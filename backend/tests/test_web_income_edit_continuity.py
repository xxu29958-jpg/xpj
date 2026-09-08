"""Native income editing must retain the rendered month and immutable intent."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import IncomePlanRevision, LedgerMember, MonthlyIncomePlan
from app.routes.web_app import _require_local as _web_require_local
from app.services import income_plan_service, spending_contract_service
from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture()
def web_income(client, monkeypatch):
    clock = {"month": "2026-09", "now": datetime(2026, 9, 5, tzinfo=UTC)}
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: clock["now"])
    monkeypatch.setattr(spending_contract_service, "current_month", lambda _timezone: clock["month"])
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client, clock
    app.dependency_overrides.pop(_web_require_local, None)


def _create(client, identity):
    response = client.post("/api/income-plans", headers=negotiated_headers(client, identity.app_headers), json={
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
