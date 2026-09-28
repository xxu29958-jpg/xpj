"""Installed goal tasks retain their original identity, receipt and revision."""

import json

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Goal, GoalRevision
from app.services.identity_service import authenticate_web_session_token
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
