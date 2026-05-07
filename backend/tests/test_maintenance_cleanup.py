from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import BACKEND_ROOT, PNG_BYTES, TEST_UPLOAD_DIR, admin_headers, app_headers, upload_headers
from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc


def _upload_png(client: TestClient) -> int:
    response = client.post(
        "/api/upload-screenshot",
        headers=upload_headers(),
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


def test_cleanup_rejected_images_keeps_row_and_removes_old_files(client: TestClient, monkeypatch) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client)
    rejected = client.post(f"/api/expenses/{expense_id}/reject", headers=app_headers())
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

    response = client.post("/api/maintenance/cleanup-rejected", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["scanned"] == 1
    assert payload["deleted_images"] == 1
    assert not os.path.exists(image_path)

    detail = client.get(f"/api/expenses/{expense_id}", headers=app_headers())
    assert detail.status_code == 200
    assert detail.json()["status"] == "rejected"

    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.status == "rejected"
        assert row.image_deleted_at is not None


def test_cleanup_orphans_dry_run_does_not_delete_files(client: TestClient, monkeypatch) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    orphan_dir = TEST_UPLOAD_DIR / "2026" / "05"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / "orphan.png"
    orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(orphan, (old, old))

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=true", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 0
    assert orphan.exists()


def test_cleanup_orphans_deletes_only_unreferenced_old_files(client: TestClient, monkeypatch) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client)
    referenced = _expense(expense_id)
    assert referenced.image_path is not None
    referenced_path = _absolute(referenced.image_path)
    assert os.path.isfile(referenced_path)

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: replace(settings, orphan_upload_grace_hours=1))

    orphan_dir = TEST_UPLOAD_DIR / "2026" / "05"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan = orphan_dir / "orphan-delete.png"
    orphan.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(orphan, (old, old))

    response = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["orphan_files"] == 1
    assert payload["deleted_files"] == 1
    assert not orphan.exists()
    assert os.path.isfile(referenced_path)
