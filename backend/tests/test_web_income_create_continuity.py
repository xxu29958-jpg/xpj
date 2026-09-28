"""Native create preserves the rendered command through refusal and calendar rollover."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.routes.web_app import _require_local
from app.services import income_plan_service, spending_contract_service
from app.services.identity_service import authenticate_web_session_token
from app.services.manual_expense_draft_presenter import manual_draft_scope
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms

ACTION = "/web/income-plans/create"


@pytest.fixture()
def income_form(client, monkeypatch):
    clock = {"month": "2026-09", "now": datetime(2026, 9, 5, tzinfo=UTC)}
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: clock["now"])
    monkeypatch.setattr(spending_contract_service, "current_month", lambda _tz: clock["month"])
    app.dependency_overrides[_require_local] = lambda: None
    try:
        page = client.get("/web/income-plans?ledger_id=owner")
        assert page.status_code == 200, page.text
        fields = hidden_post_forms(page.text)[ACTION]
        assert fields["intent_month"] == "2026-09" and fields["idempotency_key"]
        fields.update(label="原计划", source_type="salary", frequency="monthly", amount_yuan="1200", pay_day="10",
            income_month_year="2026", income_month_number="9")
        yield client, fields, clock
    finally:
        app.dependency_overrides.pop(_require_local, None)


@pytest.mark.parametrize("frequency", ["monthly", "one_time"])
def test_original_create_month_currency_and_single_revision_survive_replay(income_form, frequency):
    client, fields, clock = income_form
    fields.update(frequency=frequency, home_currency_code="JPY")
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    for _ in range(2):
        response = client.post(ACTION, data=fields, follow_redirects=False)
        assert response.status_code == 303, response.text
    with SessionLocal() as db:
        plans = list(db.scalars(select(MonthlyIncomePlan)))
        assert len(plans) == 1
        plan = plans[0]
        assert (plan.home_currency_code, plan.amount_cents) == ("JPY", 1200)
        assert plan.income_month == ("2026-09" if frequency == "one_time" else None)
        revision = db.scalar(select(IncomePlanRevision).where(IncomePlanRevision.plan_id == plan.id))
        assert revision.intent_month.isoformat() == "2026-09-01"
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1


def test_invalid_raw_input_survives_refusal_with_original_identity(income_form):
    client, fields, clock = income_form
    fields.update(home_currency_code="JPY", amount_yuan=" 001200.50 ", pay_day="32")
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    refused = client.post(ACTION, data=fields, follow_redirects=False)
    assert refused.status_code == 422, refused.text
    retained = hidden_post_forms(refused.text)[ACTION]
    for name in ("home_currency_code", "intent_month", "idempotency_key", "ledger_id"):
        assert retained[name] == fields[name]
    assert 'value=" 001200.50 "' in refused.text and 'value="32"' in refused.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0


def test_reused_key_requires_explicit_nonwriting_preparation_for_new_plan(income_form):
    client, fields, _ = income_form
    assert client.post(ACTION, data=fields, follow_redirects=False).status_code == 303
    fields.update(label="准备另一计划", amount_yuan="2400")
    refused = client.post(ACTION, data=fields, follow_redirects=False)
    assert refused.status_code == 422, refused.text
    assert 'name="review_new"' in refused.text
    assert hidden_post_forms(refused.text)[ACTION]["idempotency_key"] == fields["idempotency_key"]
    prepared = client.post(ACTION, data={**fields, "review_new": "true"}, follow_redirects=False)
    assert prepared.status_code == 200, prepared.text
    next_fields = hidden_post_forms(prepared.text)[ACTION]
    assert next_fields["idempotency_key"] != fields["idempotency_key"]
    assert next_fields["home_currency_code"] == fields["home_currency_code"]
    assert next_fields["intent_month"] == fields["intent_month"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 1
    next_fields.update(label=fields["label"], amount_yuan=fields["amount_yuan"], source_type="salary", frequency="monthly", pay_day="10")
    assert client.post(ACTION, data=next_fields, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 2


@pytest.fixture
def installed_income_browser():
    yield from installed_web_setup()


def _installed_income_form(installed):
    token = _connect_local_session(installed)
    browser = installed.browser
    browser.base_url = browser.base_url.copy_with(scheme="https")
    with SessionLocal() as db:
        auth = authenticate_web_session_token(db, token, ttl_seconds=8 * 60 * 60).auth
        scope = manual_draft_scope(db, auth)
    page = browser.get("/web/income-plans")
    assert page.status_code == 200, page.text
    fields = {**hidden_post_forms(page.text)[ACTION], "draft_scope": json.dumps(scope),
        "label": "原收入计划", "source_type": "salary", "frequency": "monthly",
        "amount_yuan": "1500.00", "pay_day": "10", "income_month_year": "2026", "income_month_number": "9"}
    return browser, fields, scope


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_browser_income_ack_replays_original_result_after_later_edit(installed_income_browser):
    browser, fields, scope = _installed_income_form(installed_income_browser)
    headers = {"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"}
    accepted = browser.post(ACTION, data=fields, headers=headers, follow_redirects=False)
    assert accepted.status_code in {200, 303}, accepted.text
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        public_id = plan.public_id
        assert (plan.tenant_id, plan.label, plan.home_currency_code, plan.amount_cents, plan.row_version) == (
            installed_income_browser.shared_ledger_id, "原收入计划", "CNY", 150000, 1)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    assert receipt["receipt"]["public_id"] == public_id
    assert receipt["receipt"]["label"] == "原收入计划"
    assert receipt["receipt"]["amount_cents"] == 150000
    edit_action = f"/web/income-plans/{public_id}/edit"
    editor = browser.get(f"{edit_action}?intent_month={fields['intent_month']}")
    assert editor.status_code == 200, editor.text
    changed = browser.post(edit_action, data={**fields, **hidden_post_forms(editor.text)[edit_action],
        "label": "后来修改的计划", "amount_yuan": "2400", "income_month": ""},
        headers={"Origin": headers["Origin"]}, follow_redirects=False)
    assert changed.status_code == 303, changed.text
    replayed = browser.post(ACTION, data=fields, headers=headers, follow_redirects=False)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == receipt
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        assert (plan.public_id, plan.label, plan.amount_cents, plan.row_version) == (
            public_id, "后来修改的计划", 240000, 2)
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 2


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_income_draft_cannot_follow_a_replacement_browser_identity(installed_income_browser):
    browser, original, scope = _installed_income_form(installed_income_browser)
    browser.base_url = browser.base_url.copy_with(scheme="http")
    replacement = _connect_local_session(installed_income_browser)
    browser.base_url = browser.base_url.copy_with(scheme="https")
    with SessionLocal() as db:
        auth = authenticate_web_session_token(db, replacement, ttl_seconds=8 * 60 * 60).auth
        current_scope = manual_draft_scope(db, auth)
    assert current_scope["accountId"] == scope["accountId"]
    assert current_scope["ledgerId"] == scope["ledgerId"]
    assert current_scope["deviceId"] != scope["deviceId"]
    refreshed = browser.get("/web/income-plans")
    assert refreshed.status_code == 200, refreshed.text
    original["csrf_token"] = hidden_post_forms(refreshed.text)[ACTION]["csrf_token"]
    refused = browser.post(ACTION, data=original,
        headers={"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"},
        follow_redirects=False)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "session_binding_changed"


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_browser_income_refusal_can_prepare_correction_without_writing(installed_income_browser):
    browser, fields, scope = _installed_income_form(installed_income_browser)
    fields.update(pay_day="32")
    origin = str(browser.base_url).rstrip("/")
    refused = browser.post(ACTION, data=fields, headers={"Origin": origin, "Accept": "application/json"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["draft_result"] == "blocked"
    prepared = browser.post(ACTION, data={**fields, "review_new": "true"},
        headers={"Origin": origin}, follow_redirects=False)
    assert prepared.status_code == 200, prepared.text
    next_fields = hidden_post_forms(prepared.text)[ACTION]
    assert next_fields["idempotency_key"] != fields["idempotency_key"]
    for name in ("ledger_id", "draft_scope", "intent_month", "home_currency_code"):
        assert next_fields[name] == fields[name]
    assert 'value="1500.00"' in prepared.text and 'value="32"' in prepared.text
    assert 'data-income-native-result="prepared"' in prepared.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
    accepted = browser.post(ACTION, data={**fields, **next_fields, "pay_day": "12"},
        headers={"Origin": origin, "Accept": "application/json"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ack"] == {"scope": scope, "clientRef": next_fields["idempotency_key"]}
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        assert (plan.tenant_id, plan.label, plan.amount_cents, plan.pay_day, plan.row_version) == (
            installed_income_browser.shared_ledger_id, "原收入计划", 150000, 12, 1)
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_pre_binding_income_form_can_explicitly_prepare_a_bound_new_plan(installed_income_browser):
    browser, original, scope = _installed_income_form(installed_income_browser)
    original.pop("draft_scope")  # A genuine form opened before scope capture existed.
    origin = str(browser.base_url).rstrip("/")
    refused = browser.post(ACTION, data=original, headers={"Origin": origin}, follow_redirects=False)
    assert refused.status_code == 409, refused.text
    retained = hidden_post_forms(refused.text)[ACTION]
    for name in ("ledger_id", "intent_month", "home_currency_code", "idempotency_key"):
        assert retained[name] == original[name]
    assert retained["draft_scope"] == ""
    assert 'value="1500.00"' in refused.text and 'value="原收入计划"' in refused.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0
    assert "已核对，准备新计划</button>" in refused.text

    prepared = browser.post(ACTION, data={**original, **retained, "review_new": "true"},
        headers={"Origin": origin}, follow_redirects=False)
    assert prepared.status_code == 200, prepared.text
    new_form = hidden_post_forms(prepared.text)[ACTION]
    assert new_form["idempotency_key"] != original["idempotency_key"]
    assert json.loads(new_form["draft_scope"]) == scope
    for name in ("ledger_id", "intent_month", "home_currency_code"):
        assert new_form[name] == original[name]
    assert 'value="1500.00"' in prepared.text and 'value="原收入计划"' in prepared.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MonthlyIncomePlan)) == 0
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 0

    headers = {"Origin": origin, "Accept": "application/json"}
    accepted = browser.post(ACTION, data={**original, **new_form}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ack"] == {"scope": scope, "clientRef": new_form["idempotency_key"]}
    replayed = browser.post(ACTION, data={**original, **new_form}, headers=headers)
    assert replayed.status_code == 200 and replayed.json() == accepted.json()
    assert browser.post(ACTION, data=original, headers=headers).status_code == 409
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        assert (plan.tenant_id, plan.label, plan.amount_cents, plan.row_version) == (
            installed_income_browser.shared_ledger_id, "原收入计划", 150000, 1)
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 1
