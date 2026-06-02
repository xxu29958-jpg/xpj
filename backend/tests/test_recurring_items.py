"""v0.6 recurring item API contract and permission guards."""

from __future__ import annotations

from datetime import UTC, datetime

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember, RecurringItem
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _seed_monthly_candidate(*, merchant: str = "ChatGPT Plus", amount_cents: int = 20000) -> datetime:
    last_seen = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for when in (
        datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        last_seen,
    ):
        insert_confirmed_expense(
            amount_cents=amount_cents,
            merchant=merchant,
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )
    return last_seen


def _confirm_candidate(
    client: TestClient,
    *, identity,
    merchant: str = "ChatGPT Plus",
    amount_cents: int = 20000,
) -> dict:
    last_seen = _seed_monthly_candidate(merchant=merchant, amount_cents=amount_cents)
    response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": merchant,
            "amount_cents": amount_cents,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def _assert_permission_denied(response, *, label: str) -> None:
    assert response.status_code == 403, label
    payload = response.json()
    assert payload["error"] == "permission_denied", label
    assert payload["message"] == VIEWER_WRITE_MESSAGE, label


def test_recurring_candidate_confirm_creates_item_and_is_idempotent(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)

    assert item["ledger_id"] == "owner"
    assert item["merchant"] == "ChatGPT Plus"
    assert item["merchant_key"] == "chatgpt plus"
    assert item["frequency"] == "monthly"
    assert item["baseline_amount_cents"] == 20000
    assert item["last_amount_cents"] == 20000
    assert item["occurrence_count"] == 3
    assert item["last_seen_at"] == "2026-05-05T12:00:00Z"
    assert item["next_expected_date"] == "2026-06-05"
    assert item["status"] == "active"
    assert item["source"] == "candidate"

    again = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "ChatGPT Plus",
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": "2026-05-05T12:00:00Z",
            "confidence": "high",
        },
    )
    assert again.status_code == 200, again.json()
    assert again.json()["public_id"] == item["public_id"]

    listed = client.get("/api/recurring/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert [entry["public_id"] for entry in listed.json()["items"]] == [item["public_id"]]


def test_recurring_candidate_next_expected_uses_local_expense_date(client: TestClient, *, identity) -> None:
    merchant = "Boundary Billing"
    amount_cents = 9900
    last_seen = datetime(2026, 4, 30, 16, 30, tzinfo=UTC)
    for when in (
        datetime(2026, 2, 28, 16, 30, tzinfo=UTC),
        datetime(2026, 3, 31, 16, 30, tzinfo=UTC),
        last_seen,
    ):
        insert_confirmed_expense(
            amount_cents=amount_cents,
            merchant=merchant,
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )

    response = client.post(
        "/api/recurring/from-candidate?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={
            "merchant": merchant,
            "amount_cents": amount_cents,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["last_seen_at"] == "2026-04-30T16:30:00Z"
    assert response.json()["next_expected_date"] == "2026-06-01"


def test_recurring_item_state_transitions(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)
    public_id = item["public_id"]
    token = item["row_version"]

    paused = client.post(
        f"/api/recurring/items/{public_id}/pause",
        headers=identity.app_headers,
        json={"expected_row_version": token},
    )
    assert paused.status_code == 200, paused.json()
    assert paused.json()["status"] == "paused"
    assert paused.json()["paused_at"] is not None
    token = paused.json()["row_version"]

    resumed = client.post(
        f"/api/recurring/items/{public_id}/resume",
        headers=identity.app_headers,
        json={"expected_row_version": token},
    )
    assert resumed.status_code == 200, resumed.json()
    assert resumed.json()["status"] == "active"
    assert resumed.json()["paused_at"] is None

    archived = client.post(f"/api/recurring/items/{public_id}/archive", headers=identity.app_headers)
    assert archived.status_code == 200, archived.json()
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None

    hidden = client.get("/api/recurring/items", headers=identity.app_headers)
    assert hidden.status_code == 200, hidden.json()
    assert hidden.json()["items"] == []

    visible = client.get("/api/recurring/items?include_archived=true", headers=identity.app_headers)
    assert visible.status_code == 200, visible.json()
    assert [entry["public_id"] for entry in visible.json()["items"]] == [public_id]

    blocked = client.post(
        f"/api/recurring/items/{public_id}/resume",
        headers=identity.app_headers,
        json={"expected_row_version": visible.json()["items"][0]["row_version"]},
    )
    assert blocked.status_code == 409, blocked.json()
    assert blocked.json()["error"] == "recurring_item_archived"


def test_confirm_candidate_reactivates_archived_item(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)
    public_id = item["public_id"]

    archived = client.post(f"/api/recurring/items/{public_id}/archive", headers=identity.app_headers)
    assert archived.status_code == 200, archived.json()
    assert archived.json()["status"] == "archived"

    last_seen = _seed_monthly_candidate(merchant="ChatGPT Plus", amount_cents=20000)
    response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "ChatGPT Plus",
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["public_id"] == public_id
    assert payload["status"] == "active"
    assert payload["archived_at"] is None
    assert payload["paused_at"] is None

    listed = client.get("/api/recurring/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert [entry["public_id"] for entry in listed.json()["items"]] == [public_id]


def test_viewer_cannot_mutate_recurring_items(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)
    public_id = item["public_id"]
    _demote_owner_ledger_to_viewer()

    create_response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "ChatGPT Plus",
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": "2026-05-05T12:00:00Z",
        },
    )
    _assert_permission_denied(create_response, label="viewer confirm recurring candidate")

    for label, path in (
        ("pause", f"/api/recurring/items/{public_id}/pause"),
        ("resume", f"/api/recurring/items/{public_id}/resume"),
        ("archive", f"/api/recurring/items/{public_id}/archive"),
    ):
        _assert_permission_denied(client.post(path, headers=identity.app_headers), label=label)


def test_recurring_items_are_ledger_isolated(client: TestClient, *, identity) -> None:
    owner_item = _confirm_candidate(client, identity=identity)

    owner_list = client.get("/api/recurring/items", headers=identity.app_headers)
    assert owner_list.status_code == 200, owner_list.json()
    assert [entry["public_id"] for entry in owner_list.json()["items"]] == [owner_item["public_id"]]

    gray_list = client.get("/api/recurring/items", headers=identity.gray_app_headers)
    assert gray_list.status_code == 200, gray_list.json()
    assert gray_list.json()["items"] == []

    gray_detail = client.get(f"/api/recurring/items/{owner_item['public_id']}", headers=identity.gray_app_headers)
    assert gray_detail.status_code == 404, gray_detail.json()
    assert gray_detail.json()["error"] == "recurring_item_not_found"


def test_recurring_items_mark_current_month_amount_anomaly(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)
    expensive_monthly_charge = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    insert_confirmed_expense(
        amount_cents=28000,
        merchant="ChatGPT Plus",
        category="AI订阅",
        expense_time=expensive_monthly_charge,
        confirmed_at=expensive_monthly_charge,
    )

    listed = client.get("/api/recurring/items?month=2026-05&timezone=UTC", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    current = listed.json()["items"][0]
    assert current["public_id"] == item["public_id"]
    assert current["anomaly_status"] == "higher_than_average"
    assert current["current_month_amount_cents"] == 28000
    assert current["historical_average_amount_cents"] == 20000
    assert current["amount_delta_percent"] == 40
    assert current["last_amount_cents"] == 20000


def test_recurring_anomaly_ignores_unrelated_same_merchant_large_purchase(client: TestClient, *, identity) -> None:
    item = _confirm_candidate(client, identity=identity)
    one_off_purchase = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    insert_confirmed_expense(
        amount_cents=120000,
        merchant="ChatGPT Plus",
        category="AI订阅",
        expense_time=one_off_purchase,
        confirmed_at=one_off_purchase,
    )

    listed = client.get("/api/recurring/items?month=2026-05&timezone=UTC", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    current = listed.json()["items"][0]
    assert current["public_id"] == item["public_id"]
    assert current["anomaly_status"] == "none"
    assert current["current_month_amount_cents"] == 20000


def test_recurring_status_filter_and_invalid_candidate_errors(client: TestClient, *, identity) -> None:
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key="netflix",
                merchant_name="Netflix",
                frequency="monthly",
                baseline_amount_cents=6800,
                last_amount_cents=6800,
                occurrence_count=4,
                last_seen_at=now,
                status="paused",
                confidence="high",
                source="candidate",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    paused = client.get("/api/recurring/items?status=paused", headers=identity.app_headers)
    assert paused.status_code == 200, paused.json()
    assert [entry["merchant"] for entry in paused.json()["items"]] == ["Netflix"]

    invalid_status = client.get("/api/recurring/items?status=unknown", headers=identity.app_headers)
    assert invalid_status.status_code == 422, invalid_status.json()
    assert invalid_status.json()["error"] == "recurring_status_invalid"

    not_found = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "Not Monthly",
            "amount_cents": 1234,
            "occurrence_count": 1,
        },
    )
    assert not_found.status_code == 404, not_found.json()
    assert not_found.json()["error"] == "recurring_candidate_not_found"
