from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from api_contract_helpers import (
    upload_png,
)
from app.database import SessionLocal
from app.errors import AppError
from app.models import DuplicateIgnore, Expense
from app.services.duplicate_service import _remember_duplicate_ignore
from app.services.expense_service import confirm_expense, reject_expense, retry_expense_ocr
from app.services.ocr_service import MockOcrProvider, OcrResult, apply_ocr_result, retry_ocr
from conftest import (
    BACKEND_ROOT,
    PNG_BYTES,
    app_headers,
    gray_app_headers,
)


def test_upload_pending_image_and_confirm_flow(client: TestClient) -> None:
    expense_id = upload_png(client)

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200
    assert detail.json()["id"] == expense_id

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["amount_cents"] is None
    UUID(item["public_id"])
    assert item["category"] == "其他"
    assert item["image_path"].startswith("uploads/")
    assert "\\" not in item["image_path"]
    assert item["image_hash"]

    image_without_token = client.get(f"/api/expenses/{expense_id}/image")
    assert image_without_token.status_code == 401
    assert image_without_token.json()["error"] == "invalid_token"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=app_headers())
    assert image.status_code == 200
    assert image.content == PNG_BYTES

    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=app_headers()
    )
    assert thumbnail.status_code == 200
    assert thumbnail.content.startswith(b"\xff\xd8")

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=app_headers())
    assert response.status_code == 400
    assert response.json()["error"] == "amount_required"

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 3680,
            "merchant": "美团外卖",
            "category": "餐饮",
            "note": "午饭",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["amount_cents"] == 3680

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=app_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    confirmed = client.get(
        "/api/expenses/confirmed?page=1&page_size=50&month=2026-05&category=餐饮",
        headers=app_headers(),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1

    categories = client.get("/api/expenses/categories", headers=app_headers())
    assert categories.status_code == 200
    assert "餐饮" in categories.json()["items"]
    assert "吃饭" not in categories.json()["items"]

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert "2026-05" in months.json()["items"]

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮", headers=app_headers()
    )
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "美团外卖" in exported.text
    assert "public_id" in exported.text.splitlines()[0]
    assert "3680" in exported.text

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 3680


@pytest.mark.parametrize(
    "path",
    [
        "/api/stats/monthly?month=2026-13",
        "/api/stats/monthly?month=0000-05",
        "/api/stats/lifestyle?month=2026-5",
        "/api/expenses/confirmed?month=2026-13",
        "/api/expenses/export.csv?month=0000-05",
    ],
)
def test_month_filters_reject_invalid_month_labels(client: TestClient, path: str) -> None:
    response = client.get(path, headers=app_headers())
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_confirm_removes_expense_from_pending_and_adds_confirmed(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 1851,
            "merchant": "中国建设银行",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=app_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    assert all(item["id"] != expense_id for item in pending.json())

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=app_headers()
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1
    assert confirmed.json()["items"][0]["id"] == expense_id

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 1851


def test_confirm_delete_after_confirm_hides_image_and_thumbnail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, delete_image_after_confirm=True),
    )

    expense_id = upload_png(client)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_path is not None
        assert expense.thumbnail_path is not None
        image_path = BACKEND_ROOT / expense.image_path
        thumbnail_path = BACKEND_ROOT / expense.thumbnail_path
    assert image_path.is_file()
    assert thumbnail_path.is_file()

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 1851,
            "merchant": "A",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=app_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["image_deleted_at"] is not None
    assert payload["thumbnail_deleted_at"] is not None
    assert not image_path.exists()
    assert not thumbnail_path.exists()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=app_headers())
    assert image.status_code == 404
    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail",
        headers=app_headers(),
    )
    assert thumbnail.status_code == 404

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_deleted_at is not None
        assert expense.thumbnail_deleted_at is not None


def test_reject_removes_expense_from_pending_without_confirming(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)

    response = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["confirmed_at"] is None

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    assert all(item["id"] != expense_id for item in pending.json())

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=app_headers()
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 0


def test_stale_reject_cannot_overwrite_confirmed_expense(client: TestClient) -> None:
    expense_id = upload_png(client)
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={"amount_cents": 3680, "merchant": "A", "category": "餐饮"},
    )
    assert response.status_code == 200

    confirm_db = SessionLocal()
    reject_db = SessionLocal()
    try:
        assert confirm_db.get(Expense, expense_id) is not None
        assert reject_db.get(Expense, expense_id) is not None
        confirmed = confirm_expense(confirm_db, expense_id, "owner")
        assert confirmed.status == "confirmed"

        with pytest.raises(AppError) as error:
            reject_expense(reject_db, expense_id, "owner")
        assert error.value.error == "expense_not_found"
        assert error.value.status_code == 404
    finally:
        confirm_db.close()
        reject_db.close()

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.status == "confirmed"
        assert expense.confirmed_at is not None
        assert expense.rejected_at is None


def test_ocr_retry_and_recognize_text_only_update_pending_draft(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)

    retry = client.post(f"/api/expenses/{expense_id}/ocr/retry", headers=app_headers())
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending"
    assert retry.json()["confirmed_at"] is None

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
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
        "/api/expenses/confirmed?month=2026-05", headers=app_headers()
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 0


def test_ocr_routes_do_not_modify_confirmed_expense(client: TestClient) -> None:
    created = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 1234,
            "merchant": "Stable Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T02:00:00Z",
        },
    )
    assert created.status_code == 200, created.json()
    expense_id = created.json()["id"]

    retry = client.post(f"/api/expenses/{expense_id}/ocr/retry", headers=app_headers())
    assert retry.status_code == 404
    recognized = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": "Changed Cafe\n99.99"},
    )
    assert recognized.status_code == 404

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 1234
    assert payload["merchant"] == "Stable Cafe"
    assert payload["raw_text"] == ""


def test_ocr_routes_do_not_modify_rejected_expense(client: TestClient) -> None:
    expense_id = upload_png(client)
    rejected = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
    assert rejected.status_code == 200

    retry = client.post(f"/api/expenses/{expense_id}/ocr/retry", headers=app_headers())
    assert retry.status_code == 404
    recognized = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": "Changed Cafe\n99.99"},
    )
    assert recognized.status_code == 404

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "rejected"
    assert payload["raw_text"] == ""


def test_reject_is_idempotent_for_already_rejected_expense(client: TestClient) -> None:
    expense_id = upload_png(client)
    first = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
    assert first.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        rejected_at = expense.rejected_at
        updated_at = expense.updated_at

    second = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
    assert second.status_code == 200
    assert second.json()["status"] == "rejected"

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.rejected_at == rejected_at
        assert expense.updated_at == updated_at


def test_apply_ocr_result_is_noop_for_terminal_expenses() -> None:
    expense = Expense(
        status="confirmed",
        amount_cents=1234,
        merchant="Stable Cafe",
        category="餐饮",
        raw_text="",
    )

    apply_ocr_result(
        expense,
        OcrResult(raw_text="Changed Cafe\n99.99", amount_cents=9999, merchant="Changed Cafe", confidence=None),
    )

    assert expense.amount_cents == 1234
    assert expense.merchant == "Stable Cafe"
    assert expense.raw_text == ""


def test_recognize_text_then_confirm_enters_stats_and_export(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
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
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["amount_cents"] == 1789
    assert payload["merchant"] == "好想来零食乐园"
    assert payload["category"] == "餐饮"

    pending_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert pending_stats.status_code == 200, pending_stats.json()
    assert pending_stats.json()["total_amount_cents"] == 0

    pending_export = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=app_headers(),
    )
    assert pending_export.status_code == 200, pending_export.text
    assert "好想来零食乐园" not in pending_export.text

    confirmed = client.post(f"/api/expenses/{expense_id}/confirm", headers=app_headers())
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["status"] == "confirmed"

    confirmed_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert confirmed_stats.status_code == 200, confirmed_stats.json()
    assert confirmed_stats.json()["total_amount_cents"] == 1789

    confirmed_export = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=app_headers(),
    )
    assert confirmed_export.status_code == 200, confirmed_export.text
    assert "好想来零食乐园" in confirmed_export.text
    assert "1789" in confirmed_export.text


def test_recognize_text_does_not_overwrite_user_filled_fields(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 9900,
            "merchant": "用户填写商家",
            "category": "生活",
            "expense_time": "2026-05-04T00:00:00Z",
        },
    )
    assert response.status_code == 200

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
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
    client: TestClient,
) -> None:
    expense_id = upload_png(client)

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
        headers=app_headers(),
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
        headers=app_headers(),
        json={"raw_text": corrected_raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["confirmed_at"] is None
    assert payload["amount_cents"] == 1900
    assert payload["merchant"] == "巴南区卢记牛肉面"

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={"merchant": "用户手动确认商家"},
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
        headers=app_headers(),
        json={"raw_text": newer_raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 2568
    assert payload["merchant"] == "用户手动确认商家"
    assert payload["status"] == "pending"


def test_legacy_recent_ocr_draft_can_be_corrected(client: TestClient) -> None:
    expense_id = upload_png(client)
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
        headers=app_headers(),
        json={"raw_text": corrected_raw_text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1900
    assert payload["merchant"] == "巴南区卢记牛肉面"
    assert payload["status"] == "pending"
    assert payload["confirmed_at"] is None


def test_legacy_stale_or_manual_pending_fields_are_not_overwritten(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
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
        headers=app_headers(),
        json={"raw_text": corrected_raw_text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 7200
    assert payload["merchant"] == "用户手动确认商家"
    assert payload["status"] == "pending"


def test_duplicate_detection_never_rejects_or_confirms(client: TestClient) -> None:
    first_id = upload_png(client)
    second_id = upload_png(client)

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    matched = next(item for item in pending.json() if item["id"] == second_id)
    assert matched["duplicate_status"] == "suspected"
    assert matched["duplicate_of_id"] == first_id
    assert matched["status"] == "pending"
    assert matched["confirmed_at"] is None
    assert matched["rejected_at"] is None


def test_mark_not_duplicate_suppresses_all_current_pair_detection_types(
    client: TestClient,
) -> None:
    first_id = upload_png(client)
    second_id = upload_png(client)

    response = client.post(
        f"/api/expenses/{second_id}/mark-not-duplicate", headers=app_headers()
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = client.patch(
            f"/api/expenses/{expense_id}",
            headers=app_headers(),
            json={
                "amount_cents": 5200,
                "merchant": "同一家店",
                "category": "生活",
                "expense_time": timestamp,
            },
        )
        assert response.status_code == 200

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    matched = next(item for item in pending.json() if item["id"] == second_id)
    assert matched["status"] == "pending"
    assert matched["duplicate_status"] == "none"
    assert matched["duplicate_of_id"] is None


def test_duplicate_ignore_insert_is_idempotent_for_retries(client: TestClient) -> None:
    first_id = upload_png(client)
    second_id = upload_png(client)

    with SessionLocal() as db:
        _remember_duplicate_ignore(db, "owner", second_id, first_id, "similar")
        _remember_duplicate_ignore(db, "owner", second_id, first_id, "similar")
        db.commit()

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(DuplicateIgnore)
            .where(DuplicateIgnore.tenant_id == "owner")
            .where(DuplicateIgnore.kind == "similar")
        )
    assert count == 1


def test_deleted_image_does_not_break_confirmed_ledger_data(client: TestClient) -> None:
    expense_id = upload_png(client)
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 3680,
            "merchant": "图片已清理商家",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200
    assert (
        client.post(
            f"/api/expenses/{expense_id}/confirm", headers=app_headers()
        ).status_code
        == 200
    )

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200
    for path_key in ["image_path", "thumbnail_path"]:
        relative_path = detail.json().get(path_key)
        if relative_path:
            (BACKEND_ROOT / relative_path).unlink(missing_ok=True)

    detail_after_delete = client.get(
        f"/api/expenses/{expense_id}", headers=app_headers()
    )
    assert detail_after_delete.status_code == 200
    payload = detail_after_delete.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 3680
    assert payload["merchant"] == "图片已清理商家"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=app_headers())
    assert image.status_code == 404
    assert image.json()["error"] == "image_not_found"


def test_recognize_text_extracts_receipt_fields(client: TestClient) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "中国建设银行",
            "交易提醒",
            "交易时间：2026年5月4日 16:23:25",
            "交易类型：支出（尾号 0436 账户）",
            "交易金额：18.51（人民币）",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_text"] == raw_text
    assert payload["amount_cents"] == 1851
    assert payload["merchant"] == "中国建设银行"
    assert payload["category"] == "其他"
    assert payload["expense_time"] == "2026-05-04T08:23:25Z"
    assert payload["confidence"] >= 0.8


def test_recognize_text_prefers_transaction_time_over_other_times(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "商品详情：超级咸蛋黄狮子头+泡椒脆笋鸭丝单人套餐",
            "中国建设银行",
            "交易提醒",
            "交易时间：",
            "2026年5月4日16:23:25",
            "交易金额：",
            "18.51(人民币)",
            "京东快递",
            "来电时间：",
            "2026-05-04 06:49:50",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1851
    assert payload["merchant"] == "中国建设银行"
    assert payload["expense_time"] == "2026-05-04T08:23:25Z"


def test_recognize_text_prefers_alipay_primary_amount_and_title_merchant(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
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
            "付款方式",
            "花呗",
            "商品说明",
            "重庆巴南区珠江城店",
            "收单机构",
            "招商银行股份有限公司",
            "清算机构",
            "中国银联股份有限公司",
            "收款方全称",
            "巴南区财进宁食品经营部（个体工商户）",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1789
    assert payload["merchant"] == "好想来零食乐园"
    assert payload["category"] == "餐饮"
    assert payload["expense_time"] == "2026-05-05T13:38:13Z"


def test_recognize_text_ignores_alipay_success_page_ads_for_merchant(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "支付成功",
            "￥7.50",
            "获得森林能量",
            "20g",
            "罗森便利店",
            "￥ 7.50",
            "交易方式",
            "花呗",
            "抢到下笔立减0.18元红包",
            "去查看",
            "立即领取",
            "高德",
            "写真实评价，领10元打车红包",
            "评价本店>",
            "扫街榜",
            "券后￥0.01",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 750
    assert payload["merchant"] == "罗森便利店"
    assert payload["category"] == "餐饮"


def test_recognize_text_alipay_success_body_ignores_navigation_title(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "07:55",
            "l 4G 13",
            "支",
            "回首页",
            "支付成功",
            "￥ 21.82",
            "获得森林能量",
            "20g",
            "乐尔乐特价批发超市",
            "￥ 22.00",
            "碰一下立减",
            "-￥ 0.18",
            "交易方式",
            "花呗",
            "本店特价限时抢购",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 2182
    assert payload["merchant"] == "乐尔乐特价批发超市"
    assert payload["category"] == "购物"


def test_recognize_text_wechat_payment_line_merchant_candidate(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "微信支付",
            "Q",
            "Jack",
            "使用建设银行储蓄卡支付",
            "¥5.00",
            "交易状态",
            "支付成功，对方已收款",
            "查看账单详情",
            "商家名片",
            "星期二07:19",
            "松针小笼包",
            "使用建设银行储蓄卡(0436)支付",
            "¥10.00",
            "账单详情>",
            "我的账单",
            "支付服务",
            "摇优惠",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 500
    assert payload["merchant"] == "Jack"
    assert payload["category"] == "其他"


def test_recognize_text_ignores_status_bar_numbers_and_destination_text(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    raw_text = "\n".join(
        [
            "花溪工业园区",
            "高德地图",
            "21:15",
            ".·5G",
            "91",
            "好想来零食乐园（重庆巴南区珠江城店）",
            "订单支付",
            "鲸志出行-经济型|余师傅·渝AA77599",
            "物品遗失打电话",
            "11.73元",
            "费用说明）",
            "起步价",
            "11.73元",
            "高德打车",
            "高德打车聚合平台由北京易行出行旅游有限公司运营并提供服务",
            "已开启免密支付，将于05月06日21:17自动扣款",
            "11.73元",
            "共计",
            "确认支付",
        ]
    )
    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=app_headers(),
        json={"raw_text": raw_text},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 1173
    assert payload["merchant"] == "高德"
    assert payload["category"] == "交通"


def test_retry_ocr_rejects_stale_pending_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expense_id = upload_png(client)

    def slow_ocr_result(expense: Expense) -> OcrResult:
        with SessionLocal() as user_db:
            row = user_db.get(Expense, expense.id)
            assert row is not None
            row.merchant = "鐢ㄦ埛鎵嬪姩淇敼"
            row.amount_cents = 1234
            row.updated_at = (row.updated_at or row.created_at) + timedelta(seconds=5)
            user_db.commit()
        return OcrResult(
            raw_text="OCR 鍟嗗\n99.99",
            amount_cents=9999,
            merchant="OCR 鍟嗗",
            confidence=0.9,
        )

    monkeypatch.setattr("app.services.expense_service.extract_ocr_result", slow_ocr_result)

    with SessionLocal() as db:
        with pytest.raises(AppError) as exc_info:
            retry_expense_ocr(db, expense_id, "owner")

    assert exc_info.value.error == "expense_changed"
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.merchant == "鐢ㄦ埛鎵嬪姩淇敼"
        assert row.amount_cents == 1234


def test_mock_ocr_provider_populates_pending_draft() -> None:
    expense = Expense(status="pending", category="其他", raw_text="")
    retry_ocr(expense, MockOcrProvider())
    assert expense.amount_cents == 1851
    assert expense.merchant == "中国建设银行"
    assert expense.expense_time is not None
    assert expense.confidence is not None and expense.confidence >= 0.8


def test_manual_expense_create_contract(client: TestClient) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 1280,
            "merchant": "手动早餐",
            "category": "餐饮",
            "note": "上班路上",
            "expense_time": "2026-05-04T00:30:00Z",
            "tags": "手动",
            "value_score": 4,
            "regret_score": 1,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    UUID(payload["public_id"])
    assert payload["source"] == "手动记账"
    assert payload["amount_cents"] == 1280
    assert payload["image_path"] is None
    assert payload["confirmed_at"].endswith("Z")

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮", headers=app_headers()
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 1280

    missing_amount = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={"merchant": "无金额"},
    )
    assert missing_amount.status_code == 400
    assert missing_amount.json()["error"] == "amount_required"


def test_confirmed_batch_update_scopes_and_updates_tags(client: TestClient) -> None:
    def _manual(headers: dict[str, str], merchant: str, category: str) -> int:
        response = client.post(
            "/api/expenses/manual",
            headers=headers,
            json={
                "amount_cents": 1200,
                "merchant": merchant,
                "category": category,
                "expense_time": "2026-05-05T12:00:00Z",
            },
        )
        assert response.status_code == 200, response.json()
        return int(response.json()["id"])

    first_id = _manual(app_headers(), "Batch Coffee A", "OldCat")
    second_id = _manual(app_headers(), "Batch Coffee B", "OldCat")
    other_ledger_id = _manual(gray_app_headers(), "Batch Other Ledger", "GrayCat")
    pending_id = upload_png(client)

    response = client.post(
        "/api/expenses/confirmed/batch-update",
        headers=app_headers(),
        json={
            "expense_ids": [first_id, second_id, pending_id, other_ledger_id, first_id],
            "category": "Family Meals",
            "tags": "weekend, shared, weekend",
        },
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload == {
        "requested_count": 4,
        "updated_count": 2,
        "skipped_not_found": 1,
        "skipped_not_confirmed": 1,
    }

    for expense_id in [first_id, second_id]:
        detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
        assert detail.status_code == 200
        assert detail.json()["category"] == "Family Meals"
        assert detail.json()["tags"] == "weekend, shared"

    pending_detail = client.get(f"/api/expenses/{pending_id}", headers=app_headers())
    assert pending_detail.status_code == 200
    assert pending_detail.json()["category"] != "Family Meals"

    other_detail = client.get(f"/api/expenses/{other_ledger_id}", headers=gray_app_headers())
    assert other_detail.status_code == 200
    assert other_detail.json()["category"] == "GrayCat"


def test_expense_update_normalizes_user_text(client: TestClient) -> None:
    expense_id = upload_png(client)

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "amount_cents": 990,
            "merchant": "  便利店  ",
            "category": "  生活  ",
            "note": "  夜宵  ",
            "tags": "  真机联调  ",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["merchant"] == "便利店"
    assert payload["category"] == "生活"
    assert payload["note"] == "夜宵"
    assert payload["tags"] == "真机联调"

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={"category": "吃饭"},
    )
    assert response.status_code == 200
    assert response.json()["category"] == "餐饮"

    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={
            "merchant": "   ",
            "category": "   ",
            "note": None,
            "tags": "   ",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["merchant"] is None
    assert payload["category"] == "其他"
    assert payload["note"] == ""
    assert payload["tags"] is None


def test_duplicate_and_category_rule_contract(client: TestClient) -> None:
    first_id = upload_png(client)
    second_id = upload_png(client)

    duplicates = client.get("/api/duplicates", headers=app_headers())
    assert duplicates.status_code == 200
    assert any(item["id"] == second_id for item in duplicates.json())

    response = client.post(f"/api/expenses/{second_id}/reject", headers=app_headers())
    assert response.status_code == 200
    duplicates = client.get("/api/duplicates", headers=app_headers())
    assert duplicates.status_code == 200
    assert all(item["id"] != second_id for item in duplicates.json())

    second_id = upload_png(client)
    duplicates = client.get("/api/duplicates", headers=app_headers())
    assert duplicates.status_code == 200
    assert any(item["id"] == second_id for item in duplicates.json())

    response = client.post(
        f"/api/expenses/{second_id}/mark-not-duplicate", headers=app_headers()
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    response = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={
            "keyword": "测试商家",
            "category": "生活",
            "enabled": True,
            "priority": 1,
        },
    )
    assert response.status_code == 200
    rule_id = int(response.json()["id"])

    response = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=app_headers(),
        json={"priority": 2, "enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 2
    assert response.json()["enabled"] is False

    response = client.delete(f"/api/rules/categories/{rule_id}", headers=app_headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    reject = client.post(f"/api/expenses/{first_id}/reject", headers=app_headers())
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


def test_similar_expense_duplicate_ignore_survives_after_edit(client: TestClient) -> None:
    first_id = upload_png(client)
    second_id = upload_png(client)
    client.post(f"/api/expenses/{second_id}/mark-not-duplicate", headers=app_headers())

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = client.patch(
            f"/api/expenses/{expense_id}",
            headers=app_headers(),
            json={
                "amount_cents": 5200,
                "merchant": "同一家店",
                "category": "生活",
                "expense_time": timestamp,
            },
        )
        assert response.status_code == 200

    second = client.get("/api/expenses/pending", headers=app_headers()).json()
    matched = next(item for item in second if item["id"] == second_id)
    assert matched["duplicate_status"] == "none"
    assert matched["duplicate_of_id"] is None


def test_editing_duplicate_original_revalidates_stale_references(client: TestClient) -> None:
    first = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 5200,
            "merchant": "Same Store",
            "category": "生活",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert first.status_code == 200, first.json()
    first_id = first.json()["id"]
    second = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 5200,
            "merchant": "Same Store",
            "category": "生活",
            "expense_time": "2026-05-03T05:20:00Z",
        },
    )
    assert second.status_code == 200, second.json()
    second_id = second.json()["id"]
    assert second.json()["duplicate_of_id"] == first_id

    response = client.patch(
        f"/api/expenses/{first_id}",
        headers=app_headers(),
        json={
            "amount_cents": 5200,
            "merchant": "Changed Original",
            "category": "生活",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert response.status_code == 200

    after = client.get(f"/api/expenses/{second_id}", headers=app_headers())
    assert after.status_code == 200
    assert after.json()["duplicate_status"] == "none"
    assert after.json()["duplicate_of_id"] is None
