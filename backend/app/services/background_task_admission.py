"""Bounded PostgreSQL admission for the existing background-task owner."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BackgroundTask, Expense
from app.services.file_service import require_upload_storage, resolve_upload_path_for_tenant
from app.services.time_service import now_utc

_ACTIVE_STATUSES = ("queued", "running")
_ADMISSION_LOCK_LABEL = "ticketbox-background-task-admission"
INTERRUPTED_TASK_CODES = frozenset({"orphaned_after_restart", "task_submission_failed"})
_IMAGE_TASK_TYPES = frozenset({"expense_enrichment", "expense_ocr_retry"})


class BackgroundTaskCapacityFullError(RuntimeError):
    """The persistent pending-work allowance is full; execution slots are separate."""


def stage_queued_task(
    db: Session,
    *,
    task_type: str,
    initiator_account_id: int | None,
    initiator_device_id: int | None,
    ledger_id: str | None,
    progress_total: int | None,
    source_expense_id: int | None = None,
) -> BackgroundTask:
    """Reserve durable pending-work allowance and stage its task row.

    The transaction-scoped PostgreSQL advisory lock makes ``count + insert``
    one admission decision across concurrent request sessions.  The caller
    owns the transaction boundary so a business fact (for receipt uploads, the
    Pending expense) can commit atomically with this row.
    """

    _reserve_active_slot(db, ledger_id=ledger_id, source_expense_id=source_expense_id)
    if task_type == "expense_enrichment" and source_expense_id is not None:
        # Publication precedes this transaction; recheck after concurrent file writes.
        require_upload_storage()
    task = BackgroundTask(
        task_type=task_type,
        tenant_id=ledger_id,
        initiated_by_account_id=initiator_account_id,
        initiated_by_device_id=initiator_device_id,
        progress_total=progress_total,
        source_expense_id=source_expense_id,
    )
    db.add(task)
    # Materialise id/public_id and surface deterministic insert failures before
    # the caller enters the commit-acknowledgement ambiguity window.
    db.flush()
    return task


def readmit_orphaned_task(db: Session, task_id: int) -> BackgroundTask | None:
    """Re-admit a domain-validated original; the caller commits before submitting it."""
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.id == task_id)
        .with_for_update().execution_options(populate_existing=True))
    if task is None:
        return None
    # A concurrent replay may already have committed re-admission, then lost its
    # acknowledgement. Its original queued task still needs a safe worker wakeup.
    if task.status == "queued":
        return task
    if (task.status != "failed" or task.error_code not in INTERRUPTED_TASK_CODES
            or task.cancellation_requested_at is not None):
        return None
    _reserve_active_slot(db, ledger_id=task.tenant_id,
        source_expense_id=task.source_expense_id if task.task_type in _IMAGE_TASK_TYPES else None)
    task.status = "queued"
    task.started_at = task.completed_at = None
    task.last_progress_at = now_utc()
    task.error_code = task.error_message = None
    if task.result_summary_json is None:
        task.progress_current = 0
        task.progress_message = None
    db.flush()
    return task


def _reserve_active_slot(db: Session, *, ledger_id: str | None, source_expense_id: int | None) -> None:
    """One admission lock and capacity decision for both new and recovered tasks."""
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtext(current_database()), hashtext(:lock_label))"
        ),
        {"lock_label": _ADMISSION_LOCK_LABEL},
    )
    settings = get_settings()
    active = list(db.scalars(select(BackgroundTask).where(BackgroundTask.status.in_(_ACTIVE_STATUSES))
        .limit(settings.background_task_max_active)))
    if len(active) >= settings.background_task_max_active:
        raise BackgroundTaskCapacityFullError
    if ledger_id is not None and sum(task.tenant_id == ledger_id for task in active) >= settings.background_task_max_ledger_active:
        raise BackgroundTaskCapacityFullError
    if source_expense_id is None:
        return
    references = {(task.tenant_id, task.source_expense_id) for task in active if task.task_type in _IMAGE_TASK_TYPES}
    references.add((ledger_id, source_expense_id))
    sizes = _pending_image_sizes(db, references)
    if (sum(sizes.values()) > settings.background_task_max_image_bytes or
            sum(size for (tenant, _), size in sizes.items() if tenant == ledger_id) > settings.background_task_max_ledger_image_bytes):
        raise BackgroundTaskCapacityFullError


def _pending_image_sizes(db: Session, references: set[tuple[str | None, int | None]]) -> dict[tuple[str, int], int]:
    """Charge each referenced original once; use the existing protected-file resolver."""
    identifiers = {identifier for _, identifier in references if identifier is not None}
    sizes = {}
    for expense in db.scalars(select(Expense).where(Expense.id.in_(identifiers))):
        key = (expense.tenant_id, expense.id)
        if key not in references or not expense.image_path or expense.image_deleted_at:
            continue
        path = resolve_upload_path_for_tenant(expense.image_path, tenant_id=expense.tenant_id)
        if path is not None:
            try:
                sizes[key] = path.stat().st_size
            except FileNotFoundError:
                # Missing originals consume no storage; their task's source validation still fails.
                continue
    return sizes

__all__ = ["BackgroundTaskCapacityFullError", "readmit_orphaned_task", "stage_queued_task"]
