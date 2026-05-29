"""ADR-0031 v1.0 cut-over handler.

The cut-over is a one-shot ceremony. All v1.0 schema changes were
already applied to the DB through incremental boot-time migrations in
v0.9.x — there is no separate schema rewrite. See the ADR's "Errata
(2026-05)" section for why the shadow-swap protocol simplified to
"snapshot + restore" once that reality became clear.

PR-2 makes the cut-over rollback-safe by forcing a fresh
``kind=pre-v1.0`` SQLite Online Backup *before* the
``schema_version=1.0`` write commits. The handler does four things:

1. Refuse if the current binary is older than v1.0 (would self-lock).
2. Re-run readiness; refuse if any check is red.
3. Create a pre-v1.0 backup snapshot (the rollback material).
4. Write ``schema_version="1.0"`` / ``schema_min_compatible="1.0"`` /
   ``migration_completed_at=<now>`` to ``app_meta``.

Step 3 is the rollback contract: ``scripts/rollback_to_v0.ps1`` finds
the latest ``pre-v1.0`` backup, checks age < 30 days, and feeds it to
``restore_ticketbox_db.ps1``. If step 4 commits but the operator
later wants to revert, the snapshot at step 3 is the truth they
restore.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BackgroundTask
from app.services import (
    app_meta_service,
    background_task_service,
    backup_service,
    migration_readiness_service,
)
from app.services.app_meta_service import _version_tuple
from app.services.time_service import now_utc
from app.version import BACKEND_VERSION

logger = logging.getLogger(__name__)

V1_MIGRATION_TASK_TYPE = "v1_migration"


def _handler(db: Session, task: BackgroundTask, payload: dict[str, Any]) -> None:
    """Background task handler invoked by ``background_task_service``."""
    # Safety: refuse to set schema_min_compatible=1.0 from a pre-v1.0
    # binary. Doing so would make THIS very process refuse to restart
    # (assert_binary_compatible_with_db would reject 0.9.x < 1.0). Cut
    # over must be triggered from a v1.0+ binary release.
    if _version_tuple(BACKEND_VERSION) < _version_tuple(app_meta_service.V1_TARGET_VERSION):
        raise RuntimeError(
            f"Refuse to cut over: backend binary {BACKEND_VERSION!r} is older "
            f"than v1.0 target {app_meta_service.V1_TARGET_VERSION!r}. Upgrade "
            "the binary first, then re-run cut-over from the v1.0 binary."
        )
    _raise_if_cancelled(db, task)

    report = migration_readiness_service.build_v1_migration_readiness_report(
        create_backup=False
    )
    if not report.ready:
        raise RuntimeError(
            f"v1.0 migration readiness check failed: "
            f"{[c.code for c in report.checks if c.status != 'ok']}"
        )

    background_task_service.update_progress(
        db, task.id, current=1, total=3, message="readiness check passed"
    )
    _raise_if_cancelled(db, task)

    # Rollback material. The schema_version write below is the
    # point-of-no-return for old binaries; this backup is the only
    # way out if v1.0 misbehaves within the 30-day rollback window.
    try:
        snapshot = backup_service.create_pre_v1_backup()
    except AppError as exc:
        raise RuntimeError(
            f"pre-v1.0 rollback snapshot failed: {exc.message}"
        ) from exc

    background_task_service.update_progress(
        db,
        task.id,
        current=2,
        total=3,
        message=f"pre-v1.0 snapshot: {snapshot.file_name}",
    )
    _guard_final_commit_not_cancelled(db, task.id)

    app_meta_service.mark_v1_cut_over_completed(db)

    background_task_service.update_progress(
        db, task.id, current=3, total=3, message="schema_version=1.0 committed"
    )
    task.result_summary_json = json.dumps({
        "schema_version": app_meta_service.V1_TARGET_VERSION,
        "schema_min_compatible": app_meta_service.V1_TARGET_VERSION,
        "rollback_snapshot": snapshot.file_name,
        "rollback_snapshot_size_bytes": snapshot.size_bytes,
    })
    db.commit()


def register() -> None:
    # Production handlers are declared in background_task_registry's runtime
    # catalog. This helper only populates a per-test isolated registry.
    """Idempotent registration — called from FastAPI lifespan startup."""
    if background_task_service.has_active_handler_registry_context():
        background_task_service.register_handler(V1_MIGRATION_TASK_TYPE, _handler)


def _raise_if_cancelled(db: Session, task: BackgroundTask) -> None:
    if background_task_service.check_cancellation_requested(db, task.id):
        raise background_task_service.TaskCancelledError()


def _guard_final_commit_not_cancelled(db: Session, task_id: int) -> None:
    result = db.execute(
        update(BackgroundTask)
        .where(BackgroundTask.id == task_id)
        .where(BackgroundTask.cancellation_requested_at.is_(None))
        .values(last_progress_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        raise background_task_service.TaskCancelledError()
