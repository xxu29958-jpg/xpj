"""Manual fixed-expense create/edit contracts for the A3 product slice."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import LedgerMember, RecurringItem
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc


def _intent_headers(identity, key: str | None = None) -> dict[str, str]:
    headers = dict(identity.app_headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _manual_payload(*, merchant: str = "房租", amount_cents: int = 680_000) -> dict[str, object]:
    return {
        "merchant": merchant,
        "baseline_amount_cents": amount_cents,
        "next_expected_date": "2026-09-05",
    }


def _seed_candidate_item() -> RecurringItem:
    now = now_utc()
    with SessionLocal() as db:
        resolve_write_capability(db)
        item = RecurringItem(
            tenant_id="owner",
            merchant_key="cloud storage",
            merchant_name="Cloud Storage",
            frequency="monthly",
            baseline_amount_cents=2_000,
            last_amount_cents=1_900,
            occurrence_count=5,
            last_seen_at=now,
            next_expected_date=date(2026, 9, 8),
            status="active",
            confidence="high",
            source="candidate",
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        db.expunge(item)
        return item


def test_manual_recurring_create_replays_same_resource_once(client: TestClient, *, identity) -> None:
    key = str(uuid4())
    payload = _manual_payload()
    before_budget = client.get(
        "/api/budgets/monthly?month=2026-09&timezone=UTC",
        headers=identity.app_headers,
    )
    assert before_budget.status_code == 200, before_budget.json()

    created = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, key),
        json=payload,
    )

    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["merchant"] == "房租"
    assert body["merchant_key"] == "房租"
    assert body["frequency"] == "monthly"
    assert body["baseline_amount_cents"] == 680_000
    assert body["last_amount_cents"] == 680_000
    assert body["occurrence_count"] == 0
    assert body["last_seen_at"] is None
    assert body["confidence"] is None
    assert body["next_expected_date"] == "2026-09-05"
    assert body["status"] == "active"
    assert body["source"] == "manual"

    replay = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, key),
        json=payload,
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == body["public_id"]
    assert replay.json()["row_version"] == body["row_version"]

    after_budget = client.get(
        "/api/budgets/monthly?month=2026-09&timezone=UTC",
        headers=identity.app_headers,
    )
    assert after_budget.status_code == 200, after_budget.json()
    assert (
        after_budget.json()["fixed_amount_cents"]
        == before_budget.json()["fixed_amount_cents"] + payload["baseline_amount_cents"]
    )

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
            .where(RecurringItem.merchant_key == "房租")
        )
    assert count == 1


def test_manual_recurring_create_requires_idempotency_and_writer(client: TestClient, *, identity) -> None:
    missing_key = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity),
        json=_manual_payload(),
    )
    assert missing_key.status_code == 422, missing_key.json()
    assert missing_key.json()["error"] == "idempotency_key_required"

    editable = _seed_candidate_item()

    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()

    denied = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(),
    )
    assert denied.status_code == 403, denied.json()
    assert denied.json()["error"] == "permission_denied"

    denied_edit = client.patch(
        f"/api/recurring/items/{editable.public_id}",
        headers=_intent_headers(identity, str(uuid4())),
        json={
            "baseline_amount_cents": 2_100,
            "expected_row_version": editable.row_version,
        },
    )
    assert denied_edit.status_code == 403, denied_edit.json()
    assert denied_edit.json()["error"] == "permission_denied"


def test_manual_recurring_duplicate_points_to_edit_or_restore(client: TestClient, *, identity) -> None:
    first = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="  Monthly Rent  "),
    )
    assert first.status_code == 201, first.json()

    duplicate = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="monthly rent", amount_cents=700_000),
    )
    assert duplicate.status_code == 409, duplicate.json()
    assert duplicate.json()["error"] == "recurring_item_conflict"
    assert duplicate.json()["public_id"] == first.json()["public_id"]
    assert duplicate.json()["status"] == "active"

    archived = client.post(
        f"/api/recurring/items/{first.json()['public_id']}/archive",
        headers=identity.app_headers,
    )
    assert archived.status_code == 200, archived.json()

    archived_duplicate = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="MONTHLY RENT"),
    )
    assert archived_duplicate.status_code == 409, archived_duplicate.json()
    assert archived_duplicate.json()["error"] == "recurring_item_conflict"
    assert archived_duplicate.json()["public_id"] == first.json()["public_id"]
    assert archived_duplicate.json()["status"] == "archived"


def test_recurring_edit_preserves_observed_facts_and_replays_before_occ(client: TestClient, *, identity) -> None:
    original = _seed_candidate_item()
    key = str(uuid4())
    payload = {
        "baseline_amount_cents": 2_500,
        "next_expected_date": None,
        "expected_row_version": original.row_version,
    }

    updated = client.patch(
        f"/api/recurring/items/{original.public_id}",
        headers=_intent_headers(identity, key),
        json=payload,
    )

    assert updated.status_code == 200, updated.json()
    body = updated.json()
    assert body["merchant"] == "Cloud Storage"
    assert body["merchant_key"] == "cloud storage"
    assert body["baseline_amount_cents"] == 2_500
    assert body["next_expected_date"] is None
    assert body["last_amount_cents"] == 1_900
    assert body["occurrence_count"] == 5
    assert body["last_seen_at"] == original.last_seen_at.isoformat().replace("+00:00", "Z")
    assert body["confidence"] == "high"
    assert body["source"] == "candidate"
    assert body["row_version"] == original.row_version + 1

    replay = client.patch(
        f"/api/recurring/items/{original.public_id}",
        headers=_intent_headers(identity, key),
        json=payload,
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json()["row_version"] == body["row_version"]

    stale_new_intent = client.patch(
        f"/api/recurring/items/{original.public_id}",
        headers=_intent_headers(identity, str(uuid4())),
        json={**payload, "baseline_amount_cents": 2_600},
    )
    assert stale_new_intent.status_code == 409, stale_new_intent.json()
    assert stale_new_intent.json()["error"] == "state_conflict"


def test_manual_recurring_edit_keeps_legacy_seed_aligned_with_user_baseline(
    client: TestClient,
    *,
    identity,
) -> None:
    created = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="宽带", amount_cents=12_000),
    )
    assert created.status_code == 201, created.json()

    updated = client.patch(
        f"/api/recurring/items/{created.json()['public_id']}",
        headers=_intent_headers(identity, str(uuid4())),
        json={
            "baseline_amount_cents": 9_900,
            "expected_row_version": created.json()["row_version"],
        },
    )

    assert updated.status_code == 200, updated.json()
    assert updated.json()["baseline_amount_cents"] == 9_900
    assert updated.json()["last_amount_cents"] == 9_900
    assert updated.json()["occurrence_count"] == 0
    assert updated.json()["last_seen_at"] is None


def test_recurring_edit_rejects_no_effective_change_without_bumping_revision(
    client: TestClient,
    *,
    identity,
) -> None:
    created = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="宽带", amount_cents=12_000),
    )
    assert created.status_code == 201, created.json()
    original = created.json()

    unchanged = client.patch(
        f"/api/recurring/items/{original['public_id']}",
        headers=_intent_headers(identity, str(uuid4())),
        json={
            "merchant": original["merchant"],
            "baseline_amount_cents": original["baseline_amount_cents"],
            "next_expected_date": original["next_expected_date"],
            "expected_row_version": original["row_version"],
        },
    )

    assert unchanged.status_code == 422, unchanged.json()
    assert unchanged.json()["error"] == "recurring_item_no_changes"

    current = client.get(
        f"/api/recurring/items/{original['public_id']}",
        headers=identity.app_headers,
    )
    assert current.status_code == 200, current.json()
    assert current.json()["row_version"] == original["row_version"]


def test_archived_manual_recurring_copy_never_pretends_the_seed_was_observed(
    client: TestClient,
    *,
    identity,
) -> None:
    created = client.post(
        "/api/recurring/items",
        headers=_intent_headers(identity, str(uuid4())),
        json=_manual_payload(merchant="宽带", amount_cents=12_000),
    )
    assert created.status_code == 201, created.json()
    public_id = created.json()["public_id"]

    archived = client.post(
        f"/api/recurring/items/{public_id}/archive",
        headers=identity.app_headers,
    )
    assert archived.status_code == 200, archived.json()

    recycle_bin = client.get("/api/recycle-bin", headers=identity.app_headers)
    assert recycle_bin.status_code == 200, recycle_bin.json()
    item = next(
        row for row in recycle_bin.json()["items"]
        if row["kind"] == "recurring_item" and row["resource_id"] == public_id
    )
    assert item["detail"] == "每月 ¥120.00"
    assert "已出现" not in item["detail"]
