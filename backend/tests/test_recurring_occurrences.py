"""The monthly obligation must reconcile with an explicitly selected payment."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember, MonthlyIncomePlan
from app.services.currency_binding_service import resolve_write_capability
from tests.test_bill_split import _seed_receiver
from tests.test_bill_split_security_regressions import _bearer_for_account_ledger


def _create_series(client: TestClient, identity) -> dict:
    response = client.post(
        "/api/recurring/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "房租",
            "baseline_amount_cents": 10_000,
            "next_expected_date": "2026-09-05",
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _payment(client: TestClient, identity) -> dict:
    response = client.post(
        "/api/expenses/manual", headers=identity.app_headers,
        json={
            "amount_cents": 10_000, "merchant": "房租", "category": "餐饮",
            "expense_time": "2026-09-05T12:00:00Z", "note": "本期完整付款",
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def test_recurring_payment_reconciles_reservation_and_replays_once(
    client: TestClient, *, identity,
) -> None:
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(MonthlyIncomePlan(
            tenant_id="owner", label="计划工资", source_type="salary",
            amount_cents=100_000, pay_day=1, status="active",
            frequency="one_time", income_month="2026-09",
        ))
        db.commit()
    series = _create_series(client, identity)
    payment = _payment(client, identity)
    path = f"/api/recurring/items/{series['public_id']}/occurrences/2026-09"
    initial = client.get(path, headers=identity.app_headers)
    assert initial.status_code == 200, initial.json()
    assert initial.json()["state"] == "unfulfilled"
    assert initial.json()["reserved_amount_cents"] == 10_000

    key = str(uuid4())
    payload = {
        "action": "link",
        "expense_public_id": payment["public_id"],
        "expected_expense_row_version": payment["row_version"],
        "expected_row_version": initial.json()["row_version"],
        "expected_series_row_version": series["row_version"],
    }
    headers = {**identity.app_headers, "Idempotency-Key": key}
    fulfilled = client.put(path, headers=headers, json=payload)
    assert fulfilled.status_code == 200, fulfilled.json()
    assert fulfilled.json()["state"] == "fulfilled"
    assert fulfilled.json()["reserved_amount_cents"] == 0
    assert fulfilled.json()["expense_public_id"] == payment["public_id"]
    assert fulfilled.json()["next_due_date"] == "2026-10-05"

    replay = client.put(path, headers=headers, json=payload)
    assert replay.status_code == 200, replay.json()
    assert replay.json() == fulfilled.json()
    after = client.get(f"/api/expenses/{payment['id']}", headers=identity.app_headers)
    assert after.json() == payment

    breakdown = client.get(
        "/api/budget/discretionary?month=2026-09&timezone=UTC",
        headers=identity.app_headers,
    )
    assert breakdown.status_code == 200, breakdown.json()
    assert breakdown.json()["spent_amount_cents"] == 10_000
    assert breakdown.json()["fixed_expenses_cents"] == 0
    assert breakdown.json()["discretionary_cents"] == 90_000

    undo_payload = {
        "action": "clear",
        "expense_public_id": None,
        "expected_row_version": fulfilled.json()["row_version"],
        "expected_series_row_version": fulfilled.json()["series_row_version"],
    }
    cleared = client.put(
        path,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=undo_payload,
    )
    assert cleared.status_code == 200, cleared.json()
    assert cleared.json()["state"] == "unfulfilled"
    assert cleared.json()["reserved_amount_cents"] == 10_000
    assert cleared.json()["next_due_date"] == "2026-09-05"
    assert cleared.json()["row_version"] > fulfilled.json()["row_version"]
    assert client.get(
        f"/api/expenses/{payment['id']}", headers=identity.app_headers,
    ).json() == payment

    # A committed command result is stable even after a later explicit undo.
    late_replay = client.put(path, headers=headers, json=payload)
    assert late_replay.status_code == 200, late_replay.json()
    assert late_replay.json() == fulfilled.json()
    assert client.get(path, headers=identity.app_headers).json()["state"] == "unfulfilled"


def _link_payload(series, payment, *, version=0):
    return {
        "action": "link",
        "expense_public_id": payment["public_id"],
        "expected_expense_row_version": payment["row_version"],
        "expected_row_version": version,
        "expected_series_row_version": series["row_version"],
    }


def test_confirmed_payment_corrected_to_zero_still_fulfills_explicit_obligation(client: TestClient, *, identity) -> None:
    series = _create_series(client, identity)
    payment = _payment(client, identity)
    path = f"/api/recurring/items/{series['public_id']}/occurrences/2026-09"
    linked = client.put(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
                        json=_link_payload(series, payment))
    assert linked.status_code == 200, linked.json()
    corrected = client.post(
        f"/api/expenses/{payment['id']}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": payment["row_version"], "reason": "核对原账单金额", "amount_cents": 0},
    )
    assert corrected.status_code == 201, corrected.json()
    current = client.get(path, headers=identity.app_headers).json()
    assert current["state"] == "fulfilled"
    assert current["paid_amount_cents"] == 0
    assert current["reserved_amount_cents"] == 0
    assert current["next_due_date"] == "2026-10-05"
    budget = client.get("/api/budget/discretionary?month=2026-09", headers=identity.app_headers).json()
    assert budget["fixed_expenses_cents"] == 0


def test_occurrence_conflicts_and_payment_reversal_are_visible(client: TestClient, *, identity) -> None:
    series = _create_series(client, identity)
    payment = _payment(client, identity)
    base = f"/api/recurring/items/{series['public_id']}/occurrences"
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    linked = client.put(f"{base}/2026-09", headers=headers, json=_link_payload(series, payment))
    assert linked.status_code == 200, linked.json()

    stale = client.put(
        f"{base}/2026-09",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "action": "clear",
            "expense_public_id": None, "expected_row_version": 0,
            "expected_series_row_version": series["row_version"],
        },
    )
    assert stale.status_code == 409, stale.json()
    duplicate = client.put(
        f"{base}/2026-10",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=_link_payload(series, payment),
    )
    assert duplicate.status_code == 409, duplicate.json()

    reversed_payment = client.post(
        f"/api/expenses/{payment['id']}/offsets",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "kind": "reversal", "accounting_date": "2026-09-06",
            "reason": "付款记录有误", "expected_row_version": payment["row_version"],
        },
    )
    assert reversed_payment.status_code == 201, reversed_payment.json()
    current = client.get(f"{base}/2026-09", headers=identity.app_headers).json()
    assert current["state"] == "needs_review"
    assert current["expense_public_id"] == payment["public_id"]
    assert current["reserved_amount_cents"] == 10_000
    assert current["next_due_date"] == "2026-09-05"
    item = client.get(f"/api/recurring/items/{series['public_id']}", headers=identity.app_headers).json()
    assert item["next_due_date"] == "2026-09-05"
    refused = client.put(
        f"{base}/2026-10",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=_link_payload(series, reversed_payment.json()["root"]),
    )
    assert refused.status_code == 409, refused.json()


def test_occurrence_enforces_ledger_writer_and_explicit_payload(client: TestClient, *, identity) -> None:
    series = _create_series(client, identity)
    payment = _payment(client, identity)
    path = f"/api/recurring/items/{series['public_id']}/occurrences/2026-09"
    other_account = _seed_receiver("另一账本", "occurrence_other")
    other_headers = _bearer_for_account_ledger(other_account, "occurrence_other")
    assert client.get(path, headers=other_headers).status_code == 404
    foreign = client.post(
        "/api/expenses/manual", headers=other_headers,
        json={"amount_cents": 10_000, "merchant": "另一笔付款", "category": "餐饮"},
    )
    assert foreign.status_code == 200, foreign.json()
    blocked = client.put(
        path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=_link_payload(series, foreign.json()),
    )
    assert blocked.status_code == 404, blocked.json()
    missing = _link_payload(series, payment)
    missing.pop("expense_public_id")
    assert client.put(
        path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json=missing,
    ).status_code == 422
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        member.role = "viewer"
        db.commit()
    denied = client.put(
        path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=_link_payload(series, payment),
    )
    assert denied.status_code == 403, denied.json()
    assert client.get(path, headers=identity.app_headers).json()["state"] == "unfulfilled"
