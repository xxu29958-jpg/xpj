"""ADR-0031 v1.0 cut-over handler.

PR-1 MVP: the cut-over itself is a *one-shot ceremony* that records the
new schema_version in ``app_meta``. All v1.0 schema changes (bill
splits, line item kind, background tasks, items_sum_status,
split_origin_invitation_id) were already applied to the DB through
incremental boot-time migrations in v0.9.x — there is no separate
schema rewrite to do here.

The cut-over does three things:

1. Re-run :func:`migration_readiness_service.build_v1_migration_readiness_report`
   and refuse if readiness is red.
2. Write ``schema_version="1.0"`` / ``schema_min_compatible="1.0"`` /
   ``migration_completed_at=<now>`` to ``app_meta`` (atomic via single
   service helper).
3. Audit-log the event.

PR-2 follow-up (not in scope of this PR):
- Shadow DB file-level copy + atomic rename swap
- 30-day rollback window + rollback_to_v0.ps1 CLI
- /owner/migration confirm-then-switch two-step UI
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services import app_meta_service, background_task_service, migration_readiness_service

logger = logging.getLogger(__name__)

V1_MIGRATION_TASK_TYPE = "v1_migration"


def _handler(db: Session, task: BackgroundTask, payload: dict[str, Any]) -> None:
    """Background task handler invoked by ``background_task_service``."""
    # Safety: refuse to set schema_min_compatible=1.0 from a pre-v1.0
    # binary. Doing so would make THIS very process refuse to restart
    # (assert_binary_compatible_with_db would reject 0.9.x < 1.0). Cut
    # over must be triggered from a v1.0+ binary release.
    from app.services.app_meta_service import _version_tuple
    from app.version import BACKEND_VERSION

    if _version_tuple(BACKEND_VERSION) < _version_tuple(app_meta_service.V1_TARGET_VERSION):
        raise RuntimeError(
            f"Refuse to cut over: backend binary {BACKEND_VERSION!r} is older "
            f"than v1.0 target {app_meta_service.V1_TARGET_VERSION!r}. Upgrade "
            "the binary first, then re-run cut-over from the v1.0 binary."
        )

    report = migration_readiness_service.build_v1_migration_readiness_report(
        create_backup=False
    )
    if not report.ready:
        raise RuntimeError(
            f"v1.0 migration readiness check failed: "
            f"{[c.code for c in report.checks if c.status != 'ok']}"
        )

    background_task_service.update_progress(
        db, task.id, current=1, total=2, message="readiness check passed"
    )

    app_meta_service.mark_v1_cut_over_completed(db)

    background_task_service.update_progress(
        db, task.id, current=2, total=2, message="schema_version=1.0 committed"
    )
    task.result_summary_json = json.dumps({
        "schema_version": app_meta_service.V1_TARGET_VERSION,
        "schema_min_compatible": app_meta_service.V1_TARGET_VERSION,
    })
    db.commit()


def register() -> None:
    """Idempotent registration — called from FastAPI lifespan startup."""
    background_task_service.register_handler(V1_MIGRATION_TASK_TYPE, _handler)
