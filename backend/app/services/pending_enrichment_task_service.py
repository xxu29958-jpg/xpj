"""Persistent task owner for upload-driven Pending expense enrichment."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import BackgroundTask
from app.services.expense_service import enrich_pending_expense

PENDING_EXPENSE_ENRICHMENT_TASK_TYPE = "expense_enrichment"

_PROGRESS_MESSAGES = {
    "updated": "识别结果已写入待确认账单。",
    "no_result": "识别完成，未返回可用字段。",
    "not_pending": "账单已不在待确认队列。",
    "conflict": "用户后续修改已保留，识别结果未覆盖账单。",
}


def _task_payload(
    task: BackgroundTask,
    payload: dict[str, Any],
) -> tuple[int, str, str | None, int]:
    expense_id = payload.get("expense_id")
    if isinstance(expense_id, bool) or not isinstance(expense_id, int) or expense_id <= 0:
        raise ValueError("expense_enrichment requires a positive expense_id")

    tenant_id = task.tenant_id
    if not tenant_id or payload.get("tenant_id") != tenant_id:
        raise ValueError("expense_enrichment ledger payload does not match its task owner")

    timezone_name = payload.get("timezone_name")
    if timezone_name is not None and not isinstance(timezone_name, str):
        raise ValueError("expense_enrichment timezone_name must be a string")
    expected_row_version = payload.get("expected_row_version")
    if (
        isinstance(expected_row_version, bool)
        or not isinstance(expected_row_version, int)
        or expected_row_version <= 0
    ):
        raise ValueError("expense_enrichment requires a positive expected_row_version")
    return expense_id, tenant_id, timezone_name or None, expected_row_version


def run_pending_expense_enrichment_task(
    db: Session,
    task: BackgroundTask,
    payload: dict[str, Any],
) -> None:
    """Run one task-scoped enrichment and persist its exact user outcome."""
    from app.services.background_task_service import (
        TaskCancelledError,
        check_cancellation_requested,
    )

    expense_id, tenant_id, timezone_name, expected_row_version = _task_payload(
        task,
        payload,
    )

    def assert_not_cancelled() -> None:
        if check_cancellation_requested(db, task.id):
            raise TaskCancelledError

    assert_not_cancelled()

    result = enrich_pending_expense(
        expense_id,
        tenant_id,
        timezone_name,
        expected_row_version=expected_row_version,
        before_apply=assert_not_cancelled,
        raise_on_failure=True,
    )
    if result.outcome == "failed":
        raise RuntimeError("expense enrichment failed without an exception")

    task.result_summary_json = json.dumps(
        {
            "expense_id": result.expense_id,
            "outcome": result.outcome,
            "row_version": result.row_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    task.progress_current = 1
    task.progress_total = 1
    task.progress_message = _PROGRESS_MESSAGES[result.outcome]
    db.commit()


__all__ = [
    "PENDING_EXPENSE_ENRICHMENT_TASK_TYPE",
    "run_pending_expense_enrichment_task",
]
