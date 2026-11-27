from __future__ import annotations

from datetime import timedelta

from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    recognize_text_api,
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

    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=raw_text
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

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="中国建设银行\n交易金额：18.51\n交易时间：2026年5月4日 16:23:25",
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
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=first_raw_text
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
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=corrected_raw_text
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
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=newer_raw_text
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
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=corrected_raw_text
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
    response = recognize_text_api(
        client, expense_id, headers=identity.app_headers, raw_text=corrected_raw_text
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["amount_cents"] == 7200
    assert payload["merchant"] == "用户手动确认商家"
    assert payload["status"] == "pending"


def test_recognize_text_preserves_explicit_other_category_and_cleared_merchant(
    client: TestClient, *, identity,
) -> None:
    from uuid import uuid4

    rule = client.post(
        "/api/rules/categories",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "好想来", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert rule.status_code == 200, rule.text

    expense_id = upload_png(client, identity=identity)
    first = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-17.89\n交易成功\n支付时间\n2026-05-05 21:38:13",
    )
    assert first.status_code == 200, first.text
    assert first.json()["category"] == "餐饮"
    assert first.json()["merchant"] == "好想来零食乐园"

    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"category": "其他", "merchant": ""},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["category"] == "其他"
    assert patched.json()["merchant"] is None

    second = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-28.50\n交易成功\n支付时间\n2026-05-06 10:00:00",
    )
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["amount_cents"] == 2850
    assert payload["category"] == "其他"
    assert payload["merchant"] is None


def test_legacy_null_draft_fields_edited_within_five_minutes_is_not_overwritten(
    client: TestClient, *, identity,
) -> None:
    """Blocker 1: ocr_draft_fields=NULL + row_version>1 within 5 min must protect manual fields."""
    from app.services.currency_binding_service import resolve_write_capability

    expense_id = upload_png(client, identity=identity)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.confidence = 0.9
        expense.amount_cents = 7200
        expense.merchant = "用户手改商户"
        expense.category = "餐饮"
        expense.updated_at = expense.created_at + timedelta(seconds=10)
        expense.row_version = 2
        expense.ocr_draft_fields = None

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n巴南区卢记牛肉面\n-19.00\n交易成功\n支付时间\n2026-05-07 08:30:00",
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["amount_cents"] == 7200
    assert payload["merchant"] == "用户手改商户"


def test_pre_upgrade_ocr_only_partial_list_still_allows_untouched_empty_fields(
    client: TestClient, *, identity,
) -> None:
    """Blocker 2: pre-upgrade OCR-only partial list recovers untouched category/expense_time."""
    import json

    from app.models import BackgroundTask
    from app.services.currency_binding_service import resolve_write_capability

    expense_id = upload_png(client, identity=identity)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.amount_cents = 7200
        expense.merchant = "好想来零食乐园"
        expense.category = "其他"
        expense.expense_time = None
        expense.confidence = 0.9
        expense.row_version = 2
        expense.ocr_draft_fields = json.dumps(["amount_cents", "merchant"])
        db.add(
            BackgroundTask(
                tenant_id=expense.tenant_id,
                task_type="expense_enrichment",
                status="completed",
                source_expense_id=expense.id,
                input_payload_json=json.dumps({"expense_id": expense.id, "expected_row_version": 1}),
                result_summary_json=json.dumps({"expense_id": expense.id, "outcome": "updated", "row_version": 2}),
            )
        )

    response = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-17.89\n交易成功\n支付时间\n2026-05-05 21:38:13",
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["amount_cents"] == 1789
    assert payload["category"] == "餐饮"
    assert payload["expense_time"] is not None


def test_pre_upgrade_null_upload_editing_only_merchant_keeps_other_fields_ocr_eligible(
    client: TestClient, *, identity,
) -> None:
    """Blocker 2: patching only merchant on a pre-upgrade ocr_draft_fields=NULL row preserves amount/time/category."""
    from app.services.currency_binding_service import resolve_write_capability

    expense_id = upload_png(client, identity=identity)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.ocr_draft_fields = None
        expense.confidence = None
        expense.row_version = 1

    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": "用户先填商户"},
    )
    assert patched.status_code == 200, patched.text

    recognized = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-17.89\n交易成功\n支付时间\n2026-05-05 21:38:13",
    )
    assert recognized.status_code == 200, recognized.text
    payload = recognized.json()
    assert payload["merchant"] == "用户先填商户"
    assert payload["amount_cents"] == 1789
    assert payload["expense_time"] is not None
    assert payload["category"] == "餐饮"


def test_patch_explicit_null_original_amount_clears_pending_amount_and_blocks_ocr_overwrite(
    client: TestClient, *, identity,
) -> None:
    """Blocker 3 backend half: explicit original_amount=null clears amount and revokes OCR ownership."""
    expense_id = upload_png(client, identity=identity)
    first = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-17.89\n交易成功\n支付时间\n2026-05-05 21:38:13",
    )
    assert first.status_code == 200, first.text
    assert first.json()["amount_cents"] == 1789
    assert first.json()["original_amount_minor"] == 1789

    cleared = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"original_amount": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["amount_cents"] is None
    assert cleared.json()["original_amount_minor"] is None

    second = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-28.50\n交易成功\n支付时间\n2026-05-06 10:00:00",
    )
    assert second.status_code == 200, second.text
    assert second.json()["amount_cents"] is None
    assert second.json()["original_amount_minor"] is None


def test_legacy_null_confident_row_note_only_patch_within_window_preserves_empty_amount_eligibility(
    client: TestClient, *, identity,
) -> None:
    """R2 Finding 1: ocr_draft_fields=NULL, row_version=1, confidence=0.9 within 5m keeps empty amount OCR-eligible after note-only PATCH."""
    from app.services.currency_binding_service import resolve_write_capability

    expense_id = upload_png(client, identity=identity)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.confidence = 0.9
        expense.merchant = "好想来零食乐园"
        expense.amount_cents = None
        expense.original_amount_minor = None
        expense.category = "其他"
        expense.updated_at = expense.created_at + timedelta(seconds=10)
        expense.row_version = 1
        expense.ocr_draft_fields = None

    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"note": "只改备注"},
    )
    assert patched.status_code == 200, patched.text

    recognized = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-17.89\n交易成功\n支付时间\n2026-05-05 21:38:13",
    )
    assert recognized.status_code == 200, recognized.text
    assert recognized.json()["amount_cents"] == 1789
    assert recognized.json()["note"] == "只改备注"


def test_patch_explicit_null_original_amount_with_manual_exchange_rate_clears_foreign_pending_amount(
    client: TestClient, *, identity,
) -> None:
    """R2 Finding 2: clearing amount on a pending foreign-currency bill with manual_exchange_rate must clear both amounts."""
    expense_id = upload_png(client, identity=identity)
    seeded = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "original_currency": "USD",
            "original_amount": "10.00",
            "manual_exchange_rate": "7",
        },
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["original_amount_minor"] == 1000
    assert seeded.json()["amount_cents"] == 7000

    cleared = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "original_amount": None,
            "manual_exchange_rate": "7",
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["original_amount_minor"] is None
    assert cleared.json()["amount_cents"] is None

    recognized = recognize_text_api(
        client,
        expense_id,
        headers=identity.app_headers,
        raw_text="账单详情\n好想来零食乐园\n-28.50\n交易成功\n支付时间\n2026-05-06 10:00:00",
    )
    assert recognized.status_code == 200, recognized.text
    assert recognized.json()["original_amount_minor"] is None
    assert recognized.json()["amount_cents"] is None
