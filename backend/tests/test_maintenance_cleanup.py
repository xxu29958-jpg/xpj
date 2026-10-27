from __future__ import annotations

import importlib.util
import logging.config
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from api_contract_helpers import reject_expense_api
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Expense, Ledger, LedgerMember
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.identity_service import authenticate_session_token, hash_secret, new_session_token
from app.services.invitation_service import transfer_ledger_owner
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT, TEST_UPLOAD_DIR
from tests.original_test_support import _bill, _financial_snapshot


def _cleanup_owner_case(client, identity, monkeypatch, external_upload_dir, entry):
    from app.services import cleanup_service

    settings = replace(cleanup_service.get_settings(), upload_dir=external_upload_dir,
                       delete_image_after_days=1, delete_rejected_after_days=1, orphan_upload_grace_hours=1)
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: settings)
    expense_id = None
    if entry == "images":
        expense_id, _saved, original = _bill(client, identity)
    elif entry == "rejected":
        from app.services.file_service import resolve_upload_path_for_tenant

        expense_id = _upload_png(client, identity=identity)
        assert reject_expense_api(client, expense_id, headers=identity.app_headers).status_code == 200
        original = resolve_upload_path_for_tenant(_expense(expense_id).image_path, "owner")
    else:
        original = external_upload_dir / "owner" / "2026" / "01" / "old-orphan.png"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(PNG_BYTES)
        old = (now_utc() - timedelta(days=3)).timestamp()
        os.utime(original, (old, old))
    assert original.is_file()
    with SessionLocal() as db:
        if expense_id is not None:
            authorize_currency_metadata_write(db)
            row = db.get(Expense, expense_id)
            setattr(row, "confirmed_at" if entry == "images" else "rejected_at", now_utc() - timedelta(days=3))
        owner_id = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        target = Account(display_name="next cleanup owner")
        db.add(target)
        db.flush()
        member = LedgerMember(ledger_id="owner", account_id=target.id, role="member")
        device = Device(account_id=target.id, device_name="cleanup admin", platform="test")
        db.add_all([member, device])
        db.flush()
        target_token = new_session_token()
        db.add(AuthToken(token_hash=hash_secret(target_token), account_id=target.id,
                         device_id=device.id, ledger_id="owner", scope="admin"))
        db.commit()
        member_id = member.id
    path = f"/api/maintenance/cleanup-{entry}" + ("?dry_run=false" if entry == "orphans" else "")
    return SimpleNamespace(original=original, expense_id=expense_id, owner_id=owner_id,
                           member_id=member_id, path=path, target_token=target_token)


def _transfer_cleanup_owner(case):
    with SessionLocal() as db:
        transfer_ledger_owner(db, ledger_id="owner", member_id=case.member_id,
                              requester_account_id=case.owner_id, auth=None)


@pytest.mark.parametrize("entry", ["images", "rejected", "orphans"])
def test_cleanup_after_owner_transfer_refuses_live_former_owner_token(
    client, identity, monkeypatch, external_upload_dir, entry,
):
    case = _cleanup_owner_case(client, identity, monkeypatch, external_upload_dir, entry)
    _transfer_cleanup_owner(case)
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.admin_token, {"admin"})
        assert auth.role == "member"
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.admin_token)))
        assert token.revoked_at is None

    response = client.post(case.path, headers=identity.admin_headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"] == "permission_denied"
    assert case.original.is_file()
    if case.expense_id is not None:
        assert _expense(case.expense_id).image_deleted_at is None
    accepted = client.post(case.path, headers={"Authorization": f"Bearer {case.target_token}"})
    assert accepted.status_code == 200, accepted.text
    assert not case.original.exists()


@pytest.mark.real_db
@pytest.mark.parametrize(("entry", "deleted_before_transfer"), [
    ("images", 0), ("rejected", 0), ("orphans", 0), ("orphans", 1),
])
def test_cleanup_rechecks_owner_after_commit_before_remaining_deletion(
    client, identity, monkeypatch, external_upload_dir, entry, deleted_before_transfer,
):
    from app.routes import maintenance
    from app.services import orphan_upload_service

    case = _cleanup_owner_case(client, identity, monkeypatch, external_upload_dir, entry)
    originals = [case.original]
    if deleted_before_transfer:
        second = case.original.with_name("second-orphan.png")
        second.write_bytes(PNG_BYTES)
        old = case.original.stat().st_mtime
        os.utime(second, (old, old))
        originals.append(second)
        monkeypatch.setattr(orphan_upload_service, "CHUNK_SIZE", 1)
    before = _financial_snapshot(case.expense_id) if case.expense_id else None
    paused, proceed = Event(), Event()
    command_name = {"images": "cleanup_confirmed_images", "rejected": "cleanup_rejected_images",
                    "orphans": "cleanup_orphan_uploads"}[entry]
    command = getattr(maintenance, command_name)

    def after_commit(_db):
        if not paused.is_set() and sum(not item.exists() for item in originals) == deleted_before_transfer:
            paused.set()
            assert proceed.wait(timeout=10)

    def observed_command(db, *args, **kwargs):
        event.listen(db, "after_commit", after_commit)
        try:
            return command(db, *args, **kwargs)
        finally:
            event.remove(db, "after_commit", after_commit)

    monkeypatch.setattr(maintenance, command_name, observed_command)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(client.post, case.path, headers=identity.admin_headers)
        try:
            assert paused.wait(timeout=10)
            _transfer_cleanup_owner(case)
        finally:
            proceed.set()
        response = request.result(timeout=10)
    assert response.status_code == 403, response.text
    assert response.json()["error"] == "permission_denied"
    assert sum(not item.exists() for item in originals) == deleted_before_transfer
    if case.expense_id is not None:
        expense = _expense(case.expense_id)
        assert expense.attachment_cleanup_request is not None
        assert expense.image_deleted_at is None
        assert _financial_snapshot(case.expense_id) == before

    accepted = client.post(case.path, headers={"Authorization": f"Bearer {case.target_token}"})
    assert accepted.status_code == 200, accepted.text
    assert all(not item.exists() for item in originals)
    if case.expense_id is not None:
        assert _expense(case.expense_id).attachment_cleanup_request is None
        assert _financial_snapshot(case.expense_id) == before


@pytest.mark.real_db
@pytest.mark.parametrize("entry", ["images", "orphans"])
def test_cleanup_holds_owner_authority_until_file_deletion_commits(
    client, identity, monkeypatch, external_upload_dir, entry,
):
    case = _cleanup_owner_case(client, identity, monkeypatch, external_upload_dir, entry)
    paused, proceed = Event(), Event()
    unlink = Path.unlink

    def paused_unlink(path, *args, **kwargs):
        if path == case.original:
            paused.set()
            assert proceed.wait(timeout=10)
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", paused_unlink)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(client.post, case.path, headers=identity.admin_headers)
        try:
            assert paused.wait(timeout=10)
            with SessionLocal() as db:
                db.execute(text("SET LOCAL lock_timeout = '150ms'"))
                with pytest.raises(OperationalError) as caught:
                    transfer_ledger_owner(db, ledger_id="owner", member_id=case.member_id,
                                          requester_account_id=case.owner_id, auth=None)
                assert caught.value.orig.sqlstate == "55P03"
                db.rollback()
            assert case.original.is_file()
        finally:
            proceed.set()
        response = request.result(timeout=10)
    assert response.status_code == 200, response.text
    assert not case.original.exists()
    _transfer_cleanup_owner(case)


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


def _load_packaging_launch():
    launch_path = BACKEND_ROOT / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location(
        "ticketbox_cleanup_test_launch",
        launch_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_rejected_images_keeps_row_and_removes_old_files(client: TestClient, monkeypatch, *, identity) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
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
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
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

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    response = client.post("/api/maintenance/cleanup-rejected", headers=identity.admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["scanned"] == 1
    assert payload["deleted_images"] == 0

    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.image_deleted_at is None


def test_cleanup_rejected_images_does_not_disguise_missing_bytes_as_deleted(
    client: TestClient,
    monkeypatch,
    caplog,
    tmp_path,
    *,
    identity,
) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    rejected = reject_expense_api(client, expense_id, headers=identity.app_headers)
    assert rejected.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None and expense.image_path is not None
        expense.rejected_at = now_utc() - timedelta(days=3)
        missing_reference = expense.image_path
        missing_tenant_id = expense.tenant_id
        missing_path = _absolute(missing_reference)
        db.commit()

    os.unlink(missing_path)
    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, delete_rejected_after_days=1),
    )

    response = client.post(
        "/api/maintenance/cleanup-rejected",
        headers=identity.admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["deleted_images"] == 0
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        assert row.image_deleted_at is None
    integrity_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "upload_integrity_missing"
    ]
    assert len(integrity_records) == 1
    record = integrity_records[0]
    assert re.fullmatch(r"[0-9a-f]{16}", record.reference_digest)

    launch = _load_packaging_launch()
    config = launch._build_log_config(tmp_path / "logs", console=False)
    formatter = logging.config.DictConfigurator(config).configure_formatter(config["formatters"]["plain"])
    formatted = formatter.format(record)
    assert "event=upload_integrity_missing" in formatted
    assert f"reference_digest={record.reference_digest}" in formatted
    assert missing_tenant_id not in formatted
    assert missing_reference not in formatted
    assert missing_path not in formatted


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

    monkeypatch.setattr(Path, "unlink", fail_unlink)

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


def test_cleanup_orphans_reclaims_file_reappearing_after_deletion_marker(
    client: TestClient,
    monkeypatch,
    *,
    identity,
) -> None:
    from app.services import cleanup_service

    expense_id = _upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None and expense.image_path is not None
        image_path = _absolute(expense.image_path)
        authorize_currency_metadata_write(db)
        expense.image_deleted_at = now_utc()
        db.commit()

    old = (now_utc() - timedelta(hours=3)).timestamp()
    os.utime(image_path, (old, old))
    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, orphan_upload_grace_hours=1),
    )

    response = client.post(
        "/api/maintenance/cleanup-orphans?dry_run=false",
        headers=identity.admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["orphan_files"] == 1
    assert response.json()["deleted_files"] == 1
    assert not os.path.exists(image_path)


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
