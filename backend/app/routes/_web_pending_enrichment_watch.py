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
]
_COMPLETED_OUTCOMES = frozenset({"updated", "no_result", "not_pending", "conflict"})


@dataclass(frozen=True, slots=True)
class PendingEnrichmentWatch:
    task_public_id: str
    state: PendingEnrichmentState
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class PendingEnrichmentPresentation:
    active_watch: PendingEnrichmentWatch | None
    terminal: PendingEnrichmentWatch | None
    flash_message: str
    flash_type: str


_TERMINAL_FEEDBACK = {
    "updated": ("识别结果已更新，请核对后确认。", "success"),
    "no_result": (
        "识别已完成，但未返回可用字段；可手动补全或打开账单重试识别。",
        "",
    ),
    "failed": (
        "自动识别失败，账单仍安全保留；可打开账单重试识别或手动补全。",
        "error",
    ),
    "cancelled": ("自动识别已取消，账单仍保留在待确认队列。", ""),
    "not_pending": ("账单已离开待确认队列，无需继续等待识别。", ""),
    "conflict": (
        "你后来保存的修改已保留，自动识别没有覆盖这张账单。",
        "",
    ),
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
    one_attempt_seconds = (
        settings.local_llm_timeout_seconds
        + settings.local_llm_queue_timeout_seconds
    )
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
    if outcome not in _COMPLETED_OUTCOMES:
        return "failed"
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
