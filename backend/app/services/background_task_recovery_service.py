"""Bounded recovery and wakeups for the original durable OCR task owner."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import SessionLocal
from app.error_reporting import report_error
from app.models import BackgroundTask
from app.services.background_task_handler_api import OCR_RECOVERY_DELAYS, OCR_TASK_TYPES, schedule_task_recovery
from app.services.time_service import ensure_utc, now_utc

_RECOVERABLE_STATUSES = frozenset({"running", "queued"})
_SCAN_BATCH = 16
logger = logging.getLogger(__name__)


def _should_recover_active_task(task: BackgroundTask, *, grace_seconds: int) -> bool:
    if grace_seconds <= 0:
        return True
    stamp = ensure_utc(task.last_progress_at) or ensure_utc(task.created_at)
    if stamp is None:
        return True
    return stamp <= now_utc() - timedelta(seconds=grace_seconds)


def recover_orphaned_tasks() -> int:
    """Finish applied receipts, retain queued OCR, and bound interrupted inference.

    The default grace is zero seconds, preserving the single-process ADR-0030
    behavior. Cloud/multi-worker deployments can set a positive
    ``BACKGROUND_TASK_ORPHAN_GRACE_SECONDS`` so a newly started worker does not
    immediately fail fresh work still heartbeating in another worker.
    """

    grace_seconds = get_settings().background_task_orphan_grace_seconds
    applied = []
    with SessionLocal() as db:
        active_tasks = list(
            db.scalars(
                select(BackgroundTask).where(
                    BackgroundTask.status.in_(_RECOVERABLE_STATUSES)
                ).with_for_update()
            )
        )
        orphans = [
            task
            for task in active_tasks
            if _should_recover_active_task(task, grace_seconds=grace_seconds)
        ]
        for task in orphans:
            if task.task_type in OCR_TASK_TYPES and task.result_summary_json is not None:
                applied.append(task.id)
                continue
            if task.task_type in OCR_TASK_TYPES and task.cancellation_requested_at is not None:
                from app.services.background_task_handler_api import stage_task_cancellation

                stage_task_cancellation(task)
                continue
            if task.task_type in OCR_TASK_TYPES and task.input_payload_json and task.status == "queued":
                # Losing only the in-memory wakeup is not another inference attempt.
                continue
            task.status = "failed"
            task.completed_at = now_utc()
            task.error_code = "orphaned_after_restart"
            if grace_seconds > 0:
                task.error_message = (
                    "Task heartbeat exceeded BACKGROUND_TASK_ORPHAN_GRACE_SECONDS; "
                    "the worker that owned it is assumed dead."
                )
            else:
                task.error_message = (
                    "Task was running or queued when the backend restarted; "
                    "single-process executor cannot resume across restarts."
                )
            schedule_task_recovery(task)
        if orphans:
            db.commit()
    from app.services import background_task_service

    for task_id in applied:
        background_task_service.complete_applied_task(task_id)
    return len(orphans)


def resume_due_ocr_tasks() -> int:
    """Discover bounded original inputs, then submit through the existing executor."""
    from app.services.background_task_admission import INTERRUPTED_TASK_CODES

    applied = and_(BackgroundTask.status.in_(("queued", "running", "failed")),
                   BackgroundTask.result_summary_json.is_not(None))
    resumable = and_(BackgroundTask.input_payload_json.is_not(None),
        BackgroundTask.cancellation_requested_at.is_(None),
        or_(and_(BackgroundTask.status == "queued", or_(BackgroundTask.recovery_after.is_(None),
                    BackgroundTask.recovery_after <= now_utc())),
            and_(BackgroundTask.status == "failed", BackgroundTask.error_code.in_(INTERRUPTED_TASK_CODES),
                 BackgroundTask.recovery_attempts < len(OCR_RECOVERY_DELAYS))))
    with SessionLocal() as db:
        identifiers = list(db.scalars(select(BackgroundTask.id).where(
            BackgroundTask.task_type.in_(OCR_TASK_TYPES), or_(applied, resumable),
        # Already-admitted work must release capacity before historical failures
        # compete for re-admission; blocked old rows cannot consume the whole scan.
        ).order_by(BackgroundTask.result_summary_json.is_not(None).desc(),
                   (BackgroundTask.status == "queued").desc(), BackgroundTask.created_at,
                   BackgroundTask.id).limit(_SCAN_BATCH)))
    return sum(_wake_original_task(identifier) for identifier in identifiers)


def _wake_original_task(task_id: int) -> bool:
    from app.services import background_task_service
    from app.services.background_task_admission import BackgroundTaskCapacityFullError, readmit_orphaned_task

    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if task is None or task.status not in {"queued", "running", "failed"}:
            return False
        if task.result_summary_json is not None:
            db.rollback()
            background_task_service.complete_applied_task(task_id)
            return True
        if task.status == "running":
            return False
        try:
            payload = json.loads(task.input_payload_json)
            if not isinstance(payload, dict):
                raise ValueError("original task input is not an object")
        except (TypeError, ValueError):
            task.status, task.error_code = "failed", "task_input_unavailable"
            task.error_message = "原识别任务缺少可恢复输入，请从待确认账单重新识别。"
            task.completed_at, task.recovery_after = now_utc(), None
            db.commit()
            return False
        if task.status == "failed":
            try:
                readmit_orphaned_task(db, task_id)
                db.commit()
            except BackgroundTaskCapacityFullError:
                db.rollback()
            return False
        try:
            background_task_service.submit_existing(db, task, payload)
        except background_task_service.BackgroundTaskSubmissionError:
            return False
        return True


@dataclass
class OcrTaskRecovery:
    stop_event: threading.Event
    thread: threading.Thread

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)


def _recovery_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            resume_due_ocr_tasks()
        except SQLAlchemyError as exc:
            # The owned scanner must survive a transient database refusal.
            report_error(logger, "background OCR recovery scan failed", error=exc)
        except Exception as exc:  # Terminal reporting boundary of the owned scanner thread.
            report_error(logger, "background OCR recovery scanner stopped", error=exc)
            stop_event.set()
            return
        stop_event.wait(2)


def start_ocr_task_recovery() -> OcrTaskRecovery | None:
    if os.environ.get("XPJ_BACKGROUND_TASK_INLINE") == "1":
        return None
    stop_event = threading.Event()
    thread = threading.Thread(target=_recovery_loop, args=(stop_event,), name="xpj-ocr-recovery", daemon=True)
    thread.start()
    return OcrTaskRecovery(stop_event, thread)


__all__ = ["recover_orphaned_tasks", "resume_due_ocr_tasks", "start_ocr_task_recovery"]
