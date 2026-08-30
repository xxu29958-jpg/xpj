"""Allocation invariant at the direct household split command consumer."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, OcrFact
from tests.api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    recognize_text_api,
    replace_splits_api,
    upload_png,
)
from tests.expense_split_test_support import (
    bearer,
    family_split_fixture,
    personal_owner_member_id,
    replace_splits,
)


def test_expense_splits_reject_overallocation_without_mutating_parent(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = family_split_fixture(client, identity=identity)
    headers = bearer(owner_token)
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()

    rejected = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": before["row_version"],
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 6000},
                {"member_id": member_member_id, "amount_cents": 5000},
            ],
        },
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["row_version"] == before["row_version"]
    splits = client.get(f"/api/expenses/{expense_id}/splits", headers=headers).json()
    assert splits["splits"] == []


def test_pending_amount_patch_rejects_existing_split_overallocation(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = family_split_fixture(client, identity=identity)
    headers = bearer(owner_token)
    replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=6000,
        member_amount_cents=3000,
    )
    before = client.get(f"/api/expenses/{expense_id}", headers=headers).json()

    rejected = patch_expense(
        client,
        expense_id,
        headers=headers,
        fields={"amount_cents": 8000},
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["amount_cents"] == before["amount_cents"]
    assert current["row_version"] == before["row_version"]


def test_recognize_text_preserves_coherent_money_when_ocr_suggestion_would_overallocate_splits(
    client: TestClient,
    *,
    identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    first = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="盒马\n交易金额：100.00\n交易时间：2026年5月4日 16:23:25",
    )
    assert first.status_code == 200, first.text
    assert first.json()["amount_cents"] == 10_000

    splits = replace_splits_api(
        client,
        expense_id,
        headers=identity.app_headers,
        splits=[
            {
                "member_id": personal_owner_member_id(),
                "amount_cents": 9_000,
            }
        ],
    )
    assert splits.status_code == 200, splits.text
    before_retry = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()

    second = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="盒马鲜生\n交易金额：80.00\n交易时间：2026年5月4日 16:23:25",
    )

    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["amount_cents"] == 10_000
    assert second_payload["row_version"] == before_retry["row_version"] + 1
    money_snapshot_fields = (
        "amount_cents",
        "home_currency",
        "original_currency_code",
        "original_amount_minor",
        "exchange_rate_to_cny",
        "exchange_rate_date",
        "exchange_rate_source",
        "fx_status",
    )
    assert tuple(second_payload[field] for field in money_snapshot_fields) == tuple(
        before_retry[field] for field in money_snapshot_fields
    )
    listed_splits = client.get(
        f"/api/expenses/{expense_id}/splits",
        headers=identity.app_headers,
    )
    assert listed_splits.status_code == 200, listed_splits.text
    assert listed_splits.json()["splits_total_amount_cents"] == 9_000
    with SessionLocal() as db:
        latest_fact = db.scalar(
            select(OcrFact)
            .where(OcrFact.expense_id == expense_id)
            .order_by(OcrFact.id.desc())
            .limit(1)
        )
        assert latest_fact is not None
        assert latest_fact.parsed_amount_cents == 8_000

    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.text


def test_confirmation_rejects_preexisting_pending_split_overallocation(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = family_split_fixture(client, identity=identity)
    headers = bearer(owner_token)
    replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=6000,
        member_amount_cents=4000,
    )
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert expense is not None
        expense.amount_cents = 9000
        db.commit()

    rejected = confirm_expense_api(client, expense_id, headers=headers)

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"] == "expense_split_total_exceeds_parent"
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["status"] == "pending"
