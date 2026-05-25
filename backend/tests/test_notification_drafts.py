"""v0.6 notification drafts: structured-only input and idempotent pending creation."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Expense, LedgerMember

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _payload(*, expense_time: str = "2026-05-13T10:05:00Z") -> dict:
    return {
        "source": "wechat",
        "merchant": "星巴克",
        "amount_cents": 2680,
        "category": "餐饮",
        "expense_time": expense_time,
    }


def _draft_count() -> int:
    with SessionLocal() as db:
        return int(
            db.scalar(
                select(func.count(Expense.id)).where(
                    Expense.draft_idempotency_key.is_not(None)
                )
            )
            or 0
        )


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_notification_draft_is_pending_structured_and_idempotent(
    client: TestClient, *, identity,
) -> None:
    first = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(),
    )
    second = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert _draft_count() == 1

    body = first.json()
    assert body["status"] == "pending"
    assert body["source"] == "通知草稿:微信"
    assert body["merchant"] == "星巴克"
    assert body["amount_cents"] == 2680
    assert body["raw_text"] is None
    assert body["image_path"] is None
    assert body["thumbnail_path"] is None
    assert body["confirmed_at"] is None

    with SessionLocal() as db:
        expense = db.get(Expense, body["id"])
        assert expense is not None
        assert expense.draft_idempotency_key
        assert expense.raw_text == ""
        assert set(json.loads(expense.ocr_draft_fields or "[]")) == {
            "amount_cents",
            "category",
            "expense_time",
            "merchant",
        }


def test_notification_draft_canonicalizes_currency_ocr_ownership(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={
            "source": "wechat",
            "merchant": "Alias Cafe",
            "original_currency": "USD",
            "original_amount": "12.34",
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        expense = db.get(Expense, response.json()["id"])
        assert expense is not None
        assert set(json.loads(expense.ocr_draft_fields or "[]")) == {
            "amount_cents",
            "merchant",
        }


def test_notification_draft_time_window_creates_new_pending_after_bucket(
    client: TestClient, *, identity,
) -> None:
    first = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(expense_time="2026-05-13T10:05:00Z"),
    )
    second = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(expense_time="2026-05-13T10:35:00Z"),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first.json()["id"]
    assert _draft_count() == 2


def test_notification_draft_idempotency_is_ledger_scoped(client: TestClient, *, identity) -> None:
    owner = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(),
    )
    tester = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.gray_app_headers,
        json=_payload(),
    )

    assert owner.status_code == 200, owner.text
    assert tester.status_code == 200, tester.text
    assert owner.json()["id"] != tester.json()["id"]
    assert _draft_count() == 2

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(Expense)
                .where(Expense.draft_idempotency_key.is_not(None))
                .order_by(Expense.tenant_id.asc())
            )
        )
    assert [row.tenant_id for row in rows] == ["owner", "tester_1"]
    assert rows[0].draft_idempotency_key == rows[1].draft_idempotency_key


def test_notification_draft_rejects_raw_text_and_unknown_source(
    client: TestClient, *, identity,
) -> None:
    raw_text = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={**_payload(), "raw_text": "原始通知正文不允许上传"},
    )
    assert raw_text.status_code == 422
    assert raw_text.json()["error"] == "invalid_request"

    unknown = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={**_payload(), "source": "mail"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "notification_source_invalid"


def test_notification_draft_viewer_is_read_only(client: TestClient, *, identity) -> None:
    _demote_owner_ledger_to_viewer()

    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json=_payload(),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE
