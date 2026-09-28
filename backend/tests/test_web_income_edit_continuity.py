"""Native income editing must retain the rendered month and immutable intent."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import IncomePlanRevision, LedgerMember, MonthlyIncomePlan
from app.routes import income_plans, web_income_edit, web_income_plans
from app.routes.web_app import _require_local as _web_require_local
from app.services import income_plan_service
from app.services.identity_service import authenticate_web_session_token
from app.services.manual_expense_draft_presenter import manual_draft_scope
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture()
def web_income(client, monkeypatch):
    clock = {"month": "2026-09", "now": datetime(2026, 9, 5, tzinfo=UTC)}
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: clock["now"])
    for routes in (income_plans, web_income_edit, web_income_plans):
        monkeypatch.setattr(routes, "current_ledger_month", lambda _db, *, ledger_id: clock["month"])
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client, clock
    app.dependency_overrides.pop(_web_require_local, None)


def _create(client, identity):
    response = client.post("/api/income-plans", headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}, json={"home_currency_code": "CNY",
        "label": "工资计划", "frequency": "monthly", "source_type": "salary",
        "amount_cents": 100000, "pay_day": 5, "intent_month": "2026-08",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _edit(client, public_id):
    action = f"/web/income-plans/{public_id}/edit"
    page = client.get("/web/income-plans?ledger_id=owner")
    assert action + "?" in page.text
    editor = client.get(action, params={"ledger_id": "owner", "intent_month": "2026-09"})
    assert editor.status_code == 200, editor.text
    fields = hidden_post_forms(editor.text)[action]
    assert fields["intent_month"] == "2026-09" and fields["idempotency_key"]
    fields.update(label="调整后的工资", frequency="monthly", source_type="salary", amount_yuan="2000.25", pay_day="5", income_month="")
    return action, fields


def _revisions(public_id):
    with SessionLocal() as db:
        plan = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == public_id))
        return [(r.revision_number, r.intent_month.isoformat(), r.amount_cents) for r in db.scalars(
            select(IncomePlanRevision).where(IncomePlanRevision.plan_id == plan.id).order_by(IncomePlanRevision.revision_number),
        )]


def test_rendered_month_survives_calendar_change_and_replay_does_not_publish_again(web_income, identity):
    client, clock = web_income
    plan = _create(client, identity)
    before = _revisions(plan["public_id"])
    action, fields = _edit(client, plan["public_id"])
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    saved = client.post(action, data=fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    assert client.post(action, data=fields, follow_redirects=False).status_code == 303
    revisions = _revisions(plan["public_id"])
    assert revisions == before + [(plan["row_version"] + 1, "2026-09-01", 200025)]
    for month, expected in (("2026-08", 100000), ("2026-09", 200025)):
        forecast = client.get("/api/income-plans", params={"month": month}, headers=identity.app_headers)
        assert forecast.status_code == 200 and forecast.json()["expected_amount_cents"] == expected
    fields.update(label="再次修改", amount_yuan="2100.25")
    reused = client.post(action, data=fields)
    assert reused.status_code == 422 and 'value="再次修改"' in reused.text
    assert 'name="review_latest"' in reused.text
    assert hidden_post_forms(reused.text)[action]["idempotency_key"] == fields["idempotency_key"]
    assert _revisions(plan["public_id"]) == revisions


def test_refusal_retains_input_and_review_of_a_later_month_never_submits_a_write(web_income, identity):
    client, clock = web_income
    plan = _create(client, identity)
    action, fields = _edit(client, plan["public_id"])
    invalid = client.post(action, data={**fields, "amount_yuan": "bad-amount"})
    assert invalid.status_code == 422 and 'value="bad-amount"' in invalid.text
    assert hidden_post_forms(invalid.text)[action]["idempotency_key"] == fields["idempotency_key"]
    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    parallel = client.patch(f'/api/income-plans/{plan["public_id"]}', headers={
        **negotiated_headers(client, identity.app_headers), "Idempotency-Key": "parallel-income-month",
    }, json={"label": "另一端已更新", "expected_row_version": plan["row_version"], "intent_month": "2026-10"})
    assert parallel.status_code == 200, parallel.text
    before = _revisions(plan["public_id"])
    refused = client.post(action, data=fields)
    assert refused.status_code == 409 and 'value="调整后的工资"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    assert all(retained[key] == fields[key] for key in ("idempotency_key", "expected_row_version", "intent_month"))
    reviewed = client.post(action, data={**fields, "review_latest": "true"})
    assert reviewed.status_code == 200 and 'value="调整后的工资"' in reviewed.text
    proposal = hidden_post_forms(reviewed.text)[action]
    assert proposal["intent_month"] == "2026-10" and proposal["idempotency_key"] != fields["idempotency_key"]
    assert int(proposal["expected_row_version"]) == parallel.json()["row_version"]
    assert _revisions(plan["public_id"]) == before


def test_viewer_and_unknown_ledger_cannot_publish_income_revisions(web_income, identity):
    client, _ = web_income
    plan = _create(client, identity)
    action, fields = _edit(client, plan["public_id"])
    before = _revisions(plan["public_id"])
    assert client.post(action, data={**fields, "ledger_id": "unavailable-ledger"}).status_code == 400
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()
    assert action + "?" not in client.get("/web/income-plans?ledger_id=owner").text
    assert client.post(action, data=fields).status_code == 403
    assert _revisions(plan["public_id"]) == before


@pytest.mark.parametrize("review_latest", [False, True])
def test_permission_refusal_keeps_the_original_form_and_resumes_once_after_month_rollover(web_income, identity, review_latest):
    client, clock = web_income
    plan = _create(client, identity)
    action, fields = _edit(client, plan["public_id"])
    if review_latest:
        fields["review_latest"] = "true"
    before = _revisions(plan["public_id"])
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        original_role = member.role
        member.role = "viewer"
        db.commit()

    clock.update(month="2026-10", now=datetime(2026, 10, 2, tzinfo=UTC))
    refused = client.post(action, data=fields)
    assert refused.status_code == 403
    assert _revisions(plan["public_id"]) == before
    forms = hidden_post_forms(refused.text)
    assert action in forms, "A write-only refusal must keep the original income form available for continuation"
    retained = forms[action]
    assert all(retained[key] == fields[key] for key in ("ledger_id", "intent_month", "expected_row_version", "idempotency_key"))
    assert 'value="调整后的工资"' in refused.text and 'value="2000.25"' in refused.text
    assert "权限恢复后重试" in refused.text
    assert ("权限恢复后重试核对" in refused.text) == review_latest
    assert client.post(action, data={**fields, **retained}).status_code == 403
    assert _revisions(plan["public_id"]) == before

    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = original_role
        db.commit()
    # Resume the retained original; permission recovery cannot invent a new key, month or version.
    resumed = {**fields, **retained}
    if review_latest:
        reviewed = client.post(action, data=resumed, follow_redirects=False)
        assert reviewed.status_code == 200
        prepared = hidden_post_forms(reviewed.text)[action]
        assert prepared["intent_month"] == "2026-10"
        assert prepared["idempotency_key"] != fields["idempotency_key"]
        assert 'value="调整后的工资"' in reviewed.text and 'value="2000.25"' in reviewed.text
        assert _revisions(plan["public_id"]) == before, "Resuming an explicit review must never publish a save"
        return
    assert client.post(action, data=resumed, follow_redirects=False).status_code == 303
    assert client.post(action, data=resumed, follow_redirects=False).status_code == 303
    assert _revisions(plan["public_id"]) == before + [(plan["row_version"] + 1, "2026-09-01", 200025)]


@pytest.fixture
def installed_income_editor():
    yield from installed_web_setup()


def _installed_edit_form(installed):
    token = _connect_local_session(installed)
    browser = installed.browser
    browser.base_url = browser.base_url.copy_with(scheme="https")
    with SessionLocal() as db:
        auth = authenticate_web_session_token(db, token, ttl_seconds=8 * 60 * 60).auth
        scope = manual_draft_scope(db, auth)
    page = browser.get("/web/income-plans")
    assert page.status_code == 200, page.text
    create_action = "/web/income-plans/create"
    original = {**hidden_post_forms(page.text)[create_action], "draft_scope": json.dumps(scope),
        "label": "原工资计划", "source_type": "salary", "frequency": "monthly",
        "amount_yuan": "1000.00", "pay_day": "10"}
    created = browser.post(create_action, data=original,
        headers={"Origin": str(browser.base_url).rstrip("/")}, follow_redirects=False)
    assert created.status_code == 303, created.text
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        public_id = plan.public_id
        assert (plan.tenant_id, plan.amount_cents, plan.row_version) == (installed.shared_ledger_id, 100000, 1)
    action = f"/web/income-plans/{public_id}/edit"
    editor = browser.get(action, params={"intent_month": original["intent_month"]})
    assert editor.status_code == 200, editor.text
    fields = {**hidden_post_forms(editor.text)[action], "draft_scope": json.dumps(scope),
        "label": "原稿调薪", "source_type": "salary", "frequency": "monthly",
        "amount_yuan": "2000.25", "pay_day": "10", "income_month": ""}
    return browser, action, fields, scope, public_id


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_bound_income_edit_replays_its_original_ack_after_a_later_revision(installed_income_editor):
    browser, action, fields, scope, public_id = _installed_edit_form(installed_income_editor)
    before = _revisions(public_id)
    headers = {"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"}
    accepted = browser.post(action, data=fields, headers=headers, follow_redirects=False)
    assert accepted.status_code in {200, 303}, accepted.text
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        assert (plan.public_id, plan.label, plan.home_currency_code, plan.amount_cents, plan.row_version) == (
            public_id, "原稿调薪", "CNY", 200025, 2)
    assert _revisions(public_id) == before + [(2, fields["intent_month"] + "-01", 200025)]
    assert accepted.status_code == 200, "An accepted edit must acknowledge the captured original, not redirect it away"
    original_result = accepted.json()
    assert original_result["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    assert (original_result["receipt"]["public_id"], original_result["receipt"]["row_version"],
        original_result["receipt"]["amount_cents"]) == (public_id, 2, 200025)

    later_page = browser.get(action, params={"intent_month": fields["intent_month"]})
    assert later_page.status_code == 200, later_page.text
    later = {**fields, **hidden_post_forms(later_page.text)[action], "label": "后来调薪", "amount_yuan": "3000.50"}
    assert later["idempotency_key"] != fields["idempotency_key"] and later["expected_row_version"] == "2"
    changed = browser.post(action, data=later, headers={"Origin": headers["Origin"]}, follow_redirects=False)
    assert changed.status_code == 303, changed.text
    replayed = browser.post(action, data=fields, headers=headers, follow_redirects=False)
    assert replayed.status_code == 200 and replayed.json() == original_result, replayed.text
    assert _revisions(public_id) == before + [(2, fields["intent_month"] + "-01", 200025),
        (3, fields["intent_month"] + "-01", 300050)]


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_income_edit_from_another_browser_identity_cannot_publish_a_revision(installed_income_editor):
    browser, action, fields, scope, public_id = _installed_edit_form(installed_income_editor)
    before = _revisions(public_id)
    browser.base_url = browser.base_url.copy_with(scheme="http")
    replacement = _connect_local_session(installed_income_editor)
    browser.base_url = browser.base_url.copy_with(scheme="https")
    with SessionLocal() as db:
        auth = authenticate_web_session_token(db, replacement, ttl_seconds=8 * 60 * 60).auth
        current_scope = manual_draft_scope(db, auth)
    assert current_scope["accountId"] == scope["accountId"] and current_scope["ledgerId"] == scope["ledgerId"]
    assert current_scope["deviceId"] != scope["deviceId"]
    current_page = browser.get(action, params={"intent_month": fields["intent_month"]})
    assert current_page.status_code == 200, current_page.text
    fields["csrf_token"] = hidden_post_forms(current_page.text)[action]["csrf_token"]
    refused = browser.post(action, data=fields,
        headers={"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"},
        follow_redirects=False)
    assert _revisions(public_id) == before, "The replacement device must not publish the former device's draft"
    with SessionLocal() as db:
        plan, = list(db.scalars(select(MonthlyIncomePlan)))
        assert (plan.public_id, plan.label, plan.amount_cents, plan.row_version) == (public_id, "原工资计划", 100000, 1)
    assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed", refused.text
