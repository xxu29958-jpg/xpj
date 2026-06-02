"""ADR-0041 phase ③ Slice A — row_version groundwork (non-breaking).

Slice A adds a monotonic ``row_version`` column to the six OCC-gated models and
*maintains* it on every mutation, while the CAS predicate still rides
``updated_at`` (Slice B flips the predicate + the cross-surface token contract).

These tests lock the Slice-A invariants:

- ``row_version`` is exposed in the six responses and starts at 1.
- every guarded mutation increments it by **exactly one** — the critical guard
  against the double-bump trap: the helper claim bumps row_version via an atomic
  Core UPDATE, and the post-claim ORM flush that persists business fields must
  NOT bump it a second time (see ``optimistic_concurrency.claim_row_with_token``
  and the per-site analysis behind ``bump_row_version``).
- the inline-CAS paths (recurring pause/resume) bump too.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import RecurringItem
from app.services.time_service import now_utc
from tests.api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    recognize_text_api,
    replace_items_api,
    upload_png,
)


def _row_version(client: TestClient, expense_id: int, *, headers) -> int:
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert "row_version" in body, body
    return int(body["row_version"])


def test_expense_row_version_exposed(client: TestClient, *, identity) -> None:
    # A fresh upload is created (row_version=1) then async-enriched (one more
    # bump), so the exposed value is a positive int rather than a fixed 1; the
    # "fresh row starts at 1" contract is pinned by the rule/goal/recurring
    # direct-create tests below, which have no enrichment step.
    expense_id = upload_png(client, identity=identity)
    assert _row_version(client, expense_id, headers=identity.app_headers) >= 1


def test_expense_patch_increments_row_version_by_exactly_one(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    before = _row_version(client, expense_id, headers=identity.app_headers)

    first = patch_expense(
        client, expense_id, headers=identity.app_headers, fields={"merchant": "M1"}
    )
    assert first.status_code == 200, first.text
    # Exactly one increment, not two: the claim bumps via the atomic Core
    # UPDATE, and the business-field ORM flush must NOT double-bump.
    assert first.json()["row_version"] == before + 1
    assert _row_version(client, expense_id, headers=identity.app_headers) == before + 1

    second = patch_expense(
        client, expense_id, headers=identity.app_headers, fields={"merchant": "M2"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["row_version"] == before + 2


def test_expense_confirm_increments_row_version(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    # confirm needs an amount; that PATCH itself bumps, so snapshot AFTER it.
    primed = patch_expense(
        client, expense_id, headers=identity.app_headers, fields={"amount_cents": 1000}
    )
    assert primed.status_code == 200, primed.text
    before = primed.json()["row_version"]
    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["row_version"] == before + 1


def test_recognize_text_increments_row_version_by_exactly_one(
    client: TestClient, *, identity
) -> None:
    # The OCR/recognize flow claims the row (one bump) and then sets
    # ``expense.updated_at`` twice on the in-session instance before commit.
    # Those post-claim syncs must NOT add extra row_version bumps.
    expense_id = upload_png(client, identity=identity)
    before = _row_version(client, expense_id, headers=identity.app_headers)
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text="星巴克 ¥38.00"
    )
    assert response.status_code == 200, response.text
    assert _row_version(client, expense_id, headers=identity.app_headers) == before + 1


def test_items_replace_increments_parent_expense_row_version(
    client: TestClient, *, identity
) -> None:
    # items/splits replace CAS-claims the PARENT expense, so the parent's
    # row_version is what moves (ExpenseItem has no row_version of its own).
    expense_id = upload_png(client, identity=identity)
    before = _row_version(client, expense_id, headers=identity.app_headers)
    response = replace_items_api(
        client,
        expense_id,
        headers=identity.app_headers,
        items=[{"name": "拿铁", "amount_cents": 3800}],
    )
    assert response.status_code == 200, response.text
    assert _row_version(client, expense_id, headers=identity.app_headers) == before + 1


def _create_rule(client: TestClient, *, identity, keyword: str = "RowVerCafe") -> dict:
    response = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": keyword, "category": "餐饮", "priority": 1},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_rule_row_version_starts_at_one_and_increments(client: TestClient, *, identity) -> None:
    rule = _create_rule(client, identity=identity)
    assert rule["row_version"] == 1
    updated = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={"category": "交通", "expected_updated_at": rule["updated_at"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["row_version"] == 2


def _create_goal(client: TestClient, *, identity) -> dict:
    response = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "RowVer Goal",
            "month": "2026-05",
            "category": "餐饮",
            "target_amount_cents": 5000,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_goal_row_version_starts_at_one_and_increments(client: TestClient, *, identity) -> None:
    goal = _create_goal(client, identity=identity)
    assert goal["row_version"] == 1
    updated = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=identity.app_headers,
        json={"target_amount_cents": 6000, "expected_updated_at": goal["updated_at"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["row_version"] == 2


def _insert_recurring_item() -> str:
    """Insert a RecurringItem directly (skip candidate detection seeding)."""
    now = now_utc()
    with SessionLocal() as db:
        item = RecurringItem(
            tenant_id="owner",
            merchant_key="rowver sub",
            merchant_name="RowVer Sub",
            frequency="monthly",
            baseline_amount_cents=2000,
            last_amount_cents=2000,
            occurrence_count=3,
            status="active",
            source="candidate",
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        assert item.row_version == 1
        return item.public_id


def test_recurring_pause_resume_increment_row_version(client: TestClient, *, identity) -> None:
    # pause/resume are inline atomic CAS updates (not the shared helper); each
    # carries its own ``row_version = row_version + 1`` in the UPDATE .values().
    public_id = _insert_recurring_item()
    listed = client.get("/api/recurring/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.text
    start = next(i for i in listed.json()["items"] if i["public_id"] == public_id)
    assert start["row_version"] == 1
    token = start["updated_at"]

    paused = client.post(
        f"/api/recurring/items/{public_id}/pause",
        headers=identity.app_headers,
        json={"expected_updated_at": token},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["row_version"] == 2

    resumed = client.post(
        f"/api/recurring/items/{public_id}/resume",
        headers=identity.app_headers,
        json={"expected_updated_at": paused.json()["updated_at"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["row_version"] == 3
