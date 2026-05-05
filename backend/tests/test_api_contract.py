from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from conftest import PNG_BYTES, admin_headers, app_headers, upload_headers


def upload_png(client: TestClient) -> int:
    response = client.post(
        "/api/upload-screenshot",
        headers=upload_headers(),
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
    assert response.json() == {"status": "ok"}

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
    assert payload["max_upload_size_mb"] == 10
    assert payload["generate_thumbnail"] is True
    assert payload["ocr_provider"] == "empty"
    assert payload["pending_count"] == 1
    assert payload["upload_storage_bytes"] > 0
    assert "token" not in str(payload).lower()
    assert "path" not in str(payload).lower()
    assert "E:\\" not in str(payload)
