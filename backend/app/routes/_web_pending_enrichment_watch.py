"""Validated Web presentation state for one upload enrichment task."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.services import background_task_service
from app.services.background_task_response import task_response_dicts
from app.services.expense_service import fetch_expense_row_version_in_status
from app.services.expense_service._enrichment_receipt import OCR_NOTICE_MESSAGES
from app.services.pending_enrichment_task_service import (
    PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
)

PendingEnrichmentState = Literal[
    "pending",
    "updated",
    "no_result",
    "not_pending",
    "conflict",
    "failed",
    "cancelled",
    "enhancement_failed",
    "provider_conflict",
]
_COMPLETED_OUTCOMES = frozenset({"updated", "no_result", "not_pending", "conflict"})


@dataclass(frozen=True, slots=True)
class PendingEnrichmentWatch:
    task_public_id: str
    state: PendingEnrichmentState
    timeout_ms: int
    source_expense_id: int | None = None


@dataclass(frozen=True, slots=True)
class PendingEnrichmentPresentation:
    active_watch: PendingEnrichmentWatch | None
    terminal: PendingEnrichmentWatch | None
    flash_message: str
    flash_type: str


_TERMINAL_FEEDBACK = {
    **{key: (message, "") for key, message in OCR_NOTICE_MESSAGES.items()},
    "updated": ("识别结果已更新，请核对后确认。", "success"),
    "no_result": (
        "识别完成，当前填写没有变化；请打开账单继续核对。",
        "",
    ),
    "failed": (
        "自动识别失败，账单仍安全保留；可打开账单重试识别或手动补全。",
        "error",
    ),
    "cancelled": ("自动识别已取消，账单仍保留在待确认队列。", ""),
    "not_pending": ("当次识别时账单不在待确认队列；可打开账单继续核对。", ""),
    "conflict": (
        "你后来保存的修改已保留，自动识别没有覆盖这张账单。",
        "",
    ),
}
_RECENT_FAILURE_MESSAGES = {
    "orphaned_after_restart": "服务重启中断了当次识别；请打开原单重试识别或手动补全。",
    "task_submission_failed": "当次识别未能启动；请打开原单重试识别或手动补全。",
    "task_input_unavailable": "原识别输入已不可用；请打开原单核对凭证后重新识别或手动补全。",
}


def _canonical_task_public_id(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError):
        return None
    canonical = str(parsed)
    return canonical if canonical == raw else None


def pending_enrichment_watch_timeout_ms() -> int:
    """Bound browser waiting to the configured two-provider OCR budget."""
    settings = get_settings()
    one_attempt_seconds = settings.local_llm_timeout_seconds + settings.local_llm_queue_timeout_seconds
    total_seconds = math.ceil((one_attempt_seconds * 2) + 15)
    return max(30_000, min(total_seconds * 1_000, 600_000))


def _completed_state(raw_summary: str | None) -> PendingEnrichmentState:
    try:
        summary = json.loads(raw_summary or "")
    except (TypeError, ValueError):
        return "failed"
    if not isinstance(summary, dict):
        return "failed"
    outcome = summary.get("outcome")
    if not isinstance(outcome, str) or outcome not in _COMPLETED_OUTCOMES:
        return "failed"
    notice = summary.get("ocr_notice")
    if outcome in {"updated", "no_result"} and isinstance(notice, str) and notice in OCR_NOTICE_MESSAGES:
        return notice
    return outcome


def resolve_pending_enrichment_watch(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    raw_task_public_id: str | None,
) -> PendingEnrichmentWatch | None:
    task_public_id = _canonical_task_public_id(raw_task_public_id)
    if task_public_id is None:
        return None

    task = background_task_service.get_task(
        db,
        task_public_id,
        account_id=actor_account_id,
        tenant_id=tenant_id,
    )
    if task.task_type != PENDING_EXPENSE_ENRICHMENT_TASK_TYPE:
        return None
    if task.source_expense_id is None or fetch_expense_row_version_in_status(
        db, expense_id=task.source_expense_id, tenant_id=tenant_id, status="pending",
    ) is None:
        return None

    if task.status in {"queued", "running"}:
        state: PendingEnrichmentState = "pending"
    elif task.status == "completed":
        state = _completed_state(task.result_summary_json)
    elif task.status == "cancelled":
        state = "cancelled"
    else:
        state = "failed"
    return PendingEnrichmentWatch(
        task_public_id=task_public_id,
        state=state,
        timeout_ms=pending_enrichment_watch_timeout_ms(),
        source_expense_id=task.source_expense_id,
    )


def resolve_web_pending_enrichment_watch(
    db: Session,
    request: Request,
    *,
    tenant_id: str,
    raw_task_public_id: str | None,
) -> PendingEnrichmentWatch | None:
    """Resolve the soft Web affordance without leaking stale task identity."""
    if _canonical_task_public_id(raw_task_public_id) is None:
        return None
    try:
        actor_account_id = resolve_web_actor_account_id(db, request, tenant_id)
        return resolve_pending_enrichment_watch(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            raw_task_public_id=raw_task_public_id,
        )
    except AppError:
        # A stale, missing, or cross-ledger task id must disappear rather than
        # leak task existence or break the Pending page.
        return None


def pending_enrichment_presentation(
    watch: PendingEnrichmentWatch | None,
    *,
    flash_message: str,
    flash_type: str,
) -> PendingEnrichmentPresentation:
    active = watch if watch and watch.state == "pending" else None
    terminal = watch if watch and watch.state != "pending" else None
    if terminal is not None:
        flash_message, flash_type = _TERMINAL_FEEDBACK[terminal.state]
    elif active is not None and not flash_message:
        flash_message = "小票已收到，正在识别；完成后本页会自动更新。"
    return PendingEnrichmentPresentation(
        active_watch=active,
        terminal=terminal,
        flash_message=flash_message,
        flash_type=flash_type,
    )


def web_pending_enrichment_context(
    db: Session,
    request: Request,
    *,
    tenant_id: str,
    raw_task_public_id: str | None,
    flash_message: str,
    flash_type: str,
) -> dict[str, object]:
    """Project the active watch and this account's recent upload records."""
    watch = resolve_web_pending_enrichment_watch(
        db, request, tenant_id=tenant_id, raw_task_public_id=raw_task_public_id,
    )
    if raw_task_public_id and watch is None:
        flash_message, flash_type = "", ""
    presentation = pending_enrichment_presentation(
        watch,
        flash_message=flash_message,
        flash_type=flash_type,
    )
    try:
        account_id = resolve_web_actor_account_id(db, request, tenant_id)
    except AppError:
        recent_tasks = []
    else:
        recent_tasks = background_task_service.list_recent_tasks(
            db, account_id=account_id, tenant_id=tenant_id, limit=10,
            task_type=PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
        )
    return {
        "enrichment_watch": presentation.active_watch,
        "enrichment_terminal": presentation.terminal,
        "recent_recognition_tasks": [
            {**view, "recognition_state": _completed_state(row.result_summary_json)
                if row.status == "completed" else row.status,
                "recognition_error": _RECENT_FAILURE_MESSAGES.get(row.error_code,
                    "当次自动识别失败；请打开原单核对凭证后重试识别或手动补全。")
                if row.status == "failed" else None}
            for view, row in zip(task_response_dicts(db, recent_tasks, tenant_id=tenant_id), recent_tasks, strict=True)
        ],
        "flash_message": presentation.flash_message,
        "flash_type": presentation.flash_type,
    }
