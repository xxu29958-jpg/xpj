from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT, TEST_UPLOAD_DIR


def _upload_png(client: TestClient, *, identity) -> int:
    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def _expense(expense_id: int) -> Expense:
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        db.expunge(expense)
        return expense


def _absolute(relative_path: str) -> str:
    return str((BACKEND_ROOT / relative_path).resolve())


def test_cleanup_rejected_images_keeps_row_and_removes_old_files(client: TestClient, monkeypatch, *, identity) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    rejected = client.post(f"/api/expenses/{expense_id}/reject", headers=identity.app_headers)
    assert rejected.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.rejected_at = now_utc() - timedelta(days=3)
        db.commit()

    expense = _expense(expense_id)
    assert expense.image_path is not None
    image_path = _absolute(expense.image_path)
    assert os.path.isfile(image_path)

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, delete_rejected_after_days=1))

    response = client.post("/api/maintenance/cleanup-rejected", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["scanned"] == 1
    assert payload["deleted_images"] == 1
    assert not os.path.exists(image_path)

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "rejected"

    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.status == "rejected"
        assert row.image_deleted_at is not None


def test_cleanup_rejected_images_keeps_db_retryable_when_unlink_fails(
    client: TestClient,
    monkeypatch, *, identity,
) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    rejected = client.post(f"/api/expenses/{expense_id}/reject", headers=identity.app_headers)
    assert rejected.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.rejected_at = now_utc() - timedelta(days=3)
        db.commit()

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, delete_rejected_after_days=1))

    def fail_unlink(self):
        raise PermissionError("file is locked")

    monkeypatch.setattr(cleanup_service.Path, "unlink", fail_unlink)

    response = client.post("/api/maintenance/cleanup-rejected", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["scanned"] == 1
    assert payload["deleted_images"] == 0

    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.image_deleted_at is None


def test_cleanup_orphans_dry_run_does_not_delete_files(client: TestClient, monkeypatch, *, identity) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    orphan_dir = TEST_UPLOAD_DIR / "owner" / "2026" / "05"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / "orphan.png"
    orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(orphan, (old, old))

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=true", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 0
    assert orphan.exists()


def test_cleanup_orphans_continues_when_single_file_unlink_fails(
    client: TestClient,
    monkeypatch, *, identity,
) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    orphan_dir = TEST_UPLOAD_DIR / "owner" / "2026" / "05"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / "locked-orphan.png"
    orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(orphan, (old, old))

    def fail_unlink(self, *args, **kwargs):
        raise PermissionError("file is locked")

    monkeypatch.setattr(cleanup_service.Path, "unlink", fail_unlink)

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 0
    assert orphan.exists()


def test_cleanup_orphans_deletes_only_unreferenced_old_files(client: TestClient, monkeypatch, *, identity) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    referenced = _expense(expense_id)
    assert referenced.image_path is not None
    referenced_path = _absolute(referenced.image_path)
    assert os.path.isfile(referenced_path)

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    orphan_dir = TEST_UPLOAD_DIR / "owner" / "2026" / "05"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / "orphan-delete.png"
    orphan.write_bytes(PNG_BYTES)
    tester_orphan_dir = TEST_UPLOAD_DIR / "tester_1" / "2026" / "05"
    tester_orphan_dir.mkdir(parents=True, exist_ok=True)
    tester_orphan = tester_orphan_dir / "tester-orphan.png"
    tester_orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(orphan, (old, old))
    os.utime(tester_orphan, (old, old))

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 1
    assert not orphan.exists()
    assert tester_orphan.exists()
    assert os.path.isfile(referenced_path)


def test_cleanup_orphans_treats_windows_style_upload_paths_as_referenced(
    client: TestClient,
    monkeypatch, *, identity,
) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_path is not None
        image_path = _absolute(expense.image_path)
        expense.image_path = expense.image_path.replace("/", "\\")
        if expense.thumbnail_path is not None:
            expense.thumbnail_path = expense.thumbnail_path.replace("/", "\\")
        db.commit()

    assert os.path.isfile(image_path)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(image_path, (old, old))

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["orphan_files"] == 0
    assert payload["deleted_files"] == 0
    assert os.path.isfile(image_path)


def test_cleanup_orphans_scans_default_ledger_legacy_upload_paths(
    client: TestClient,
    monkeypatch, *, identity,
) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    legacy_dir = TEST_UPLOAD_DIR / "2024" / "11"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    referenced = legacy_dir / "referenced.png"
    referenced.write_bytes(PNG_BYTES)
    orphan = legacy_dir / "orphan-legacy.png"
    orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(referenced, (old, old))
    os.utime(orphan, (old, old))

    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                image_path=referenced.relative_to(BACKEND_ROOT).as_posix(),
                image_hash="legacy-cleanup-hash",
                status="pending",
            )
        )
        db.commit()

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 1
    assert referenced.is_file()
    assert not orphan.exists()
