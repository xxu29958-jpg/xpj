"""Local Owner inspection and disposal through the existing durable task owner."""

import json
from contextlib import suppress
from dataclasses import replace
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Account, BackgroundTask
from app.services import background_task_service as tasks
from app.services.background_task_handler_api import TaskCancelledError, check_cancellation_requested, update_progress
from app.services.ledger_service import list_managed_ledgers_for_account
from app.services.orphan_task_results import DISPOSE_ORPHANS, INSPECT_ORPHANS, ORPHAN_TASK_TYPES
from app.services.orphan_upload_service import (
    CHUNK_SIZE,
    RETRYABLE_OUTCOMES,
    disposal_summary,
    dispose_chunk,
    inspect_orphans,
)
from app.services.owner_console_service._common import get_owner_account_id
from app.services.session_credential_lock import lock_bootstrap_owner_transaction


def maintenance_ledgers(db: Session):
    account_id = get_owner_account_id(db)
    active = db.scalar(select(Account.id).where(Account.id == account_id, Account.disabled_at.is_(None)))
    return list_managed_ledgers_for_account(db, account_id=active, include_archived=True) if active is not None else []


def authorize_local_ledger(db: Session, ledger_id: str, *, mutation: bool = False) -> int:
    if mutation:
        lock_bootstrap_owner_transaction(db)
    account_id = get_owner_account_id(db)
    active = db.scalar(select(Account.id).where(Account.id == account_id, Account.disabled_at.is_(None)))
    if active is None or ledger_id not in {row.ledger_id for row in list_managed_ledgers_for_account(
            db, account_id=active, include_archived=True)}:
        raise AppError("ledger_forbidden", status_code=403)
    return active


def read_maintenance_task(db: Session, public_id: str, *, ledger_id: str) -> BackgroundTask:
    account_id = authorize_local_ledger(db, ledger_id)
    task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id,
        BackgroundTask.tenant_id == ledger_id, BackgroundTask.initiated_by_account_id == account_id,
        BackgroundTask.task_type.in_(ORPHAN_TASK_TYPES)))
    if task is None:
        raise AppError("task_not_found", status_code=404)
    return task


def list_maintenance_tasks(db: Session, *, ledger_id: str, offset: int, limit: int) -> list[BackgroundTask]:
    account_id = authorize_local_ledger(db, ledger_id)
    return list(db.scalars(select(BackgroundTask).where(BackgroundTask.tenant_id == ledger_id,
        BackgroundTask.initiated_by_account_id == account_id, BackgroundTask.task_type.in_(ORPHAN_TASK_TYPES))
        .order_by(BackgroundTask.id.desc()).offset(offset).limit(limit)))


def _input(task: BackgroundTask) -> dict:
    return json.loads(task.input_payload_json or "{}")


def task_result(task: BackgroundTask) -> dict:
    return json.loads(task.result_summary_json or "{}")


def task_origin(task: BackgroundTask) -> dict:
    return {key: value for key, value in _input(task).items() if key in {"inspection_id", "continued_from"}}


def disposal_for_inspection(db: Session, inspection: BackgroundTask) -> BackgroundTask | None:
    return db.scalar(select(BackgroundTask).where(
        BackgroundTask.public_id == str(uuid5(UUID(inspection.public_id), "dispose")),
        BackgroundTask.tenant_id == inspection.tenant_id,
        BackgroundTask.initiated_by_account_id == inspection.initiated_by_account_id,
        BackgroundTask.task_type == DISPOSE_ORPHANS))


def _start(db: Session, *, ledger_id: str, public_id: str, task_type: str, payload: dict) -> BackgroundTask:
    account_id = authorize_local_ledger(db, ledger_id, mutation=True)
    existing = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == public_id))
    if existing is not None:
        if (existing.tenant_id, existing.initiated_by_account_id, existing.task_type) != (ledger_id, account_id, task_type):
            raise AppError("task_not_found", status_code=404)
        db.commit()
        return existing
    prepared = tasks.prepare_enqueue(db, task_type=task_type, initiator_account_id=account_id,
        ledger_id=ledger_id, payload=payload, progress_total=len(payload["candidates"]) if "candidates" in payload else None)
    prepared.task.public_id = public_id
    prepared.task.input_payload_json = json.dumps(payload, separators=(",", ":"))
    prepared = replace(prepared, task_public_id=public_id)
    db.commit()
    # Keep the original task address and its durable refused-execution state.
    with suppress(tasks.BackgroundTaskSubmissionError):
        tasks.submit_committed(db, prepared)
    db.expire_all()
    return db.get(BackgroundTask, prepared.task_id)


def start_inspection(db: Session, *, ledger_id: str, client_ref: UUID) -> BackgroundTask:
    return _start(db, ledger_id=ledger_id, public_id=str(client_ref), task_type=INSPECT_ORPHANS,
        payload={"version": 1, "grace_hours": max(get_settings().orphan_upload_grace_hours, 0)})


def start_disposal(db: Session, *, ledger_id: str, inspection_id: str) -> BackgroundTask:
    authorize_local_ledger(db, ledger_id, mutation=True)
    inspection = read_maintenance_task(db, inspection_id, ledger_id=ledger_id)
    if inspection.task_type != INSPECT_ORPHANS or inspection.status != "completed":
        raise AppError("invalid_request", "请先完成检查，再明确处置本次候选文件。", status_code=409)
    candidates = task_result(inspection).get("_candidates", [])
    if not candidates:
        raise AppError("invalid_request", "这次检查没有可处置的文件。", status_code=409)
    return _start(db, ledger_id=ledger_id, public_id=str(uuid5(UUID(inspection_id), "dispose")), task_type=DISPOSE_ORPHANS,
        payload={"version": 1, "inspection_id": inspection_id, "candidates": candidates})


def remaining_candidates(task: BackgroundTask) -> list[dict]:
    outcomes = task_result(task).get("_outcomes", {})
    return [item for item in _input(task).get("candidates", [])
        if outcomes.get(item["reference"]) is None or outcomes[item["reference"]] in RETRYABLE_OUTCOMES]


def continue_maintenance(db: Session, *, ledger_id: str, public_id: str) -> BackgroundTask:
    authorize_local_ledger(db, ledger_id, mutation=True)
    original = read_maintenance_task(db, public_id, ledger_id=ledger_id)
    if original.status in {"queued", "running"}:
        db.commit()
        return original
    payload = {**_input(original), "continued_from": original.public_id}
    if original.task_type == DISPOSE_ORPHANS:
        payload["candidates"] = remaining_candidates(original)
        if not payload["candidates"]:
            raise AppError("invalid_request", "本次处置已没有待继续的文件。", status_code=409)
    elif original.status == "completed":
        raise AppError("invalid_request", "检查已完成；需要新结果时请重新检查。", status_code=409)
    return _start(db, ledger_id=ledger_id, public_id=str(uuid5(UUID(public_id), "continue")),
        task_type=original.task_type, payload=payload)


def cancel_maintenance(db: Session, *, ledger_id: str, public_id: str) -> BackgroundTask:
    account_id = authorize_local_ledger(db, ledger_id, mutation=True)
    task = read_maintenance_task(db, public_id, ledger_id=ledger_id)
    return tasks.request_cancellation(db, task.public_id, account_id=account_id, tenant_id=ledger_id)


def _authorize_worker(db: Session, task: BackgroundTask) -> None:
    if authorize_local_ledger(db, task.tenant_id, mutation=True) != task.initiated_by_account_id:
        raise AppError("ledger_forbidden", status_code=403)


def _checkpoint(db: Session, task: BackgroundTask, result: dict, *, current: int, total: int | None = None) -> None:
    task.result_summary_json = json.dumps(result, separators=(",", ":"))
    message = "检查文件引用"
    if task.task_type == DISPOSE_ORPHANS:
        remaining = result["candidate_files"] - result["processed_files"] + result["busy_files"] + result["failed_files"]
        message = f"已删除 {result['deleted_files']} 个文件，仍有 {remaining} 个待处理。"
    update_progress(db, task.id, current=current, total=total, message=message)
    if check_cancellation_requested(db, task.id):
        raise TaskCancelledError
    _authorize_worker(db, task)


def run_orphan_inspection(db: Session, task: BackgroundTask, _payload: dict) -> None:
    _authorize_worker(db, task)
    settings = replace(get_settings(), orphan_upload_grace_hours=_input(task)["grace_hours"])
    inspect_orphans(db, task.tenant_id, settings=settings, checkpoint=lambda result:
        _checkpoint(db, task, result, current=result["scanned_files"]))


def run_orphan_disposal(db: Session, task: BackgroundTask, _payload: dict) -> None:
    _authorize_worker(db, task)
    candidates = _input(task)["candidates"]
    outcomes = task_result(task).get("_outcomes", {})
    for start in range(0, len(candidates), CHUNK_SIZE):
        if check_cancellation_requested(db, task.id):
            raise TaskCancelledError
        batch = [item for item in candidates[start:start + CHUNK_SIZE] if item["reference"] not in outcomes]
        outcomes.update(dispose_chunk(db, task.tenant_id, batch))
        result = {"inspection_id": _input(task)["inspection_id"], **disposal_summary(candidates, outcomes)}
        _checkpoint(db, task, result, current=len(outcomes), total=len(candidates))
