"""Task fencing and applied receipts inside the expense owner's transaction."""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, BackgroundTask, Device
from app.services.background_task_handler_api import TaskCancelledError
from app.services.ledger_service import get_ledger_for_account
from app.services.permission_service import ROLES_WRITE
from app.services.session_credential_lock import lock_bootstrap_owner_transaction

PROGRESS_MESSAGES = {
    "updated": "识别结果已写入待确认账单。",
    "no_result": "识别完成，未返回可用字段。",
    "not_pending": "账单已不在待确认队列。",
    "conflict": "用户后续修改已保留，识别结果未覆盖账单。",
}


def require_enrichment_actor(db: Session, task_id: int | None, tenant_id: str) -> None:
    if task_id is None:
        return
    # Same global ordering as identity revocation: identity -> expense -> task.
    lock_bootstrap_owner_transaction(db)
    task = db.get(BackgroundTask, task_id)
    if task is None or task.tenant_id != tenant_id or task.initiated_by_account_id is None:
        raise AppError("permission_denied", status_code=403)
    account_id = task.initiated_by_account_id
    if db.scalar(select(Account.id).where(Account.id == account_id, Account.disabled_at.is_(None))) is None:
        raise AppError("permission_denied", status_code=403)
    _, role = get_ledger_for_account(db, account_id=account_id, ledger_id=tenant_id)
    if role not in ROLES_WRITE:
        raise AppError("permission_denied", status_code=403)
    if task.initiated_by_device_id is not None and db.scalar(select(Device.id).where(
        Device.id == task.initiated_by_device_id, Device.account_id == account_id, Device.revoked_at.is_(None),
    )) is None:
        raise AppError("permission_denied", status_code=403)


def lock_enrichment_receipt(db: Session, task_id: int | None, expense_id: int) -> BackgroundTask | None:
    if task_id is None:
        return None
    task = db.get(BackgroundTask, task_id)
    if task is None:
        raise AppError("task_not_found", status_code=404)
    db.refresh(task, with_for_update=True)
    if task.source_expense_id not in {None, expense_id}:
        raise AppError("state_conflict", status_code=409)
    if task.result_summary_json is not None:
        return task
    if task.cancellation_requested_at is not None or task.status == "cancelled":
        raise TaskCancelledError
    if task.status != "running":
        raise AppError("state_conflict", status_code=409)
    return task


def stage_enrichment_receipt(task: BackgroundTask | None, result) -> None:
    if task is None:
        return
    task.result_summary_json = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    task.progress_current = task.progress_total = 1
    task.progress_message = PROGRESS_MESSAGES[result.outcome]
