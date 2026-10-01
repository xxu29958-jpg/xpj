"""Real PostgreSQL/file boundaries for inspected orphan disposal (cloud lane)."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Expense
from app.services import cleanup_service, orphan_upload_service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.file_service import resolve_upload_path_for_tenant, upload_reference_for_path
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_UPLOAD_DIR

pytestmark = pytest.mark.real_db


def _old_file(name: str, *, tenant_id="owner") -> Path:
    path = TEST_UPLOAD_DIR / tenant_id / "2026" / "01" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(days=2)).timestamp()
    os.utime(path, (old, old))
    return path


def _manual(client, identity):
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1725,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_retained_accepted_original_survives_current_reference_replacement(client, identity):
    fact = _manual(client, identity)
    old = _old_file("accepted-original.png")
    current = _old_file("current-original.png")
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, fact["id"])
        expense.image_path = upload_reference_for_path(current)
        db.add(ApiIdempotencyKey(tenant_id="owner", idempotency_key="retained-old-original",
            operation="correct_expense", request_fingerprint="f" * 64, status="succeeded",
            resource_type="expense", resource_id=expense.public_id,
            response_body={**fact, "image_path": upload_reference_for_path(old), "image_deleted_at": None},
            completed_at=now_utc(), expires_at=now_utc() + timedelta(days=7)))
        db.commit()
    result = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
    assert result.status_code == 200, result.text
    assert result.json()["deleted_files"] == 0
    assert old.read_bytes() == current.read_bytes() == PNG_BYTES


def test_zero_grace_disposal_cannot_delete_upload_before_its_reference_commits(client, identity, monkeypatch):
    import app.routes._upload_request as uploads

    saved, release = Event(), Event()
    files = []
    original_save = uploads._save_content
    settings = replace(cleanup_service.get_settings(), orphan_upload_grace_hours=0)
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: settings)

    def gate(*args, **kwargs):
        value = original_save(*args, **kwargs)
        files.append(resolve_upload_path_for_tenant(value.relative_path, "owner"))
        saved.set()
        assert release.wait(15), "disposal did not release the isolated upload"
        return value

    monkeypatch.setattr(uploads, "_save_content", gate)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(client.post, identity.upload_url_path, headers=identity.upload_headers,
            files={"file": ("inflight.png", PNG_BYTES, "image/png")})
        try:
            assert saved.wait(15)
            assert files[0].is_file()
            result = client.post("/api/maintenance/cleanup-orphans?dry_run=false", headers=identity.admin_headers)
            assert result.status_code == 200, result.text
            assert result.json()["deleted_files"] == 0
            assert files[0].is_file(), "publication bytes vanished before the accepted receipt"
        finally:
            release.set()
        response = future.result(timeout=15)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        expense = db.get(Expense, response.json()["id"])
        assert resolve_upload_path_for_tenant(expense.image_path, "owner") == files[0]
    assert files[0].read_bytes() == PNG_BYTES


def test_disposal_rechecks_frozen_files_and_retries_only_its_remaining_candidates(client, identity, monkeypatch):
    files = {kind: _old_file(kind + ".png") for kind in ("ordinary", "replaced", "referenced", "locked")}
    other = _old_file("other-ledger.png", tenant_id="tester_1")
    with SessionLocal() as db:
        inspection = orphan_upload_service.inspect_orphans(db, "owner", settings=cleanup_service.get_settings(),
            checkpoint=lambda _value: db.commit())
    assert inspection["candidate_files"] == 4
    candidates = inspection["_candidates"]
    late = _old_file("created-after-inspection.png")
    unchanged_mtime = files["replaced"].stat().st_mtime_ns
    files["replaced"].write_bytes(PNG_BYTES[:-1] + bytes([PNG_BYTES[-1] ^ 1]))
    os.utime(files["replaced"], ns=(unchanged_mtime, unchanged_mtime))
    fact = _manual(client, identity)
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        db.get(Expense, fact["id"]).image_path = upload_reference_for_path(files["referenced"])
        db.commit()
    unlink = Path.unlink

    def fail_one(path, *args, **kwargs):
        if path == files["locked"]:
            raise PermissionError("isolated file in use")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch, SessionLocal() as db:
        patch.setattr(Path, "unlink", fail_one)
        outcomes = orphan_upload_service.dispose_chunk(db, "owner", candidates)
        db.commit()
    assert outcomes == {upload_reference_for_path(path): outcome for path, outcome in (
        (files["ordinary"], "deleted"), (files["replaced"], "changed"),
        (files["referenced"], "referenced"), (files["locked"], "failed"))}
    remaining = [item for item in candidates if outcomes[item["reference"]] in orphan_upload_service.RETRYABLE_OUTCOMES]
    with SessionLocal() as db:
        retried = orphan_upload_service.dispose_chunk(db, "owner", remaining)
        db.commit()
    assert retried == {upload_reference_for_path(files["locked"]): "deleted"}
    assert all(path.is_file() for path in (files["replaced"], files["referenced"], late, other))
    assert not files["ordinary"].exists() and not files["locked"].exists()
