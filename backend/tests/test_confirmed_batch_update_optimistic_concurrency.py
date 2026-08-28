"""ADR-0038 PR-2d contract tests for confirmed batch update."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, ExpenseRevision
from app.schemas import ConfirmedExpenseBatchUpdateRequest
from app.services.expense_correction_service import batch_update_confirmed_expenses


def _create_confirmed(client: TestClient, *, identity, merchant: str = "Batch Race") -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1200,
            "merchant": merchant,
            "category": "Initial",
            "expense_time": "2026-05-05T12:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def test_confirmed_batch_update_missing_token_map_returns_422(client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(client, identity=identity)
    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=identity.app_headers,
        json={"expense_ids": [expense_id], "category": "New"},
    )
    assert response.status_code == 422, response.text


def test_confirmed_batch_update_token_map_must_cover_every_requested_id(client: TestClient, *, identity) -> None:
    first_id = _create_confirmed(client, identity=identity, merchant="Batch Cover A")
    second_id = _create_confirmed(client, identity=identity, merchant="Batch Cover B")
    first = client.get(f"/api/expenses/{first_id}", headers=identity.app_headers).json()

    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=identity.app_headers,
        json={
            "expense_ids": [first_id, second_id],
            "expected_row_version_by_id": {first_id: first["row_version"]},
            "category": "New",
            "reason": "批量更正",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_request"


def test_confirmed_batch_update_requires_command_identity(client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(client, identity=identity)
    current = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()

    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=identity.app_headers,
        json={
            "expense_ids": [expense_id],
            "expected_row_version_by_id": {expense_id: current["row_version"]},
            "category": "New",
            "reason": "批量更正",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"] == "idempotency_key_required"


def test_confirmed_batch_update_replay_returns_committed_result_without_new_revision(
    client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _create_confirmed(client, identity=identity)
    current = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    payload = {
        "expense_ids": [expense_id],
        "expected_row_version_by_id": {expense_id: current["row_version"]},
        "category": "Replay Safe",
        "reason": "验证批量命令重放",
    }
    headers = {**identity.app_headers, "Idempotency-Key": "confirmed-batch-replay"}

    first = client.post("/api/expenses/confirmed/batch-update", headers=headers, json=payload)
    replay = client.post("/api/expenses/confirmed/batch-update", headers=headers, json=payload)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    with SessionLocal() as db:
        revision_count = len(
            list(
                db.scalars(
                    select(ExpenseRevision).where(ExpenseRevision.expense_id == expense_id)
                )
            )
        )
    assert revision_count == 2


@pytest.mark.real_db
def test_two_sessions_confirmed_batch_update_race_only_first_writer_wins(client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Expense).where(Expense.id == expense_id))
        row_b = session_b.scalar(select(Expense).where(Expense.id == expense_id))
        assert row_a is not None and row_b is not None
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        batch_update_confirmed_expenses(
            session_a,
            tenant_id=tenant_id,
            payload=ConfirmedExpenseBatchUpdateRequest(
                expense_ids=[expense_id],
                expected_row_version_by_id={expense_id: shared_version},
                category="Writer A",
                reason="写入方 A 更正",
            ),
            idempotency_key="batch-race-writer-a",
        )

        with pytest.raises(AppError) as exc_info:
            batch_update_confirmed_expenses(
                session_b,
                tenant_id=tenant_id,
                payload=ConfirmedExpenseBatchUpdateRequest(
                    expense_ids=[expense_id],
                    expected_row_version_by_id={expense_id: shared_version},
                    category="Writer B",
                    reason="写入方 B 更正",
                ),
                idempotency_key="batch-race-writer-b",
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["category"] == "Writer A"
