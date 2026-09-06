"""Real revision/OCC/receipt boundaries, beyond pure forecast projections."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import IncomePlanRevision
from tests._runtime_protocol import negotiated_headers


@pytest.mark.real_db
def test_original_edit_result_survives_a_later_edit_and_stale_commands_do_not_publish(client, identity, monkeypatch) -> None:
    from app.services import income_plan_service

    server_now = datetime(2026, 9, 30, 15, 30, tzinfo=UTC)
    monkeypatch.setattr(income_plan_service, "now_utc", lambda: server_now)
    created = client.post("/api/income-plans", headers=negotiated_headers(client, identity.app_headers), json={
        "intent_month": "2026-08", "label": "原计划", "amount_cents": 10000, "pay_day": 31,
    })
    assert created.status_code == 201
    plan = created.json()
    path = f"/api/income-plans/{plan['public_id']}"
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    original = {"intent_month": "2026-09", "expected_row_version": plan["row_version"], "amount_cents": 12000}
    first = client.patch(path, headers=negotiated_headers(client, headers), json=original)
    assert first.status_code == 200
    server_now = datetime(2026, 10, 2, tzinfo=UTC)
    later = client.patch(path, headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}), json={
        **original, "intent_month": "2026-10", "expected_row_version": first.json()["row_version"], "amount_cents": 13000,
    })
    assert later.status_code == 200
    replay = client.patch(path, headers=negotiated_headers(client, headers), json=original)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    reused_month = client.patch(path, headers=negotiated_headers(client, headers), json={**original, "intent_month": "2026-08"})
    assert reused_month.status_code == 422
    stale = client.patch(path, headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}), json=original)
    assert stale.status_code == 409
    august = client.get("/api/income-plans?month=2026-08", headers=identity.app_headers).json()
    september = client.get("/api/income-plans?month=2026-09", headers=identity.app_headers).json()
    october = client.get("/api/income-plans?month=2026-10", headers=identity.app_headers).json()
    assert august["expected_amount_cents"] == 10000
    assert september["expected_amount_cents"] == 12000
    assert october["expected_amount_cents"] == 13000
    assert september["items"][0]["row_version"] == later.json()["row_version"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 3
        for statement in ("UPDATE income_plan_revisions SET amount_cents = 1", "DELETE FROM income_plan_revisions"):
            with pytest.raises(DBAPIError):
                db.execute(text(statement))
            db.rollback()
        assert db.scalar(select(func.count()).select_from(IncomePlanRevision)) == 3


@pytest.mark.real_db
def test_frequency_conversion_and_single_month_correction_preserve_unrelated_history(identity) -> None:
    from app.services.income_plan_service import create_income_plan, income_forecast, update_income_plan

    with SessionLocal() as db:
        plan = create_income_plan(db, tenant_id="owner", label="估算", source_type="salary", amount_cents=10000,
            pay_day=1, now=datetime(2026, 8, 2, tzinfo=UTC))
        plan = update_income_plan(db, tenant_id="owner", public_id=plan.public_id, expected_row_version=plan.row_version,
            frequency="one_time", income_month="2026-11", income_month_provided=True, amount_cents=12000,
            now=datetime(2026, 9, 2, tzinfo=UTC))
        plan = update_income_plan(db, tenant_id="owner", public_id=plan.public_id, expected_row_version=plan.row_version,
            income_month="2026-06", income_month_provided=True, amount_cents=13000,
            now=datetime(2026, 12, 2, tzinfo=UTC))
        plan = update_income_plan(db, tenant_id="owner", public_id=plan.public_id, expected_row_version=plan.row_version,
            frequency="monthly", amount_cents=14000, now=datetime(2027, 1, 2, tzinfo=UTC))
        amounts = [income_forecast(db, tenant_id="owner", month=month, as_of=datetime(2027, 2, 2, tzinfo=UTC)).expected_amount_cents
            for month in ("2026-06", "2026-08", "2026-09", "2026-11", "2027-01")]
        assert amounts == [13000, 10000, 0, 0, 14000]


def _status_revisions(db, plan_id: int):
    return list(db.execute(select(
        IncomePlanRevision.revision_number, IncomePlanRevision.intent_month,
        IncomePlanRevision.effective_month, IncomePlanRevision.status, IncomePlanRevision.recorded_at,
    ).where(
        IncomePlanRevision.tenant_id == "owner", IncomePlanRevision.plan_id == plan_id,
    ).order_by(IncomePlanRevision.revision_number)))


def _interleave_status_claim(monkeypatch, competing_command) -> None:
    from app.services import income_plan_service

    original_claim = income_plan_service.claim_row_with_token

    def claim_after_competitor(*args, **kwargs):
        monkeypatch.setattr(income_plan_service, "claim_row_with_token", original_claim)
        competing_command()
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(income_plan_service, "claim_row_with_token", claim_after_competitor)


@pytest.mark.real_db
@pytest.mark.parametrize("after_occ", [False, True], ids=["first-read", "after-occ"])
@pytest.mark.parametrize(("action", "winning_month", "expected_totals"), [
    ("archive", "2026-09", [0, 0]),
    ("archive", "2026-10", [10000, 0]),
    ("restore", "2026-09", [10000, 10000]),
    ("restore", "2026-10", [0, 10000]),
])
def test_status_replay_preserves_the_declared_month_and_committed_history(
    identity, monkeypatch, after_occ, action, winning_month, expected_totals,
) -> None:
    from app.errors import AppError
    from app.services import income_plan_service

    when = datetime(2026, 12, 2, tzinfo=UTC)
    command = getattr(income_plan_service, f"{action}_income_plan")
    with SessionLocal() as db:
        plan = income_plan_service.create_income_plan(db, tenant_id="owner", label="月份重放", source_type="salary",
            amount_cents=10000, pay_day=1, intent_month="2026-08", now=when)
        if action == "restore":
            plan = income_plan_service.archive_income_plan(db, tenant_id="owner", public_id=plan.public_id,
                expected_row_version=plan.row_version, intent_month="2026-08", now=when)
        public_id, plan_id, original_token = plan.public_id, plan.id, plan.row_version
        winner = []

        def competing_command() -> None:
            with SessionLocal() as other:
                committed = command(other, tenant_id="owner", public_id=public_id,
                    expected_row_version=original_token, intent_month=winning_month, now=when)
                winner.append((_status_revisions(other, plan_id), committed.row_version, committed.archived_at))

        if after_occ:
            _interleave_status_claim(monkeypatch, competing_command)
        else:
            competing_command()
            db.expire_all()
        original = {"tenant_id": "owner", "public_id": public_id, "expected_row_version": original_token,
            "intent_month": "2026-09", "now": when}
        if winning_month == "2026-09":
            command(db, **original)
        else:
            with pytest.raises(AppError) as error:
                command(db, **original)
            assert error.value.error == "state_conflict"
        current = income_plan_service.get_income_plan(db, tenant_id="owner", public_id=public_id)
        assert (_status_revisions(db, plan_id), current.row_version, current.archived_at) == winner[0]
        assert current.row_version == original_token + 1
        totals = [income_plan_service.income_forecast(db, tenant_id="owner", month=month, as_of=when).expected_amount_cents
            for month in ("2026-09", "2026-10")]
        assert totals == expected_totals
