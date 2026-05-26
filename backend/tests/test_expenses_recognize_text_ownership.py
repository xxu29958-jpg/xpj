from __future__ import annotations

from datetime import timedelta

from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense


def test_recognize_text_then_confirm_enters_stats_and_export(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-17.89",
            "交易成功",
            "订单金额",
            "18.00",
            "碰一下立减",
            "-0.11",
            "支付时间",
            "2026-05-0521:38:13",
        ]
    )

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["amount_cents"] == 1789
    assert payload["merchant"] == "好想来零食乐园"
    assert payload["category"] == "餐饮"

    pending_stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert pending_stats.status_code == 200, pending_stats.json()
    assert pending_stats.json()["total_amount_cents"] == 0

    pending_export = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=identity.app_headers,
    )
    assert pending_export.status_code == 200, pending_export.text
    assert "好想来零食乐园" not in pending_export.text

    confirmed = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["status"] == "confirmed"

    confirmed_stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert confirmed_stats.status_code == 200, confirmed_stats.json()
    assert confirmed_stats.json()["total_amount_cents"] == 1789

    confirmed_export = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=identity.app_headers,
    )
    assert confirmed_export.status_code == 200, confirmed_export.text
    assert "好想来零食乐园" in confirmed_export.text
    assert "1789" in confirmed_export.text


def test_recognize_text_does_not_overwrite_user_filled_fields(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 9900,
            "merchant": "用户填写商家",
            "category": "生活",
            "expense_time": "2026-05-04T00:00:00Z",
        },
    )
    assert response.status_code == 200

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
    assert payload["amount_cents"] == 9900
    assert payload["merchant"] == "用户填写商家"
    assert payload["category"] == "生活"
    assert payload["expense_time"] == "2026-05-04T00:00:00Z"


def test_recognize_text_can_correct_ocr_draft_but_not_user_edits(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)

    first_raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-72.00",
            "交易成功",
            "支付时间",
            "2026-05-05 21:38:13",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": first_raw_text},
    )
    assert response.status_code == 200
    assert response.json()["amount_cents"] == 7200
    assert response.json()["merchant"] == "好想来零食乐园"

    corrected_raw_text = "\n".join(
        [
            "账单详情",
            "巴南区卢记牛肉面",
            "-19.00",
            "交易成功",
            "支付时间",
            "2026-05-07 08:30:00",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": corrected_raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["confirmed_at"] is None
    assert payload["amount_cents"] == 1900
    assert payload["merchant"] == "巴南区卢记牛肉面"

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "用户手动确认商家"},
    )
    assert response.status_code == 200

    newer_raw_text = "\n".join(
        [
            "账单详情",
            "淘宝闪购",
            "-25.68",
            "交易成功",
            "支付时间",
            "2026-05-07 15:17:09",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": newer_raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 2568
    assert payload["merchant"] == "用户手动确认商家"
    assert payload["status"] == "pending"


def test_legacy_recent_ocr_draft_can_be_corrected(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    first_raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-72.00",
            "交易成功",
            "支付时间",
            "2026-05-05 21:38:13",
        ]
    )
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.raw_text = first_raw_text
        expense.confidence = 0.9
        expense.amount_cents = 7200
        expense.merchant = "好想来零食乐园"
        expense.category = "餐饮"
        expense.updated_at = expense.created_at + timedelta(seconds=3)
        expense.ocr_draft_fields = None
        db.commit()

    corrected_raw_text = "\n".join(
        [
            "账单详情",
            "巴南区卢记牛肉面",
            "-19.00",
            "交易成功",
            "支付时间",
            "2026-05-07 08:30:00",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": corrected_raw_text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1900
    assert payload["merchant"] == "巴南区卢记牛肉面"
    assert payload["status"] == "pending"
    assert payload["confirmed_at"] is None


def test_legacy_stale_or_manual_pending_fields_are_not_overwritten(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    first_raw_text = "\n".join(
        [
            "账单详情",
            "好想来零食乐园",
            "-72.00",
            "交易成功",
            "支付时间",
            "2026-05-05 21:38:13",
        ]
    )
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.raw_text = first_raw_text
        expense.confidence = 0.9
        expense.amount_cents = 7200
        expense.merchant = "用户手动确认商家"
        expense.category = "餐饮"
        expense.updated_at = expense.created_at + timedelta(minutes=30)
        expense.ocr_draft_fields = None
        db.commit()

    corrected_raw_text = "\n".join(
        [
            "账单详情",
            "巴南区卢记牛肉面",
            "-19.00",
            "交易成功",
            "支付时间",
            "2026-05-07 08:30:00",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": corrected_raw_text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 7200
    assert payload["merchant"] == "用户手动确认商家"
    assert payload["status"] == "pending"
