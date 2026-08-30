"""v0.6 recurring item API contract and permission guards."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import LedgerMember, RecurringItem
from app.schemas import RecurringCandidateConfirmRequest
from app.services.recurring_candidate_confirmation_service import (
    confirm_recurring_candidate as confirm_recurring_candidate_service,
)
from app.services.recurring_service import _historical_average_amount

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def test_recurring_history_average_accepts_wide_exact_numerator() -> None:
    item = RecurringItem(
        merchant_key="large-subscription",
        merchant_name="Large subscription",
        frequency="monthly",
        baseline_amount_cents=1,
        last_amount_cents=1,
    )

    assert _historical_average_amount(item, [2**53 - 1] * 1001) == 2**53 - 1


def test_recurring_candidate_confirmation_service_creates_item_directly() -> None:
    last_seen = _seed_monthly_candidate()
    payload = RecurringCandidateConfirmRequest(
        merchant="ChatGPT Plus",
        amount_cents=20000,
        occurrence_count=3,
        last_seen_at=last_seen,
        confidence="high",
        frequency="monthly",
    )

    with SessionLocal() as db:
        item = confirm_recurring_candidate_service(
            db,
            tenant_id="owner",
            payload=payload,
            timezone_name="UTC",
        )
        assert item.tenant_id == "owner"
        assert item.merchant_key == "chatgpt plus"
        assert item.baseline_amount_cents == 20000
        assert item.occurrence_count == 3
        assert item.next_expected_date.isoformat() == "2026-06-05"


def test_candidate_confirmation_rejects_display_or_normalized_merchant_overflow_with_domain_error(
    client: TestClient,
    *,
    identity,
) -> None:
    expanding_merchant = "ß" * 255
    last_seen = _seed_monthly_candidate(merchant=expanding_merchant)
    candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC",
        headers=identity.app_headers,
    )
    assert candidates.status_code == 200, candidates.json()
    assert [item["merchant"] for item in candidates.json()["items"]] == [expanding_merchant]

    rejected = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": expanding_merchant,
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert rejected.status_code == 422, rejected.json()
    assert rejected.json()["error"] == "recurring_merchant_too_long"

    display_overflow = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "x" * 256,
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )
    assert display_overflow.status_code == 422, display_overflow.json()
    assert display_overflow.json()["error"] == "recurring_merchant_too_long"

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
        ) == 0


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
    *,
    identity,
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


def test_recurring_candidate_confirm_uses_server_observation_not_client_provenance(
    client: TestClient,
    *,
    identity,
) -> None:
    last_seen = _seed_monthly_candidate()

    response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "ChatGPT Plus",
            "amount_cents": 20_000,
            "occurrence_count": 999,
            "last_seen_at": "2035-12-31T23:59:59Z",
            "confidence": "low",
            "frequency": "monthly",
        },
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["occurrence_count"] == 3
    assert body["last_seen_at"] == last_seen.isoformat().replace("+00:00", "Z")
    assert body["confidence"] == "high"


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

    for action in ("pause", "resume"):
        blocked = client.post(
            f"/api/recurring/items/{public_id}/{action}",
            headers=identity.app_headers,
            json={"expected_row_version": visible.json()["items"][0]["row_version"]},
        )
        assert blocked.status_code == 409, blocked.json()
        assert blocked.json()["error"] == "recurring_item_archived"
        assert blocked.json()["public_id"] == public_id
        assert blocked.json()["status"] == "archived"


def test_confirm_candidate_never_resurrects_archived_item(client: TestClient, *, identity) -> None:
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

    assert response.status_code == 409, response.json()
    payload = response.json()
    assert payload["error"] == "recurring_item_archived"
    assert payload["public_id"] == public_id
    assert payload["status"] == "archived"

    listed = client.get("/api/recurring/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert listed.json()["items"] == []

    candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC",
        headers=identity.app_headers,
    )
    assert candidates.status_code == 200, candidates.json()
    assert candidates.json()["items"] == []

    with SessionLocal() as db:
        current = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id).limit(1))
        assert current is not None
        assert current.status == "archived"
        assert current.source == "candidate"
        assert current.archived_at is not None


def test_confirm_candidate_never_overwrites_manual_commitment(client: TestClient, *, identity) -> None:
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    manual = client.post(
        "/api/recurring/items",
        headers=headers,
        json={
            "merchant": "ChatGPT Plus",
            "baseline_amount_cents": 18_000,
            "next_expected_date": "2026-06-06",
        },
    )
    assert manual.status_code == 201, manual.json()

    last_seen = _seed_monthly_candidate(merchant="ChatGPT Plus", amount_cents=20_000)
    confirmation = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "ChatGPT Plus",
            "amount_cents": 20_000,
            "occurrence_count": 3,
            "last_seen_at": last_seen.isoformat().replace("+00:00", "Z"),
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert confirmation.status_code == 409, confirmation.json()
    assert confirmation.json()["error"] == "recurring_item_conflict"
    assert confirmation.json()["public_id"] == manual.json()["public_id"]
    assert confirmation.json()["status"] == "active"

    with SessionLocal() as db:
        current = db.scalar(select(RecurringItem).where(RecurringItem.public_id == manual.json()["public_id"]).limit(1))
        assert current is not None
        assert current.source == "manual"
        assert current.baseline_amount_cents == 18_000
        assert current.occurrence_count == 0
        assert current.last_seen_at is None


def test_candidate_recurring_rejects_cross_key_rename_without_reopening_claimed_candidate(
    client: TestClient,
    *,
    identity,
) -> None:
    item = _confirm_candidate(client, identity=identity)

    renamed = client.patch(
        f"/api/recurring/items/{item['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "merchant": "AI Family Plan",
            "expected_row_version": item["row_version"],
        },
    )

    assert renamed.status_code == 409, renamed.json()
    assert renamed.json()["error"] == "recurring_observed_merchant_immutable"
    current = client.get(
        f"/api/recurring/items/{item['public_id']}",
        headers=identity.app_headers,
    )
    assert current.status_code == 200, current.json()
    assert current.json()["merchant"] == "ChatGPT Plus"
    assert current.json()["merchant_key"] == "chatgpt plus"

    candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC",
        headers=identity.app_headers,
    )
    assert candidates.status_code == 200, candidates.json()
    assert candidates.json()["items"] == []


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
        ("restore", f"/api/recurring/items/{public_id}/restore"),
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
