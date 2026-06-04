"""ADR-0038 PR-2e contract tests for ``POST /api/expenses/{id}/recognize-text``.

Previously the service self-claimed using the row's current ``updated_at``,
which silently overwrote concurrent edits between the client's read and
this call. The token is now required (422 if missing, 409 if stale) and
the claim is anchored to the client-supplied token, matching the rest of
the expense-mutate surface.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from api_contract_helpers import (
    patch_expense,
    recognize_text_api,
    reject_expense_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseRecognizeTextRequest
from app.services.expense_service import recognize_expense_text


def test_recognize_text_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": "中国建设银行\n交易金额：18.51"},
    )
    assert response.status_code == 422, response.text


def test_recognize_text_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.text

    # An intervening PATCH bumps updated_at so the snapshot becomes stale.
    intervening = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "用户手动改了"},
    )
    assert intervening.status_code == 200, intervening.text

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": snapshot.json()["row_version"],
            "raw_text": "中国建设银行\n交易金额：18.51",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"

    # Row stays at the intervening write, recognize did not overwrite.
    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.json()["merchant"] == "用户手动改了"


def test_recognize_text_against_confirmed_returns_404(
    client: TestClient, *, identity
) -> None:
    confirmed = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "Stable Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T02:00:00Z",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    expense_id = int(confirmed.json()["id"])

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="试图改 confirmed 行",
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"


def test_recognize_text_against_rejected_returns_404(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert rejected.status_code == 200

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="试图改 rejected 行",
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"


def test_two_sessions_recognize_text_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    tenant_id = "owner"

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.get(Expense, expense_id)
        row_b = session_b.get(Expense, expense_id)
        assert row_a is not None and row_b is not None
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        # Session A wins via a direct manual edit that bumps row_version.
        row_a.merchant = "Writer A"
        row_a.row_version = shared_version + 1
        session_a.commit()

        with pytest.raises(AppError) as exc_info:
            recognize_expense_text(
                session_b,
                expense_id,
                tenant_id,
                ExpenseRecognizeTextRequest(
                    expected_row_version=shared_version,
                    raw_text="OCR text from a stale read",
                ),
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    # Session A's value is persisted, session B did not overwrite it.
    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["merchant"] == "Writer A"


def test_recognize_text_preserves_pre_claim_ocr_draft_anchor(
    client: TestClient, *, identity
) -> None:
    """ADR-0038 PR-2e keeps the legacy OCR draft-field detection anchor.

    The service re-anchors ``expense.updated_at`` to the pre-claim snapshot
    (``anchor_updated_at``) after the row_version claim so
    ``apply_ocr_result_and_append_fact`` sees the pre-claim state when deciding
    which draft fields it owns. This test exercises the happy path and confirms
    the recognize-text route still extracts fields end-to-end with the new
    contract.
    """
    expense_id = upload_png(client, identity=identity)
    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="\n".join(
            [
                "中国建设银行",
                "交易提醒",
                "交易时间：2026年5月4日 16:23:25",
                "交易金额：18.51（人民币）",
            ]
        ),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["amount_cents"] == 1851
    assert payload["merchant"] == "中国建设银行"
    assert payload["status"] == "pending"
