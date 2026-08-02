"""Tests for /owner/backups page."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def test_owner_backups_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    assert "数据库备份" in resp.text


def test_owner_backups_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/owner/backups")
    assert resp.status_code == 403


def test_owner_backups_skip_invalid_dump_files(local_client: TestClient) -> None:
    del local_client
    from app.services import backup_service

    # A file with the right name but garbage bytes is not a readable pg_dump
    # archive — list_backups must filter it out and is_backup_valid must reject
    # it (holds whether or not pg_restore is installed on the runner).
    bogus = backup_service._backup_dir() / "ticketbox-29991231-235959.dump"  # noqa: SLF001
    bogus.write_bytes(b"not a pg_dump archive")
    try:
        assert backup_service.is_backup_valid(bogus.name) is False
        assert bogus.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        bogus.unlink(missing_ok=True)


def test_owner_backups_no_uploads_path_leak(local_client: TestClient) -> None:
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    # The page must not surface the absolute uploads/data path of the host.
    assert "C:\\" not in resp.text
    assert "E:\\" not in resp.text


def test_owner_backups_post_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/owner/backups")
    assert resp.status_code == 403


# ── Backup health (stale-chain visibility, 2026-06 silent 6-day break) ───────


def _stub_latest_backup(monkeypatch: pytest.MonkeyPatch, *, hours_ago: int | None):
    """Point ``backup_service.latest_backup`` at a synthetic entry (or None)."""
    from datetime import timedelta

    from app.services import backup_service
    from app.services.time_service import now_utc

    if hours_ago is None:
        monkeypatch.setattr(backup_service, "latest_backup", lambda: None)
        return None
    entry = backup_service.BackupEntry(
        file_name=f"ticketbox-stub-{hours_ago}h.dump",
        size_bytes=4096,
        created_at=(now_utc() - timedelta(hours=hours_ago)).astimezone(),
        kind="scheduled",
    )
    monkeypatch.setattr(backup_service, "latest_backup", lambda: entry)
    return entry


def test_backup_health_fresh_backup_is_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import backup_service

    entry = _stub_latest_backup(monkeypatch, hours_ago=1)
    health = backup_service.backup_health()
    assert health.latest is entry
    assert health.age_hours == 1
    assert health.stale is False


def test_backup_health_old_backup_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import backup_service

    entry = _stub_latest_backup(monkeypatch, hours_ago=72)
    health = backup_service.backup_health()
    assert health.latest is entry
    assert health.age_hours == 72
    assert health.stale is True


def test_backup_health_missing_backup_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import backup_service

    _stub_latest_backup(monkeypatch, hours_ago=None)
    health = backup_service.backup_health()
    assert health.latest is None
    assert health.age_hours is None
    assert health.stale is True


def test_owner_index_warns_when_backups_stale(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_latest_backup(monkeypatch, hours_ago=72)
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    assert "alert-danger" in resp.text
    assert "最近一次有效备份是 72 小时前" in resp.text
    assert "TicketboxBackup" in resp.text
    assert "查看备份" in resp.text


def test_owner_index_no_warning_when_backup_fresh(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_latest_backup(monkeypatch, hours_ago=1)
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    assert "alert-danger" not in resp.text
    assert "最近一次有效备份是" not in resp.text
    # the service-status grid still shows the fresh age via badge-ok
    assert "最近备份" in resp.text
    assert "1 小时前" in resp.text


def test_owner_backups_page_warns_when_stale(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_latest_backup(monkeypatch, hours_ago=72)
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    assert "alert-danger" in resp.text
    assert "最近一次有效备份是 72 小时前" in resp.text
    assert "TicketboxBackup" in resp.text


def test_owner_backups_page_no_warning_when_fresh(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_latest_backup(monkeypatch, hours_ago=1)
    resp = local_client.get("/owner/backups")
    assert resp.status_code == 200
    assert "alert-danger" not in resp.text


# ── Backup concurrency guard (BUG-2: shared kernel lease) ────────────────────


def _fresh_backup_entry(kind: str):
    from app.services import backup_service
    from app.services.time_service import now_utc

    return backup_service.BackupEntry(
        file_name=f"ticketbox-{kind}-probe.dump",
        size_bytes=1,
        created_at=now_utc().astimezone(),
        kind=kind,
    )


def test_manual_backup_holds_lock_during_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_manual_backup must run the dump *inside* the lock and release after."""
    from app.errors import AppError
    from app.services import backup_service

    observed: dict[str, bool] = {}

    def fake_run_pg_dump(*, prefix: str, kind: str):
        with pytest.raises(AppError) as excinfo:
            backup_service.acquire_backup_job_lock()
        observed["lock_held"] = excinfo.value.error == "backup_in_progress"
        return _fresh_backup_entry(kind)

    monkeypatch.setattr(backup_service, "_run_pg_dump", fake_run_pg_dump)
    backup_service._lock_path().unlink(missing_ok=True)  # noqa: SLF001
    try:
        backup_service.create_manual_backup()
        assert observed["lock_held"] is True
        successor = backup_service.acquire_backup_job_lock()
        successor.release()
    finally:
        backup_service._lock_path().unlink(missing_ok=True)  # noqa: SLF001


def test_manual_backup_skips_when_lock_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh lock held by another job makes a manual backup raise 409, not dump."""
    from app.errors import AppError
    from app.services import backup_service

    def fail_if_called(*, prefix: str, kind: str):
        raise AssertionError("pg_dump must not run while another backup holds the lock")

    monkeypatch.setattr(backup_service, "_run_pg_dump", fail_if_called)
    lock = backup_service._lock_path()  # noqa: SLF001
    lock.parent.mkdir(parents=True, exist_ok=True)
    lease = backup_service.acquire_backup_job_lock()
    try:
        with pytest.raises(AppError) as excinfo:
            backup_service.create_manual_backup()
        assert excinfo.value.error == "backup_in_progress"
        assert excinfo.value.status_code == 409
    finally:
        lease.release()
        lock.unlink(missing_ok=True)


def test_unlocked_persistent_backup_lock_is_reacquired() -> None:
    """A crashed owner's persistent diagnostic file never blocks a new lease."""
    from app.services import backup_service

    lock = backup_service._lock_path()  # noqa: SLF001
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999\ncrashed\n", encoding="utf-8")
    try:
        with backup_service._backup_lock():  # noqa: SLF001
            assert lock.exists()
        assert lock.exists()
    finally:
        lock.unlink(missing_ok=True)


def test_backup_lease_release_is_idempotent_and_never_unlinks_authority(tmp_path: Path) -> None:
    """Release closes ownership while keeping the stable cross-runtime lock path."""
    import shutil
    import subprocess
    import sys

    from app.services import backup_service

    lock = backup_service._lock_path()  # noqa: SLF001
    lock.unlink(missing_ok=True)
    lease = backup_service.acquire_backup_job_lock()
    try:
        if sys.platform == "win32":
            engine = shutil.which("powershell")
            assert engine is not None
            script_path = Path(__file__).resolve().parents[1] / "scripts" / "backup_database.ps1"
            probe = tmp_path / "backup-lock-probe.ps1"
            probe.write_text(
                f"""
. '{str(script_path).replace("'", "''")}'
$lease = Get-BackupLock -Path '{str(lock).replace("'", "''")}'
if ($null -eq $lease) {{ 'BLOCKED'; exit 0 }}
try {{ 'ACQUIRED' }} finally {{ Close-BackupLock -Lease $lease }}
""",
                encoding="utf-8-sig",
            )
            blocked = subprocess.run(  # noqa: S603
                [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(probe)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            assert blocked.returncode == 0, blocked.stderr
            assert blocked.stdout.strip().splitlines()[-1] == "BLOCKED"
        lease.release()
        assert lock.exists()
        lease.release()  # idempotent second release is also harmless
        if sys.platform == "win32":
            acquired = subprocess.run(  # noqa: S603
                [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(probe)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            assert acquired.returncode == 0, acquired.stderr
            assert acquired.stdout.strip().splitlines()[-1] == "ACQUIRED"
        successor = backup_service.acquire_backup_job_lock()
        successor_payload = successor.payload
        try:
            assert lock.exists()
        finally:
            successor.release()
        assert lock.read_bytes() == successor_payload
    finally:
        lease.release()
        lock.unlink(missing_ok=True)


def test_backup_lock_file_invisible_to_listing() -> None:
    """The sentinel must never be mistaken for a backup (it starts with '.')."""
    from app.services import backup_service

    lock = backup_service._lock_path()  # noqa: SLF001
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999\nheld\n", encoding="utf-8")
    try:
        assert backup_service.is_backup_valid(lock.name) is False
        assert lock.name not in {entry.file_name for entry in backup_service.list_backups()}
    finally:
        lock.unlink(missing_ok=True)
