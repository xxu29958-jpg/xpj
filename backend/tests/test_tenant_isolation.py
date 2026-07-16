from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from api_contract_helpers import (
    confirm_expense_api,
    mark_not_duplicate_api,
    patch_expense,
    recognize_text_api,
    reject_expense_api,
    retry_ocr_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal, migrate_upload_paths_to_tenant_dirs
from app.models import Expense
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT, TEST_UPLOAD_DIR, TEST_UPLOAD_RELATIVE
from tests._tenant_isolation_contracts import (
    _assert_categories_are_ledger_scoped,
    _assert_category_rule_stays_in_tester_ledger,
    _assert_category_rules_are_ledger_scoped,
    _assert_confirmed_duplicate_detection_is_ledger_scoped,
    _assert_confirmed_expense_lists_are_ledger_scoped,
    _assert_cross_ledger_expense_mutations_are_hidden,
    _assert_cross_ledger_expense_reads_are_hidden,
    _assert_exports_are_ledger_scoped,
    _assert_lifestyle_stats_are_ledger_scoped,
    _assert_monthly_stats_are_ledger_scoped,
    _assert_owner_expense_is_hidden_from_tester_reports,
    _assert_pending_duplicate_detection_stays_in_current_ledger,
    _assert_pending_receipts_are_ledger_scoped,
    _assert_server_settings_are_ledger_scoped,
    _assert_tester_cannot_read_owner_receipt,
    _assert_upload_paths_are_ledger_scoped,
    _confirm_owner_and_tester_isolation_expenses,
    _confirm_owner_may_expense,
    _upload_owner_and_tester_receipts,
)


def test_android_app_upload_uses_app_token_and_current_tenant(
    client: TestClient, *, identity,
) -> None:
    response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.app_headers,
        files={"file": ("android-ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    owner_id = int(response.json()["id"])

    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert owner_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]
    assert owner_pending.json()[0]["image_path"].startswith(
        f"{TEST_UPLOAD_RELATIVE}/owner/"
    )

    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert tester_pending.status_code == 200
    assert tester_pending.json() == []

    tester_response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.gray_app_headers,
        files={"file": ("tester-android-ticket.png", PNG_BYTES, "image/png")},
    )
    assert tester_response.status_code == 200
    tester_id = int(tester_response.json()["id"])

    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert tester_pending.status_code == 200
    assert [item["id"] for item in tester_pending.json()] == [tester_id]
    assert tester_pending.json()[0]["image_path"].startswith(
        f"{TEST_UPLOAD_RELATIVE}/tester_1/"
    )

    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert owner_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]


def test_protected_image_and_thumbnail_reject_database_path_escape(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.image_path = "../outside.png"
        expense.thumbnail_path = "../outside-thumb.jpg"
        db.commit()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    image_body = image.json()
    assert image_body["error"] == "image_not_found"
    assert image_body["message"] == "图片不存在或已被清理。"

    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers
    )
    assert thumbnail.status_code == 404
    thumb_body = thumbnail.json()
    assert thumb_body["error"] == "image_not_found"
    assert thumb_body["message"] == "图片不存在或已被清理。"


@pytest.mark.real_db
def test_legacy_upload_paths_migrate_into_current_tenant_dir(
    client: TestClient, *, identity,
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
        assert migrated.image_path.startswith(f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/")
        assert migrated.thumbnail_path.startswith(
            f"{TEST_UPLOAD_RELATIVE}/owner/2026/05/thumbs/"
        )
        migrated_image_path = BACKEND_ROOT / migrated.image_path
        migrated_thumb_path = BACKEND_ROOT / migrated.thumbnail_path

    assert not legacy_image.exists()
    assert not legacy_thumb.exists()
    assert migrated_image_path.is_file()
    assert migrated_thumb_path.is_file()
    assert (
        client.get(
            f"/api/expenses/{expense_id}/image", headers=identity.app_headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers
        ).status_code
        == 200
    )


@pytest.mark.real_db
def test_legacy_upload_migration_leaves_database_only_reference_untouched(identity) -> None:
    """A legacy ``image_path`` with no on-disk file (a database-only reference)
    is left as-is by ``migrate_upload_paths_to_tenant_dirs`` — the helper only
    rewrites rows whose file physically exists. Ported (ORM form) from the
    retired SQLite-migrator test: ``migrate_upload_paths_to_tenant_dirs`` is
    cross-dialect owner tooling that still needs this coverage.
    """
    missing_path = f"{TEST_UPLOAD_RELATIVE}/2026/05/missing.png"
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=missing_path,
            image_hash="legacy-missing-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    migrate_upload_paths_to_tenant_dirs()

    with SessionLocal() as db:
        unchanged = db.get(Expense, expense_id)
        assert unchanged is not None
        assert unchanged.image_path == missing_path


@pytest.mark.real_db
def test_legacy_upload_migration_rename_failure_keeps_original_file_and_path(
    identity, monkeypatch,
) -> None:
    """If moving a legacy file raises, the original file and its database path
    are both preserved (no half-migrated state). Ported (ORM form) from the
    retired SQLite-migrator test.
    """
    legacy_dir = TEST_UPLOAD_DIR / "2026" / "05"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / "rename-fails.png"
    legacy_file.write_bytes(PNG_BYTES)
    legacy_path = legacy_file.relative_to(BACKEND_ROOT).as_posix()
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            image_path=legacy_path,
            image_hash="legacy-rename-hash",
            status="pending",
        )
        db.add(expense)
        db.commit()
        db.refresh(expense)
        expense_id = expense.id

    def fail_rename(self: Path, target: Path) -> Path:
        raise OSError("simulated move failure")

    monkeypatch.setattr(Path, "rename", fail_rename)

    migrate_upload_paths_to_tenant_dirs()

    assert legacy_file.is_file()
    with SessionLocal() as db:
        preserved = db.get(Expense, expense_id)
        assert preserved is not None
        assert preserved.image_path == legacy_path


def test_expense_mutation_routes_are_tenant_scoped(client: TestClient, *, identity) -> None:
    owner_id = upload_png(client, identity=identity, headers=identity.upload_headers)

    scoped_operations = [
        patch_expense(
            client,
            owner_id,
            headers=identity.gray_app_headers,
            fields={"amount_cents": 1000, "merchant": "跨租户"},
        ),
        confirm_expense_api(client, owner_id, headers=identity.gray_app_headers),
        reject_expense_api(client, owner_id, headers=identity.gray_app_headers),
        retry_ocr_api(client, owner_id, headers=identity.gray_app_headers),
        # ADR-0038 PR-2e: recognize-text helper auto-fetches token; for
        # cross-tenant the GET returns 404 (row not visible), so the
        # helper short-circuits and returns that response — same shape
        # the explicit POST would have returned via the 422 → 404 flow.
        recognize_text_api(
            client,
            owner_id,
            headers=identity.gray_app_headers,
            raw_text="交易金额：18.51",
        ),
        mark_not_duplicate_api(client, owner_id, headers=identity.gray_app_headers),
    ]
    for response in scoped_operations:
        assert response.status_code == 404
        assert response.json()["error"] == "expense_not_found"

    owner = client.get(f"/api/expenses/{owner_id}", headers=identity.app_headers)
    assert owner.status_code == 200
    assert owner.json()["status"] == "pending"
    assert owner.json()["amount_cents"] is None


def test_confirmed_lifestyle_and_settings_are_tenant_scoped(client: TestClient, *, identity) -> None:
    owner = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 9900,
            "merchant": "owner高频商家",
            "category": "数码",
            "expense_time": "2026-05-05T01:00:00Z",
        },
    )
    assert owner.status_code == 200

    tester_upload_id = upload_png(client, identity=identity, headers=identity.gray_upload_headers, path=identity.gray_upload_url_path)

    tester_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.gray_app_headers
    )
    assert tester_confirmed.status_code == 200
    assert tester_confirmed.json()["total"] == 0

    tester_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=identity.gray_app_headers
    )
    assert tester_lifestyle.status_code == 200
    payload = tester_lifestyle.json()
    assert payload["digital_amount_cents"] == 0
    assert payload["max_expense"] is None
    assert payload["frequent_merchants"] == []

    owner_settings = client.get("/api/settings/server", headers=identity.app_headers)
    tester_settings = client.get("/api/settings/server", headers=identity.gray_app_headers)
    assert owner_settings.status_code == 200
    assert tester_settings.status_code == 200
    owner_payload = owner_settings.json()
    tester_payload = tester_settings.json()
    assert owner_payload["account_name"] == "我"
    assert owner_payload["ledger_id"] == "owner"
    assert owner_payload["ledger_name"] == "我的小票夹"
    assert owner_payload["ledger_is_default"] is True
    assert owner_payload["device_name"] == "pytest-android"
    assert owner_payload["role"] == "owner"
    assert owner_payload["confirmed_count"] == 1
    assert owner_payload["pending_count"] == 0
    assert tester_payload["account_name"] == "我"
    assert tester_payload["ledger_id"] == "tester_1"
    assert tester_payload["ledger_name"] == "灰度用户1"
    assert tester_payload["ledger_is_default"] is False
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
            "/api/expenses/pending", headers=identity.gray_app_headers
        ).json()
    ]


def test_tenants_cannot_read_each_other_expenses_images_stats_rules_or_duplicates(
    client: TestClient, *, identity,
) -> None:
    owner_id, tester_id = _upload_owner_and_tester_receipts(client, identity=identity)
    _assert_pending_receipts_are_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_tester_cannot_read_owner_receipt(client, identity=identity, owner_id=owner_id)
    _confirm_owner_may_expense(client, identity=identity, owner_id=owner_id)
    _assert_owner_expense_is_hidden_from_tester_reports(client, identity=identity)
    _assert_category_rule_stays_in_tester_ledger(client, identity=identity)
    _assert_pending_duplicate_detection_stays_in_current_ledger(
        client, identity=identity, tester_id=tester_id
    )


def test_owner_and_tester_tokens_are_hard_isolated_across_acceptance_surface(
    client: TestClient, *, identity,
) -> None:
    owner_id, tester_id = _upload_owner_and_tester_receipts(client, identity=identity)
    _assert_upload_paths_are_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_pending_receipts_are_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_cross_ledger_expense_mutations_are_hidden(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_cross_ledger_expense_reads_are_hidden(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _confirm_owner_and_tester_isolation_expenses(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_confirmed_expense_lists_are_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_monthly_stats_are_ledger_scoped(client, identity=identity)
    _assert_lifestyle_stats_are_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )
    _assert_exports_are_ledger_scoped(client, identity=identity)
    _assert_categories_are_ledger_scoped(client, identity=identity)
    _assert_category_rules_are_ledger_scoped(client, identity=identity)
    _assert_server_settings_are_ledger_scoped(client, identity=identity)
    _assert_confirmed_duplicate_detection_is_ledger_scoped(
        client, identity=identity, owner_id=owner_id, tester_id=tester_id
    )


def test_category_rule_mutations_are_tenant_scoped(client: TestClient, *, identity) -> None:
    owner_rule = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "owner专属",
            "category": "数码",
            "enabled": True,
            "priority": 5,
        },
    )
    assert owner_rule.status_code == 200
    rule_id = int(owner_rule.json()["id"])

    expected_row_version = owner_rule.json()["row_version"]
    patch = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers={**identity.gray_app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "keyword": "tester不该改",
            "category": "购物",
            "priority": 1,
            "expected_row_version": expected_row_version,
        },
    )
    assert patch.status_code == 404
    assert patch.json()["error"] == "rule_not_found"

    delete = client.request(
        "DELETE",
        f"/api/rules/categories/{rule_id}",
        headers={**identity.gray_app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": expected_row_version},
    )
    assert delete.status_code == 404
    assert delete.json()["error"] == "rule_not_found"

    owner_rules = client.get("/api/rules/categories", headers=identity.app_headers).json()
    assert any(
        item["id"] == rule_id and item["keyword"] == "owner专属" for item in owner_rules
    )
