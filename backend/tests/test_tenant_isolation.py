from __future__ import annotations


from fastapi.testclient import TestClient

from api_contract_helpers import (
    upload_png,
)
from app.database import SessionLocal, migrate_upload_paths_to_tenant_dirs
from app.models import Expense
from conftest import (
    BACKEND_ROOT,
    PNG_BYTES,
    TEST_UPLOAD_DIR,
    app_headers,
    gray_app_headers,
    gray_upload_headers,
    gray_upload_url_path,
    upload_headers,
)


def test_android_app_upload_uses_app_token_and_current_tenant(
    client: TestClient,
) -> None:
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
    assert owner_pending.json()[0]["image_path"].startswith(
        "uploads/pytest_test/owner/"
    )

    tester_pending = client.get("/api/expenses/pending", headers=gray_app_headers())
    assert tester_pending.status_code == 200
    assert tester_pending.json() == []

    tester_response = client.post(
        "/api/app/upload-screenshot",
        headers=gray_app_headers(),
        files={"file": ("tester-android-ticket.png", PNG_BYTES, "image/png")},
    )
    assert tester_response.status_code == 200
    tester_id = int(tester_response.json()["id"])

    tester_pending = client.get("/api/expenses/pending", headers=gray_app_headers())
    assert tester_pending.status_code == 200
    assert [item["id"] for item in tester_pending.json()] == [tester_id]
    assert tester_pending.json()[0]["image_path"].startswith(
        "uploads/pytest_test/tester_1/"
    )

    owner_pending = client.get("/api/expenses/pending", headers=app_headers())
    assert owner_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]


def test_protected_image_and_thumbnail_reject_database_path_escape(
    client: TestClient,
) -> None:
    expense_id = upload_png(client)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.image_path = "../outside.png"
        expense.thumbnail_path = "../outside-thumb.jpg"
        db.commit()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=app_headers())
    assert image.status_code == 404
    assert image.json() == {"error": "image_not_found", "message": "图片不存在或已被清理。"}

    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=app_headers()
    )
    assert thumbnail.status_code == 404
    assert thumbnail.json() == {"error": "image_not_found", "message": "图片不存在或已被清理。"}


def test_legacy_upload_paths_migrate_into_current_tenant_dir(
    client: TestClient,
) -> None:
    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_image = legacy_dir / "legacy.png"
    legacy_image.write_bytes(PNG_BYTES)
    legacy_thumb_dir = legacy_dir / "thumbs"
    legacy_thumb_dir.mkdir(parents=True, exist_ok=True)
    legacy_thumb = legacy_thumb_dir / "legacy.jpg"
    legacy_thumb.write_bytes(PNG_BYTES)

    legacy_image_path = legacy_image.relative_to(BACKEND_ROOT).as_posix()
    legacy_thumb_path = legacy_thumb.relative_to(BACKEND_ROOT).as_posix()
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=legacy_image_path,
            thumbnail_path=legacy_thumb_path,
            image_hash="legacy-test-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    migrate_upload_paths_to_tenant_dirs()

    with SessionLocal() as db:
        migrated = db.get(Expense, expense_id)
        assert migrated is not None
        assert migrated.image_path.startswith("uploads/pytest_test/owner/2026/05/")
        assert migrated.thumbnail_path.startswith(
            "uploads/pytest_test/owner/2026/05/thumbs/"
        )
        migrated_image_path = BACKEND_ROOT / migrated.image_path
        migrated_thumb_path = BACKEND_ROOT / migrated.thumbnail_path

    assert not legacy_image.exists()
    assert not legacy_thumb.exists()
    assert migrated_image_path.is_file()
    assert migrated_thumb_path.is_file()
    assert (
        client.get(
            f"/api/expenses/{expense_id}/image", headers=app_headers()
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/expenses/{expense_id}/thumbnail", headers=app_headers()
        ).status_code
        == 200
    )


def test_expense_mutation_routes_are_tenant_scoped(client: TestClient) -> None:
    owner_id = upload_png(client, upload_headers())

    scoped_operations = [
        client.patch(
            f"/api/expenses/{owner_id}",
            headers=gray_app_headers(),
            json={"amount_cents": 1000, "merchant": "跨租户"},
        ),
        client.post(f"/api/expenses/{owner_id}/confirm", headers=gray_app_headers()),
        client.post(f"/api/expenses/{owner_id}/reject", headers=gray_app_headers()),
        client.post(f"/api/expenses/{owner_id}/ocr/retry", headers=gray_app_headers()),
        client.post(
            f"/api/expenses/{owner_id}/recognize-text",
            headers=gray_app_headers(),
            json={"raw_text": "交易金额：18.51"},
        ),
        client.post(
            f"/api/expenses/{owner_id}/mark-not-duplicate", headers=gray_app_headers()
        ),
    ]
    for response in scoped_operations:
        assert response.status_code == 404
        assert response.json()["error"] == "expense_not_found"

    owner = client.get(f"/api/expenses/{owner_id}", headers=app_headers())
    assert owner.status_code == 200
    assert owner.json()["status"] == "pending"
    assert owner.json()["amount_cents"] is None


def test_confirmed_lifestyle_and_settings_are_tenant_scoped(client: TestClient) -> None:
    owner = client.post(
        "/api/expenses/manual",
        headers=app_headers(),
        json={
            "amount_cents": 9900,
            "merchant": "owner高频商家",
            "category": "数码",
            "expense_time": "2026-05-05T01:00:00Z",
        },
    )
    assert owner.status_code == 200

    tester_upload_id = upload_png(client, gray_upload_headers(), gray_upload_url_path())

    tester_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=gray_app_headers()
    )
    assert tester_confirmed.status_code == 200
    assert tester_confirmed.json()["total"] == 0

    tester_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=gray_app_headers()
    )
    assert tester_lifestyle.status_code == 200
    payload = tester_lifestyle.json()
    assert payload["digital_amount_cents"] == 0
    assert payload["max_expense"] is None
    assert payload["frequent_merchants"] == []

    owner_settings = client.get("/api/settings/server", headers=app_headers())
    tester_settings = client.get("/api/settings/server", headers=gray_app_headers())
    assert owner_settings.status_code == 200
    assert tester_settings.status_code == 200
    owner_payload = owner_settings.json()
    tester_payload = tester_settings.json()
    assert owner_payload["account_name"] == "我"
    assert owner_payload["ledger_name"] == "我的小票夹"
    assert owner_payload["device_name"] == "pytest-android"
    assert owner_payload["role"] == "owner"
    assert owner_payload["confirmed_count"] == 1
    assert owner_payload["pending_count"] == 0
    assert tester_payload["account_name"] == "我"
    assert tester_payload["ledger_name"] == "灰度用户1"
    assert tester_payload["device_name"] == "pytest-gray-android"
    assert tester_payload["role"] == "owner"
    assert tester_payload["confirmed_count"] == 0
    assert tester_payload["pending_count"] == 1
    assert tester_payload["latest_upload_at"].endswith("Z")
    assert "ocr_provider" not in tester_payload
    assert "delete_image_after_confirm" not in tester_payload
    assert tester_upload_id in [
        item["id"]
        for item in client.get(
            "/api/expenses/pending", headers=gray_app_headers()
        ).json()
    ]


def test_tenants_cannot_read_each_other_expenses_images_stats_rules_or_duplicates(
    client: TestClient,
) -> None:
    owner_id = upload_png(client, upload_headers())
    tester_id = upload_png(client, gray_upload_headers(), gray_upload_url_path())

    owner_pending = client.get("/api/expenses/pending", headers=app_headers()).json()
    tester_pending = client.get(
        "/api/expenses/pending", headers=gray_app_headers()
    ).json()
    assert [item["id"] for item in owner_pending] == [owner_id]
    assert [item["id"] for item in tester_pending] == [tester_id]

    assert (
        client.get(f"/api/expenses/{owner_id}", headers=gray_app_headers()).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/expenses/{owner_id}/image", headers=gray_app_headers()
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/expenses/{owner_id}/thumbnail", headers=gray_app_headers()
        ).status_code
        == 404
    )

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
    assert (
        client.post(
            f"/api/expenses/{owner_id}/confirm", headers=app_headers()
        ).status_code
        == 200
    )

    tester_stats = client.get(
        "/api/stats/monthly?month=2026-05", headers=gray_app_headers()
    )
    assert tester_stats.status_code == 200
    assert tester_stats.json()["total_amount_cents"] == 0

    owner_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    assert owner_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1000

    tester_csv = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=gray_app_headers()
    )
    assert tester_csv.status_code == 200
    assert "owner商家" not in tester_csv.text

    rule = client.post(
        "/api/rules/categories",
        headers=gray_app_headers(),
        json={
            "keyword": "只属于tester",
            "category": "购物",
            "enabled": True,
            "priority": 1,
        },
    )
    assert rule.status_code == 200
    owner_rules = client.get("/api/rules/categories", headers=app_headers()).json()
    tester_rules = client.get(
        "/api/rules/categories", headers=gray_app_headers()
    ).json()
    assert all(item["keyword"] != "只属于tester" for item in owner_rules)
    assert any(item["keyword"] == "只属于tester" for item in tester_rules)

    second_owner_id = upload_png(client, upload_headers())
    owner_duplicates = client.get("/api/duplicates", headers=app_headers()).json()
    tester_duplicates = client.get("/api/duplicates", headers=gray_app_headers()).json()
    assert any(item["id"] == second_owner_id for item in owner_duplicates)
    assert all(item["id"] != second_owner_id for item in tester_duplicates)

    same_hash_tester_id = upload_png(
        client, gray_upload_headers(), gray_upload_url_path()
    )
    same_hash_tester_pending = client.get(
        "/api/expenses/pending", headers=gray_app_headers()
    ).json()
    tester_match = next(
        item for item in same_hash_tester_pending if item["id"] == same_hash_tester_id
    )
    assert tester_match["duplicate_status"] == "suspected"
    assert tester_match["duplicate_of_id"] == tester_id
    assert tester_match["duplicate_of_id"] != second_owner_id


def test_owner_and_tester_tokens_are_hard_isolated_across_acceptance_surface(
    client: TestClient,
) -> None:
    owner_id = upload_png(client, upload_headers())
    tester_id = upload_png(client, gray_upload_headers(), gray_upload_url_path())

    owner_detail = client.get(f"/api/expenses/{owner_id}", headers=app_headers()).json()
    tester_detail = client.get(
        f"/api/expenses/{tester_id}", headers=gray_app_headers()
    ).json()
    assert owner_detail["image_path"].startswith("uploads/pytest_test/owner/")
    assert tester_detail["image_path"].startswith("uploads/pytest_test/tester_1/")
    if owner_detail["thumbnail_path"]:
        assert owner_detail["thumbnail_path"].startswith("uploads/pytest_test/owner/")
    if tester_detail["thumbnail_path"]:
        assert tester_detail["thumbnail_path"].startswith(
            "uploads/pytest_test/tester_1/"
        )

    owner_pending = client.get("/api/expenses/pending", headers=app_headers())
    tester_pending = client.get("/api/expenses/pending", headers=gray_app_headers())
    assert owner_pending.status_code == 200
    assert tester_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]
    assert [item["id"] for item in tester_pending.json()] == [tester_id]

    cross_mutations = [
        client.patch(
            f"/api/expenses/{tester_id}",
            headers=app_headers(),
            json={"amount_cents": 1, "merchant": "owner不该改tester"},
        ),
        client.post(f"/api/expenses/{tester_id}/confirm", headers=app_headers()),
        client.post(f"/api/expenses/{tester_id}/reject", headers=app_headers()),
        client.patch(
            f"/api/expenses/{owner_id}",
            headers=gray_app_headers(),
            json={"amount_cents": 1, "merchant": "tester不该改owner"},
        ),
        client.post(f"/api/expenses/{owner_id}/confirm", headers=gray_app_headers()),
        client.post(f"/api/expenses/{owner_id}/reject", headers=gray_app_headers()),
    ]
    for response in cross_mutations:
        assert response.status_code == 404
        assert response.json()["error"] == "expense_not_found"

    for path in [
        f"/api/expenses/{owner_id}",
        f"/api/expenses/{owner_id}/image",
        f"/api/expenses/{owner_id}/thumbnail",
    ]:
        assert client.get(path, headers=gray_app_headers()).status_code == 404
    for path in [
        f"/api/expenses/{tester_id}",
        f"/api/expenses/{tester_id}/image",
        f"/api/expenses/{tester_id}/thumbnail",
    ]:
        assert client.get(path, headers=app_headers()).status_code == 404

    owner_patch = client.patch(
        f"/api/expenses/{owner_id}",
        headers=app_headers(),
        json={
            "amount_cents": 1111,
            "merchant": "owner隔离商家",
            "category": "Owner自定义类",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    tester_patch = client.patch(
        f"/api/expenses/{tester_id}",
        headers=gray_app_headers(),
        json={
            "amount_cents": 2222,
            "merchant": "tester隔离商家",
            "category": "Tester自定义类",
            "expense_time": "2026-05-04T02:00:00Z",
        },
    )
    assert owner_patch.status_code == 200
    assert tester_patch.status_code == 200
    assert (
        client.post(
            f"/api/expenses/{owner_id}/confirm", headers=app_headers()
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/expenses/{tester_id}/confirm", headers=gray_app_headers()
        ).status_code
        == 200
    )

    owner_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=app_headers()
    )
    tester_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=gray_app_headers()
    )
    assert owner_confirmed.status_code == 200
    assert tester_confirmed.status_code == 200
    assert [item["id"] for item in owner_confirmed.json()["items"]] == [owner_id]
    assert [item["id"] for item in tester_confirmed.json()["items"]] == [tester_id]

    owner_stats = client.get("/api/stats/monthly?month=2026-05", headers=app_headers())
    tester_stats = client.get(
        "/api/stats/monthly?month=2026-05", headers=gray_app_headers()
    )
    assert owner_stats.status_code == 200
    assert tester_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1111
    assert tester_stats.json()["total_amount_cents"] == 2222
    assert owner_stats.json()["count"] == 1
    assert tester_stats.json()["count"] == 1

    owner_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=app_headers()
    )
    tester_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=gray_app_headers()
    )
    assert owner_lifestyle.status_code == 200
    assert tester_lifestyle.status_code == 200
    assert owner_lifestyle.json()["max_expense"]["id"] == owner_id
    assert tester_lifestyle.json()["max_expense"]["id"] == tester_id
    assert owner_lifestyle.json()["max_expense"]["merchant"] == "owner隔离商家"
    assert tester_lifestyle.json()["max_expense"]["merchant"] == "tester隔离商家"

    owner_export = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=app_headers()
    )
    tester_export = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=gray_app_headers()
    )
    assert owner_export.status_code == 200
    assert tester_export.status_code == 200
    assert "owner隔离商家" in owner_export.text
    assert "tester隔离商家" not in owner_export.text
    assert "tester隔离商家" in tester_export.text
    assert "owner隔离商家" not in tester_export.text

    owner_categories = client.get(
        "/api/expenses/categories", headers=app_headers()
    ).json()["items"]
    tester_categories = client.get(
        "/api/expenses/categories", headers=gray_app_headers()
    ).json()["items"]
    assert "Owner自定义类" in owner_categories
    assert "Tester自定义类" not in owner_categories
    assert "Tester自定义类" in tester_categories
    assert "Owner自定义类" not in tester_categories

    owner_rule = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={
            "keyword": "owner规则",
            "category": "Owner自定义类",
            "enabled": True,
            "priority": 1,
        },
    )
    tester_rule = client.post(
        "/api/rules/categories",
        headers=gray_app_headers(),
        json={
            "keyword": "tester规则",
            "category": "Tester自定义类",
            "enabled": True,
            "priority": 1,
        },
    )
    assert owner_rule.status_code == 200
    assert tester_rule.status_code == 200
    owner_rules = client.get("/api/rules/categories", headers=app_headers()).json()
    tester_rules = client.get(
        "/api/rules/categories", headers=gray_app_headers()
    ).json()
    assert any(item["keyword"] == "owner规则" for item in owner_rules)
    assert all(item["keyword"] != "tester规则" for item in owner_rules)
    assert any(item["keyword"] == "tester规则" for item in tester_rules)
    assert all(item["keyword"] != "owner规则" for item in tester_rules)

    owner_settings = client.get("/api/settings/server", headers=app_headers()).json()
    tester_settings = client.get(
        "/api/settings/server", headers=gray_app_headers()
    ).json()
    assert owner_settings["ledger_name"] == "我的小票夹"
    assert tester_settings["ledger_name"] == "灰度用户1"
    assert owner_settings["confirmed_count"] == 1
    assert tester_settings["confirmed_count"] == 1
    assert owner_settings["pending_count"] == 0
    assert tester_settings["pending_count"] == 0
    assert owner_settings["rejected_count"] == 0
    assert tester_settings["rejected_count"] == 0
    assert owner_settings["upload_storage_bytes"] > 0
    assert tester_settings["upload_storage_bytes"] > 0
    assert owner_settings["latest_upload_at"].endswith("Z")
    assert tester_settings["latest_upload_at"].endswith("Z")

    owner_duplicate_id = upload_png(client, upload_headers())
    tester_duplicate_id = upload_png(
        client, gray_upload_headers(), gray_upload_url_path()
    )
    owner_duplicates = client.get("/api/duplicates", headers=app_headers()).json()
    tester_duplicates = client.get("/api/duplicates", headers=gray_app_headers()).json()
    assert any(
        item["id"] == owner_duplicate_id and item["duplicate_of_id"] == owner_id
        for item in owner_duplicates
    )
    assert all(item["id"] != tester_duplicate_id for item in owner_duplicates)
    assert any(
        item["id"] == tester_duplicate_id and item["duplicate_of_id"] == tester_id
        for item in tester_duplicates
    )
    assert all(item["id"] != owner_duplicate_id for item in tester_duplicates)


def test_category_rule_mutations_are_tenant_scoped(client: TestClient) -> None:
    owner_rule = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={
            "keyword": "owner专属",
            "category": "数码",
            "enabled": True,
            "priority": 5,
        },
    )
    assert owner_rule.status_code == 200
    rule_id = int(owner_rule.json()["id"])

    patch = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=gray_app_headers(),
        json={"keyword": "tester不该改", "category": "购物", "priority": 1},
    )
    assert patch.status_code == 404
    assert patch.json()["error"] == "rule_not_found"

    delete = client.delete(
        f"/api/rules/categories/{rule_id}", headers=gray_app_headers()
    )
    assert delete.status_code == 404
    assert delete.json()["error"] == "rule_not_found"

    owner_rules = client.get("/api/rules/categories", headers=app_headers()).json()
    assert any(
        item["id"] == rule_id and item["keyword"] == "owner专属" for item in owner_rules
    )
