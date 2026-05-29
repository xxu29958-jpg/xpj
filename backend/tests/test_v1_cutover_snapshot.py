"""ADR-0031 PR-2 cut-over rollback-snapshot tests.

These tests exercise the happy path and the snapshot-failure path of
``v1_migration_service._handler``. They are file_backed_only because
``backup_service.create_pre_v1_backup`` uses SQLite's Online Backup
API against the actual DB file — the default in-memory engine can't
be backed up.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services import (
    app_meta_service,
    backup_service,
    v1_migration_service,
)
from app.services import (
    background_task_service as bgtasks,
)
from app.services.app_meta_service import V1_TARGET_VERSION
from tests._infra.db import reset_db_state

pytestmark = pytest.mark.file_backed_only


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    reset_db_state()


@pytest.fixture(autouse=True)
def _inline_handlers() -> Iterator[None]:
    os.environ["XPJ_BACKGROUND_TASK_INLINE"] = "1"
    try:
        with bgtasks.isolated_registered_handlers_for_testing():
            yield
    finally:
        os.environ.pop("XPJ_BACKGROUND_TASK_INLINE", None)


@pytest.fixture()
def _pretend_v1_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the current binary is already v1.0 so the safety gate
    in :func:`v1_migration_service._handler` does not refuse."""
    monkeypatch.setattr(v1_migration_service, "BACKEND_VERSION", "1.0.0")


def _cleanup_pre_v1_backups() -> None:
    backup_dir = backup_service._backup_dir()  # noqa: SLF001
    for entry in backup_service.list_backups():
        if entry.kind != "pre-v1.0":
            continue
        with contextlib.suppress(FileNotFoundError):
            (backup_dir / entry.file_name).unlink()


# --- happy path -----------------------------------------------------------


def test_v1_cutover_happy_path_creates_pre_v1_snapshot(
    client, _pretend_v1_binary: None
) -> None:
    del client
    # Pre-cut-over: operator must have created a readiness backup via the
    # owner-console preflight flow. Without it, readiness is red and the
    # handler refuses before reaching the snapshot step.
    preflight_backup = backup_service.create_pre_v1_backup()
    v1_migration_service.register()
    try:
        with SessionLocal() as db:
            task = bgtasks.enqueue(
                db,
                task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
                initiator_account_id=None,
                ledger_id=None,
            )
            public_id = task.public_id

        with SessionLocal() as db:
            row = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.public_id == public_id)
                .one()
            )
            assert row.status == "completed", row.error_message
            assert row.progress_total == 3
            assert row.progress_current == 3

            summary = json.loads(row.result_summary_json)
            assert summary["schema_version"] == V1_TARGET_VERSION
            assert summary["schema_min_compatible"] == V1_TARGET_VERSION
            assert summary["rollback_snapshot"].startswith("ticketbox-pre-v1.0-")
            assert summary["rollback_snapshot_size_bytes"] > 0
            # Rollback snapshot must be the one cut-over itself created,
            # NOT the older preflight backup — otherwise we'd roll back
            # to a stale snapshot from before the operator actually
            # committed to v1.0.
            assert summary["rollback_snapshot"] != preflight_backup.file_name

            # The snapshot is actually on disk and classified as pre-v1.0.
            latest = backup_service.latest_backup()
            assert latest is not None
            assert latest.file_name == summary["rollback_snapshot"]
            assert latest.kind == "pre-v1.0"

            # schema_version was committed.
            assert app_meta_service.schema_version(db) == V1_TARGET_VERSION
            assert (
                app_meta_service.schema_min_compatible(db) == V1_TARGET_VERSION
            )
    finally:
        _cleanup_pre_v1_backups()


# --- snapshot failure aborts the whole cut-over ---------------------------


def test_v1_cutover_aborts_when_snapshot_fails(
    client,
    _pretend_v1_binary: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the rollback snapshot can't be created (disk full, integrity
    failure, etc.), the cut-over MUST refuse before writing
    schema_version=1.0 — otherwise v1.0 ships with no way back."""
    del client

    def _boom() -> backup_service.BackupEntry:
        raise AppError(
            "invalid_request",
            "数据库备份校验失败，未写入最终备份文件。",
            status_code=500,
        )

    # Seed the readiness backup BEFORE installing the boom — readiness
    # must pass first so we exercise the snapshot-failure branch, not
    # the readiness-failure branch.
    backup_service.create_pre_v1_backup()
    monkeypatch.setattr(backup_service, "create_pre_v1_backup", _boom)

    v1_migration_service.register()
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
            initiator_account_id=None,
            ledger_id=None,
        )
        public_id = task.public_id

    with SessionLocal() as db:
        row = (
            db.query(BackgroundTask)
            .filter(BackgroundTask.public_id == public_id)
            .one()
        )
        assert row.status == "failed"
        assert "pre-v1.0 rollback snapshot failed" in (row.error_message or "")

        # CRITICAL: schema_version was NOT updated.
        assert app_meta_service.schema_version(db) != V1_TARGET_VERSION
        assert (
            app_meta_service.schema_min_compatible(db) != V1_TARGET_VERSION
        )
