"""ADR-0038 PR-2c contract tests for items/splits replacement endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, LedgerMember
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
)
from app.services.expense_split_service import replace_expense_splits
from app.services.receipt_item_service import replace_expense_items


def _create_manual_expense(client: TestClient, *, identity, amount_cents: int = 1500) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": "Concurrency Cafe",
            "category": "Dining",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _snapshot(client: TestClient, expense_id: int, *, identity) -> dict:
    response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def _owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return int(member.id)


def test_replace_items_without_expected_updated_at_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    response = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
        json={"items": [{"name": "Latte", "amount_cents": 500}]},
    )
    assert response.status_code == 422, response.text


def test_replace_items_with_stale_updated_at_returns_409_and_keeps_rows(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    stale = _snapshot(client, expense_id, identity=identity)["updated_at"]

    first = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
        json={
            "expected_updated_at": stale,
            "items": [{"name": "First", "amount_cents": 500}],
        },
    )
    assert first.status_code == 200, first.text

    replay = client.put(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
        json={
            "expected_updated_at": stale,
            "items": [{"name": "Second", "amount_cents": 600}],
        },
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"] == "state_conflict"

    listed = client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert listed.status_code == 200, listed.text
    assert [item["name"] for item in listed.json()["items"]] == ["First"]


def test_two_sessions_replace_items_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        replace_expense_items(
            session_a,
            expense_id,
            tenant_id,
            ExpenseItemReplaceRequest(
                expected_updated_at=shared_version,
                items=[ExpenseItemRequest(name="Writer A", amount_cents=500)],
            ),
        )

        with pytest.raises(AppError) as exc_info:
            replace_expense_items(
                session_b,
                expense_id,
                tenant_id,
                ExpenseItemReplaceRequest(
                    expected_updated_at=shared_version,
                    items=[ExpenseItemRequest(name="Writer B", amount_cents=600)],
                ),
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()


def test_replace_splits_without_expected_updated_at_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    member_id = _owner_member_id()
    response = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=identity.app_headers,
        json={"splits": [{"member_id": member_id, "amount_cents": 1500}]},
    )
    assert response.status_code == 422, response.text


def test_replace_splits_with_stale_updated_at_returns_409_and_keeps_rows(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    member_id = _owner_member_id()
    stale = _snapshot(client, expense_id, identity=identity)["updated_at"]

    first = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=identity.app_headers,
        json={
            "expected_updated_at": stale,
            "splits": [{"member_id": member_id, "amount_cents": 1500, "note": "First"}],
        },
    )
    assert first.status_code == 200, first.text

    replay = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=identity.app_headers,
        json={
            "expected_updated_at": stale,
            "splits": [{"member_id": member_id, "amount_cents": 1000, "note": "Second"}],
        },
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"] == "state_conflict"

    listed = client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    assert listed.status_code == 200, listed.text
    assert [item["note"] for item in listed.json()["splits"]] == ["First"]


def test_two_sessions_replace_splits_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = _create_manual_expense(client, identity=identity)
    member_id = _owner_member_id()
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        replace_expense_splits(
            session_a,
            expense_id,
            tenant_id,
            ExpenseSplitReplaceRequest(
                expected_updated_at=shared_version,
                splits=[
                    ExpenseSplitRequest(member_id=member_id, amount_cents=1500, note="Writer A")
                ],
            ),
            actor_account_id=None,
        )

        with pytest.raises(AppError) as exc_info:
            replace_expense_splits(
                session_b,
                expense_id,
                tenant_id,
                ExpenseSplitReplaceRequest(
                    expected_updated_at=shared_version,
                    splits=[
                        ExpenseSplitRequest(
                            member_id=member_id,
                            amount_cents=1000,
                            note="Writer B",
                        )
                    ],
                ),
                actor_account_id=None,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()
