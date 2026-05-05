from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from conftest import PNG_BYTES, admin_headers, app_headers, gray_app_headers, gray_upload_headers, upload_headers
from app.models import Expense
from app.services.ocr_service import MockOcrProvider, retry_ocr


def upload_png(client: TestClient, headers: dict[str, str] | None = None) -> int:
    response = client.post(
        "/api/upload-screenshot",
        headers=headers or upload_headers(),
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    UUID(payload["public_id"])
    return int(payload["id"])


def upload_png_as_raw_body(client: TestClient) -> int:
    response = client.post(
        "/api/upload-screenshot",
        headers={**upload_headers(), "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    return int(payload["id"])


def test_health_and_auth_contract(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}

    response = client.get("/api/auth/check", headers=app_headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "tenant_name": "我的小票夹"}

    response = client.get("/api/auth/check", headers={"Authorization": "Bearer bad"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert response.json()["message"]


def test_upload_check_contract(client: TestClient) -> None:
    response = client.get("/api/upload/check", headers=upload_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["max_upload_size_mb"] == 10
    assert payload["recommended_body"] == "file"
    assert "png" in payload["supported_file_types"]
    assert "token" not in str(payload).lower()
    assert "path" not in str(payload).lower()

    response = client.get("/api/upload/check", headers={"Upload-Token": "bad"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_framework_errors_use_uniform_chinese_shape(client: TestClient) -> None:
    response = client.get("/api/not-exists", headers=app_headers())
    assert response.status_code == 404
    assert response.json() == {"error": "route_not_found", "message": "接口不存在。"}

    response = client.post("/api/health")
    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed", "message": "请求方法不允许。"}


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

    thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=app_headers())
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

    exported = client.get("/api/expenses/export.csv?month=2026-05&category=餐饮", headers=app_headers())
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "美团外卖" in exported.text
    assert "public_id" in exported.text.splitlines()[0]
    assert "3680" in exported.text

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 3680


def test_upload_screenshot_accepts_ios_file_body(client: TestClient) -> None:
    expense_id = upload_png_as_raw_body(client)

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["status"] == "pending"
    assert item["image_path"].startswith("uploads/")
    assert item["image_path"].endswith(".png")
    assert item["image_hash"]


def test_upload_screenshot_accepts_ios_image_form_field(client: TestClient) -> None:
    response = client.post(
        "/api/upload-screenshot",
        headers=upload_headers(),
        files={"image": ("shortcut-image.jpeg", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    expense_id = int(response.json()["id"])

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["image_path"].endswith(".png")
    assert item["image_hash"]


def test_android_app_upload_uses_app_token_and_current_tenant(client: TestClient) -> None:
    response = client.post(
        "/api/app/upload-screenshot",
        headers=app_headers(),
        files={"file": ("android-ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    owner_id = int(response.json()["id"])

    owner_pending = client.get("/api/expenses/pending", headers=app_headers())
    assert owner_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]

    tester_pending = client.get("/api/expenses/pending", headers=gray_app_headers())
    assert tester_pending.status_code == 200
    assert tester_pending.json() == []


def test_tenants_cannot_read_each_other_expenses_images_stats_rules_or_duplicates(client: TestClient) -> None:
    owner_id = upload_png(client, upload_headers())
    tester_id = upload_png(client, gray_upload_headers())

    owner_pending = client.get("/api/expenses/pending", headers=app_headers()).json()
    tester_pending = client.get("/api/expenses/pending", headers=gray_app_headers()).json()
    assert [item["id"] for item in owner_pending] == [owner_id]
    assert [item["id"] for item in tester_pending] == [tester_id]

    assert client.get(f"/api/expenses/{owner_id}", headers=gray_app_headers()).status_code == 404
    assert client.get(f"/api/expenses/{owner_id}/image", headers=gray_app_headers()).status_code == 404
    assert client.get(f"/api/expenses/{owner_id}/thumbnail", headers=gray_app_headers()).status_code == 404

    owner_patch = client.patch(
        f"/api/expenses/{owner_id}",
        headers=app_headers(),
        json={
            "amount_cents": 1000,
            "merchant": "owner商家",
            "category": "生活",
            "expense_time": "2026-05-04T00:00:00Z",
        },
    )
    assert owner_patch.status_code == 200
    assert client.post(f"/api/expenses/{owner_id}/confirm", headers=app_headers()).status_code == 200

    tester_stats = client.get("/api/stats/monthly?month=2026-05", headers=gray_app_headers())
    assert tester_stats.status_code == 200
    assert tester_stats.json()["total_amount_cents"] == 0

    owner_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert owner_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1000

    tester_csv = client.get("/api/expenses/export.csv?month=2026-05", headers=gray_app_headers())
    assert tester_csv.status_code == 200
    assert "owner商家" not in tester_csv.text

    rule = client.post(
        "/api/rules/categories",
        headers=gray_app_headers(),
        json={"keyword": "只属于tester", "category": "购物", "enabled": True, "priority": 1},
    )
    assert rule.status_code == 200
    owner_rules = client.get("/api/rules/categories", headers=app_headers()).json()
    tester_rules = client.get("/api/rules/categories", headers=gray_app_headers()).json()
    assert all(item["keyword"] != "只属于tester" for item in owner_rules)
    assert any(item["keyword"] == "只属于tester" for item in tester_rules)

    second_owner_id = upload_png(client, upload_headers())
    owner_duplicates = client.get("/api/duplicates", headers=app_headers()).json()
    tester_duplicates = client.get("/api/duplicates", headers=gray_app_headers()).json()
    assert any(item["id"] == second_owner_id for item in owner_duplicates)
    assert all(item["id"] != second_owner_id for item in tester_duplicates)


def test_upload_screenshot_rejects_multipart_without_image_file(client: TestClient) -> None:
    response = client.post(
        "/api/upload-screenshot",
        headers=upload_headers(),
        files={"note": (None, "not an image")},
    )
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request", "message": "表单里没有找到图片文件。"}


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


def test_recognize_text_prefers_transaction_time_over_other_times(client: TestClient) -> None:
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


def test_mock_ocr_provider_populates_pending_draft() -> None:
    expense = Expense(category="其他", raw_text="")
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

    confirmed = client.get("/api/expenses/confirmed?month=2026-05&category=餐饮", headers=app_headers())
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


def test_confirmed_pagination_and_month_filters_are_server_side_contract(client: TestClient) -> None:
    for index, payload in enumerate(
        [
            {"amount_cents": 1100, "merchant": "早餐店", "category": "餐饮", "expense_time": "2026-05-01T00:00:00Z"},
            {"amount_cents": 2200, "merchant": "地铁", "category": "交通", "expense_time": "2026-05-02T00:00:00Z"},
            {"amount_cents": 3300, "merchant": "晚饭", "category": "餐饮", "expense_time": "2026-05-03T00:00:00Z"},
            {"amount_cents": 4400, "merchant": "上月", "category": "餐饮", "expense_time": "2026-04-30T00:00:00Z"},
        ],
        start=1,
    ):
        response = client.post(
            "/api/expenses/manual",
            headers=app_headers(),
            json={**payload, "note": f"分页测试 {index}"},
        )
        assert response.status_code == 200

    first_page = client.get("/api/expenses/confirmed?month=2026-05&page=1&page_size=2", headers=app_headers())
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["total"] == 3
    assert [item["merchant"] for item in first_payload["items"]] == ["晚饭", "地铁"]

    second_page = client.get("/api/expenses/confirmed?month=2026-05&page=2&page_size=2", headers=app_headers())
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["total"] == 3
    assert [item["merchant"] for item in second_payload["items"]] == ["早餐店"]

    category_page = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮&page=1&page_size=50",
        headers=app_headers(),
    )
    assert category_page.status_code == 200
    category_payload = category_page.json()
    assert category_payload["total"] == 2
    assert [item["merchant"] for item in category_payload["items"]] == ["晚饭", "早餐店"]

    stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["total_amount_cents"] == 6600
    assert stats_payload["count"] == 3

    months = client.get("/api/expenses/months", headers=app_headers())
    assert months.status_code == 200
    assert months.json()["items"] == ["2026-05", "2026-04"]


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

    response = client.post(f"/api/expenses/{second_id}/mark-not-duplicate", headers=app_headers())
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    response = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "测试商家", "category": "生活", "enabled": True, "priority": 1},
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


def test_similar_expense_duplicate_detection_after_edit(client: TestClient) -> None:
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
    assert matched["duplicate_status"] == "suspected"
    assert matched["duplicate_of_id"] == first_id
    assert "金额" in matched["duplicate_reason"]


def test_admin_maintenance_requires_admin_token(client: TestClient) -> None:
    response = client.post("/api/maintenance/cleanup-images", headers=app_headers())
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"

    response = client.post("/api/maintenance/cleanup-images", headers=admin_headers())
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_server_settings_snapshot_does_not_expose_paths_or_tokens(client: TestClient) -> None:
    upload_png(client)
    response = client.get("/api/settings/server", headers=app_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_name"] == "我的小票夹"
    assert payload["max_upload_size_mb"] == 10
    assert payload["generate_thumbnail"] is True
    assert payload["ocr_provider"] == "empty"
    assert payload["pending_count"] == 1
    assert payload["upload_storage_bytes"] > 0
    assert payload["latest_upload_at"].endswith("Z")
    assert "token" not in str(payload).lower()
    assert "path" not in str(payload).lower()
    assert "E:\\" not in str(payload)
