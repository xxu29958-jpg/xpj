"""Installed goal tasks retain their original identity, receipt and revision."""

import json
import re

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Budget, Expense, Goal, GoalRevision, IncomePlanRevision, LedgerMember
from app.services.identity_service import authenticate_web_session_token
from app.services.income_plan_service import income_forecast
from app.services.manual_expense_draft_presenter import manual_draft_scope
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture
def installed_goal_browser():
    yield from installed_web_setup()


def _scope(token):
    with SessionLocal() as db:
        return manual_draft_scope(db, authenticate_web_session_token(db, token, ttl_seconds=8 * 60 * 60).auth)


def _facts():
    with SessionLocal() as db:
        goals = [(g.public_id, g.tenant_id, g.name, g.month, g.category, g.home_currency_code,
            g.target_amount_cents, g.row_version) for g in db.scalars(select(Goal).order_by(Goal.id))]
        revisions = [(r.row_version, r.change_kind, r.snapshot) for r in db.scalars(
            select(GoalRevision).order_by(GoalRevision.id))]
        return goals, revisions


def _original(installed, kind):
    scope = _scope(_connect_local_session(installed))
    browser = installed.browser
    browser.base_url = browser.base_url.copy_with(scheme="https")
    page = browser.get("/web/goals", params={"month": "2026-09"})
    assert page.status_code == 200, page.text
    action = "/web/goals/create"
    fields = {**hidden_post_forms(page.text)[action], "draft_scope": json.dumps(scope),
        "name": "原消费目标", "month": "2026-09", "category": "餐饮", "target_amount_yuan": "200.00"}
    origin = {"Origin": str(browser.base_url).rstrip("/")}
    if kind == "edit":
        created = browser.post(action, data=fields, headers=origin, follow_redirects=False)
        assert created.status_code == 303, created.text
        goals, revisions = _facts()
        assert len(goals) == len(revisions) == 1 and goals[0][6:] == (20000, 1)
        action = f"/web/goals/{goals[0][0]}/edit"
        editor = browser.get(action, params={"return_category": "餐饮", "return_month": "2026-09"})
        assert editor.status_code == 200, editor.text
        fields.update(hidden_post_forms(editor.text)[action])
    fields.update(name="原稿目标", target_amount_yuan="350.25")
    return browser, action, fields, scope, origin


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", ["create", "edit"])
def test_installed_goal_keeps_original_ack_after_a_later_revision(installed_goal_browser, kind):
    browser, action, fields, scope, origin = _original(installed_goal_browser, kind)
    expected_version = 1 if kind == "create" else 2
    accepted = browser.post(action, data=fields, headers={**origin, "Accept": "application/json"}, follow_redirects=False)
    assert accepted.status_code in {200, 303}, accepted.text
    goals, revisions = _facts()
    public_id = goals[0][0]
    assert goals == [(public_id, installed_goal_browser.shared_ledger_id, "原稿目标", "2026-09", "餐饮",
        "CNY", 35025, expected_version)]
    assert len(revisions) == expected_version
    assert accepted.status_code == 200, "Accepted goal work must acknowledge its original draft"
    result = accepted.json()
    assert result["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    assert (result["receipt"]["public_id"], result["receipt"]["row_version"],
        result["receipt"]["target_amount_cents"]) == (public_id, expected_version, 35025)
    edit_action = f"/web/goals/{public_id}/edit"
    editor = browser.get(edit_action)
    assert editor.status_code == 200, editor.text
    later = {**fields, **hidden_post_forms(editor.text)[edit_action], "name": "后来调整", "month": "2026-10",
        "category": "交通", "target_amount_yuan": "400.00"}
    assert later["idempotency_key"] != fields["idempotency_key"]
    changed = browser.post(edit_action, data=later, headers=origin, follow_redirects=False)
    assert changed.status_code == 303, changed.text
    after = _facts()
    assert after[0] == [(public_id, installed_goal_browser.shared_ledger_id, "后来调整", "2026-10", "交通",
        "CNY", 40000, expected_version + 1)]
    assert len(after[1]) == expected_version + 1
    replayed = browser.post(action, data=fields, headers={**origin, "Accept": "application/json"}, follow_redirects=False)
    assert replayed.status_code == 200 and replayed.json() == result, replayed.text
    assert _facts() == after


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", ["create", "edit"])
def test_replacement_browser_cannot_publish_an_original_goal_task(installed_goal_browser, kind):
    browser, action, fields, scope, origin = _original(installed_goal_browser, kind)
    before = _facts()
    browser.base_url = browser.base_url.copy_with(scheme="http")
    replacement = _scope(_connect_local_session(installed_goal_browser))
    browser.base_url = browser.base_url.copy_with(scheme="https")
    assert replacement["accountId"] == scope["accountId"] and replacement["ledgerId"] == scope["ledgerId"]
    assert replacement["deviceId"] != scope["deviceId"]
    page = browser.get("/web/goals" if kind == "create" else action, params={"month": fields["month"]})
    assert page.status_code == 200, page.text
    fields["csrf_token"] = hidden_post_forms(page.text)[action]["csrf_token"]
    refused = browser.post(action, data=fields, headers={**origin, "Accept": "application/json"}, follow_redirects=False)
    assert _facts() == before, "The new browser identity must not publish the former device's goal"
    assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed", refused.text
    reviewed = browser.post(action, data={**fields, "review_new" if kind == "create" else "review_latest": "true"},
        headers={**origin, "Accept": "application/json"})
    assert reviewed.status_code == 409 and reviewed.json()["error"] == "session_binding_changed", reviewed.text
    assert _facts() == before


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", ["create", "edit"])
def test_goal_read_only_reopening_keeps_original_then_saves_once(installed_goal_browser, kind):
    installed = installed_goal_browser
    browser, action, fields, scope, origin = _original(installed, kind)
    before = _facts()
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == installed.shared_ledger_id,
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "viewer"
        db.commit()
    page = browser.get("/web/goals" if kind == "create" else action)
    assert page.status_code == 200 and 'data-goal-can-write="false"' in page.text, page.text
    current = hidden_post_forms(page.text)[action]
    assert json.loads(current["draft_scope"]) == scope
    fields["csrf_token"] = current["csrf_token"]
    headers = {**origin, "Accept": "application/json"}
    refused = browser.post(action, data=fields, headers=headers)
    assert refused.status_code == 403 and refused.json()["error"] == "permission_denied", refused.text
    assert _facts() == before
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == installed.shared_ledger_id,
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "member"
        db.commit()
    accepted = browser.post(action, data=fields, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    goals, revisions = _facts()
    assert goals[0][2:] == ("原稿目标", "2026-09", "餐饮", "CNY", 35025, 1 if kind == "create" else 2)
    assert len(revisions) == len(before[1]) + 1
    replayed = browser.post(action, data=fields, headers=headers)
    assert replayed.status_code == 200 and replayed.json() == accepted.json(), replayed.text
    assert _facts() == (goals, revisions)


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", ["create", "edit"])
def test_goal_pre_binding_form_can_prepare_explicit_correction_without_writing(installed_goal_browser, kind):
    browser, action, fields, scope, origin = _original(installed_goal_browser, kind)
    before = _facts()
    fields.pop("draft_scope")
    refused = browser.post(action, data=fields, headers=origin)
    assert refused.status_code == 409, refused.text
    retained = hidden_post_forms(refused.text)[action]
    for name in ("ledger_id", "month", "home_currency_code", "idempotency_key"):
        assert retained[name] == fields[name]
    assert retained["draft_scope"] == "" and 'value="350.25"' in refused.text
    assert _facts() == before
    review_name = "review_new" if kind == "create" else "review_latest"
    prepared = browser.post(action, data={**fields, **retained, review_name: "true"}, headers=origin)
    assert prepared.status_code == 200 and 'data-goal-native-result="prepared"' in prepared.text, prepared.text
    proposal = hidden_post_forms(prepared.text)[action]
    assert proposal["idempotency_key"] != fields["idempotency_key"]
    assert json.loads(proposal["draft_scope"]) == scope and _facts() == before
    accepted = browser.post(action, data={**fields, **proposal}, headers={**origin, "Accept": "application/json"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ack"] == {"scope": scope, "clientRef": proposal["idempotency_key"]}
    goals, revisions = _facts()
    assert goals[0][2:] == ("原稿目标", "2026-09", "餐饮", "CNY", 35025, 1 if kind == "create" else 2)
    assert len(revisions) == len(before[1]) + 1


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_household_can_plan_income_and_spending_then_revise_without_creating_financial_facts(installed_goal_browser):
    browser, goal_action, goal_fields, scope, origin = _original(installed_goal_browser, "create")
    headers = {**origin, "Accept": "application/json"}
    income_action = "/web/income-plans/create"
    income_page = browser.get("/web/income-plans")
    assert income_page.status_code == 200, income_page.text
    income_fields = {**hidden_post_forms(income_page.text)[income_action], "label": "家庭工资预测",
        "amount_yuan": "5000.00", "source_type": "salary", "frequency": "monthly", "pay_day": "31"}
    month = income_fields["intent_month"]
    income = browser.post(income_action, data=income_fields, headers=headers)
    assert income.status_code == 200, income.text
    income_receipt = income.json()
    _assert_household_forecast(browser, scope["ledgerId"], month, 500000, "5000.00")
    goal_fields.update(name="本月餐饮提醒", month=month, target_amount_yuan="2000.00")
    goal = browser.post(goal_action, data=goal_fields, headers=headers)
    assert goal.status_code == 200, goal.text
    goal_receipt = goal.json()
    assert goal_receipt["receipt"]["spent_amount_cents"] == 0
    goal_page = browser.get(goal_receipt["next"])
    assert goal_page.status_code == 200 and "本月餐饮提醒" in goal_page.text and "0.00 / 2000.00" in goal_page.text
    income_edit = f'/web/income-plans/{income_receipt["receipt"]["public_id"]}/edit'
    editor = browser.get(income_edit, params={"intent_month": month})
    changed_income = browser.post(income_edit, data={**income_fields, **hidden_post_forms(editor.text)[income_edit],
        "amount_yuan": "6000.00"}, headers=headers)
    assert changed_income.status_code == 200 and changed_income.json()["receipt"]["row_version"] == 2, changed_income.text
    _assert_household_forecast(browser, scope["ledgerId"], month, 600000, "6000.00")
    goal_edit = f'/web/goals/{goal_receipt["receipt"]["public_id"]}/edit'
    editor = browser.get(goal_edit)
    changed_goal = browser.post(goal_edit, data={**goal_fields, **hidden_post_forms(editor.text)[goal_edit],
        "name": "调整后的餐饮提醒", "target_amount_yuan": "2200.00"}, headers=headers)
    assert changed_goal.status_code == 200 and changed_goal.json()["receipt"]["row_version"] == 2, changed_goal.text
    history = browser.get(f'/web/goals/{goal_receipt["receipt"]["public_id"]}/history')
    assert history.status_code == 200 and "本月餐饮提醒" in history.text and "调整后的餐饮提醒" in history.text
    assert "2000.00" in history.text and "2200.00" in history.text
    original_income = browser.post(income_action, data=income_fields, headers=headers)
    original_goal = browser.post(goal_action, data=goal_fields, headers=headers)
    assert original_income.status_code == 200 and original_income.json() == income_receipt
    assert original_goal.status_code == 200 and original_goal.json() == goal_receipt
    _assert_household_forecast(browser, scope["ledgerId"], month, 600000, "6000.00")
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
        assert db.scalar(select(func.count()).select_from(Budget)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 2
        assert db.scalar(select(func.count()).select_from(GoalRevision)) == 2


def _assert_household_forecast(browser, ledger_id, month, amount, display):
    page = browser.get("/web/income-plans")
    assert page.status_code == 200, page.text
    summary = re.search(r'<section[^>]+aria-label="本月预计收入"[^>]*>(.*?)</section>', page.text, re.S)
    assert summary and display in summary.group(1) and "不代表实际到账或账户余额" in summary.group(1)
    with SessionLocal() as db:
        assert income_forecast(db, tenant_id=ledger_id, month=month).expected_amount_cents == amount
