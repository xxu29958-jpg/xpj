from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from api_contract_helpers import (
    patch_expense,
    reject_expense_api,
    retry_ocr_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, OcrFact
from app.services.expense_service import retry_expense_ocr
from app.services.ocr_service import OcrResult


def test_ocr_retry_and_recognize_text_only_update_pending_draft(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    monkeypatch.setattr(
        "app.services.expense_service._ocr._active_provider_name",
        lambda: "mock",
    )
    monkeypatch.setattr(
        "app.services.expense_service._ocr.extract_ocr_result",
        lambda expense: OcrResult(
            raw_text="中国建设银行\n交易金额：18.51\n交易时间：2026年5月4日 16:23:25",
            confidence=0.9,
            amount_cents=1851,
            merchant="中国建设银行",
        ),
    )

    retry = retry_ocr_api(client, expense_id, headers=identity.app_headers)
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending"
    assert retry.json()["confirmed_at"] is None

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={
            "raw_text": "中国建设银行\n交易金额：18.51\n交易时间：2026年5月4日 16:23:25"
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["confirmed_at"] is None
    assert payload["amount_cents"] == 1851

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.app_headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 0


def test_retry_ocr_returns_503_when_ocr_provider_is_empty(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)

    response = retry_ocr_api(client, expense_id, headers=identity.app_headers)

    assert response.status_code == 503
    assert response.json()["error"] == "ocr_not_configured"
    with SessionLocal() as db:
        assert (
            db.query(OcrFact)
            .filter(OcrFact.tenant_id == "owner")
            .filter(OcrFact.expense_id == expense_id)
            .count()
            == 0
        )


def test_ocr_routes_do_not_modify_confirmed_expense(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "Stable Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T02:00:00Z",
        },
    )
    assert created.status_code == 200, created.json()
    expense_id = created.json()["id"]

    retry = retry_ocr_api(client, expense_id, headers=identity.app_headers)
    assert retry.status_code == 404
    recognized = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": "Changed Cafe\n99.99"},
    )
    assert recognized.status_code == 404

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 1234
    assert payload["merchant"] == "Stable Cafe"
    assert payload["raw_text"] is None


def test_ocr_routes_do_not_modify_rejected_expense(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert rejected.status_code == 200

    retry = retry_ocr_api(client, expense_id, headers=identity.app_headers)
    assert retry.status_code == 404
    recognized = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": "Changed Cafe\n99.99"},
    )
    assert recognized.status_code == 404

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "rejected"
    assert payload["raw_text"] is None


def test_spent_at_alias_clears_ocr_time_ownership(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.expense_time = datetime(2026, 5, 4, 2, 0, tzinfo=UTC)
        expense.ocr_draft_fields = '["expense_time"]'
        db.commit()

    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"spent_at": "2026-05-04T05:00:00Z"},
    )
    assert patched.status_code == 200, patched.json()

    second = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": "中国建设银行\n交易金额：18.51\n交易时间：2026年5月6日 23:00:00"},
    )
    assert second.status_code == 200, second.json()
    assert second.json()["expense_time"] == "2026-05-04T05:00:00Z"


def test_retry_ocr_without_expected_updated_at_returns_422(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    response = client.post(
        f"/api/expenses/{expense_id}/ocr/retry",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 422, response.text


def test_retry_ocr_with_stale_updated_at_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert snapshot.status_code == 200, snapshot.text
    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "Manual Edit"},
    )
    assert patched.status_code == 200, patched.text
    monkeypatch.setattr(
        "app.services.expense_service._ocr._active_provider_name",
        lambda: "mock",
    )
    monkeypatch.setattr(
        "app.services.expense_service._ocr.extract_ocr_result",
        lambda expense: OcrResult(
            raw_text="OCR\n12.00", amount_cents=1200, confidence=None
        ),
    )

    stale = client.post(
        f"/api/expenses/{expense_id}/ocr/retry",
        headers=identity.app_headers,
        json={"expected_updated_at": snapshot.json()["updated_at"]},
    )

    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_retry_ocr_unknown_expense_returns_404(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/expenses/9999999/ocr/retry",
        headers=identity.app_headers,
        json={"expected_updated_at": "2026-05-04T00:00:00Z"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "expense_not_found"


def test_retry_ocr_rejects_stale_pending_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expected_updated_at = expense.updated_at

    def slow_ocr_result(expense: Expense) -> OcrResult:
        with SessionLocal() as user_db:
            row = user_db.get(Expense, expense.id)
            assert row is not None
            row.merchant = "鐢ㄦ埛鎵嬪姩淇敼"
            row.amount_cents = 1234
            row.updated_at = (row.updated_at or row.created_at) + timedelta(seconds=5)
            user_db.commit()
        return OcrResult(
            raw_text="OCR 鍟嗗\n99.99",
            amount_cents=9999,
            merchant="OCR 鍟嗗",
            confidence=0.9,
        )

    monkeypatch.setattr("app.services.expense_service._ocr.extract_ocr_result", slow_ocr_result)
    monkeypatch.setattr(
        "app.services.expense_service._ocr._active_provider_name",
        lambda: "mock",
    )

    with SessionLocal() as db, pytest.raises(AppError) as exc_info:
        retry_expense_ocr(
            db,
            expense_id,
            "owner",
            expected_updated_at=expected_updated_at,
        )

    assert exc_info.value.error == "state_conflict"
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.merchant == "鐢ㄦ埛鎵嬪姩淇敼"
        assert row.amount_cents == 1234


def test_two_sessions_retry_ocr_race_returns_state_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    monkeypatch.setattr(
        "app.services.expense_service._ocr._active_provider_name",
        lambda: "mock",
    )
    monkeypatch.setattr(
        "app.services.expense_service._ocr.extract_ocr_result",
        lambda expense: OcrResult(
            raw_text="OCR\n88.00", amount_cents=8800, confidence=None
        ),
    )

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.get(Expense, expense_id)
        row_b = session_b.get(Expense, expense_id)
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        row_a.merchant = "Writer A"
        row_a.updated_at = shared_version + timedelta(seconds=5)
        session_a.commit()

        with pytest.raises(AppError) as exc_info:
            retry_expense_ocr(
                session_b,
                expense_id,
                "owner",
                expected_updated_at=shared_version,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()
