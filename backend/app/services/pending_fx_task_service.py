"""Durable continuation of one pending bill's original currency conversion."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import asdict
from xml.etree.ElementTree import ParseError

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, BackgroundTask, Device, Expense
from app.services import background_task_service
from app.services.background_task_admission import BackgroundTaskCapacityFullError, readmit_orphaned_task
from app.services.background_task_handler_api import (
    TaskCancelledError,
    check_cancellation_requested,
    mark_failed,
    retire_obsolete_task,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.exchange_rate_service import resolve_payload_rate
from app.services.expense_query import resolve_expense
from app.services.expense_service._fx import (
    PendingFxInput,
    PendingFxResult,
    apply_pending_fx,
    check_pending_fx,
    fetch_pending_fx_reference,
)
from app.services.fx_rate_provider import FxFetchError
from app.services.ledger_service import get_ledger_for_account
from app.services.permission_service import ROLES_WRITE
from app.services.session_credential_lock import lock_bootstrap_owner_transaction

PENDING_EXPENSE_FX_TASK_TYPE = "expense_fx"
_REFILL_BATCH_SIZE = 32

_PROGRESS_MESSAGES = {
    "updated": "汇率已补齐，请核对换算金额后确认账单。",
    "no_result": "账单已有可用汇率，请回到账单核对。",
    "not_pending": "账单已不在待确认队列。",
    "conflict": "账单后续修改已保留，请核对当前账单后再继续。",
}
_FAILURE_MESSAGE = "暂未完成汇率补齐，原账单已保留；可重试或填写本笔汇率。"


class PendingFxTaskError(RuntimeError):
    """Safe failure if even the task's error publication cannot be stored."""


def latest_pending_expense_fx_tasks(
    db: Session, *, tenant_id: str, expense_ids: list[int],
) -> dict[int, BackgroundTask]:
    if not expense_ids:
        return {}
    tasks = db.scalars(select(BackgroundTask).where(
        BackgroundTask.tenant_id == tenant_id,
        BackgroundTask.task_type == PENDING_EXPENSE_FX_TASK_TYPE,
        BackgroundTask.source_expense_id.in_(expense_ids),
    ).distinct(BackgroundTask.source_expense_id).order_by(
        BackgroundTask.source_expense_id, BackgroundTask.id.desc(),
    ).execution_options(populate_existing=True))
    return {task.source_expense_id: task for task in tasks}


def _original_input(task: BackgroundTask) -> PendingFxInput:
    original = PendingFxInput.model_validate_json(task.input_payload_json or "null")
    if (task.task_type != PENDING_EXPENSE_FX_TASK_TYPE or task.tenant_id != original.tenant_id
            or task.source_expense_id != original.expense_id):
        raise ValueError("Original FX input does not match its task")
    return original


def _current_input(expense: Expense) -> PendingFxInput | None:
    try:
        return PendingFxInput.from_expense(expense)
    except ValueError:
        return None


def current_pending_expense_fx_tasks(
    db: Session, *, tenant_id: str, expenses: list[Expense],
) -> dict[int, BackgroundTask]:
    """Project only tasks for these current revisions; history remains in the task owner."""
    current = {expense.id: expense for expense in expenses if expense.tenant_id == tenant_id}
    latest = latest_pending_expense_fx_tasks(db, tenant_id=tenant_id, expense_ids=list(current))
    return {expense_id: task for expense_id, task in latest.items()
        if _task_matches_expense(task, current[expense_id])}


def _task_matches_expense(task: BackgroundTask, expense: Expense) -> bool:
    try:
        original = _original_input(task)
        return original.expected_row_version == expense.row_version or _matches_committed_result(
            task, original, expense.row_version)
    except ValueError:
        return False


def _prepare_input(
    db: Session, original: PendingFxInput, *, account_id: int | None, device_id: int | None,
) -> background_task_service.PreparedBackgroundTask:
    prepared = background_task_service.prepare_enqueue(db, task_type=PENDING_EXPENSE_FX_TASK_TYPE,
        initiator_account_id=account_id, initiator_device_id=device_id, ledger_id=original.tenant_id,
        payload=original.model_dump(mode="json"), progress_total=1)
    prepared.task.input_payload_json = original.model_dump_json()
    prepared.task.source_expense_id = original.expense_id
    return prepared


def _retire_obsolete_fx_tasks(
    db: Session, *, tenant_id: str, expense_id: int, current: PendingFxInput | None,
) -> None:
    # The caller already owns the Expense lock. Keep the same order for all
    # paths: Expense, old task rows by id, then the existing admission lock.
    tasks = db.scalars(select(BackgroundTask).where(
        BackgroundTask.tenant_id == tenant_id,
        BackgroundTask.source_expense_id == expense_id,
        BackgroundTask.task_type == PENDING_EXPENSE_FX_TASK_TYPE,
        BackgroundTask.status.in_(("queued", "running")),
    ).order_by(BackgroundTask.id))
    for task in tasks:
        try:
            original = _original_input(task)
        except ValueError:
            # Invalid durable inputs remain the task handler's explicit failure.
            continue
        if original != current:
            retire_obsolete_task(db, task)
    db.flush()


def prepare_pending_expense_fx(
    db: Session, *, expense: Expense, initiator_account_id: int | None, initiator_device_id: int | None,
) -> background_task_service.PreparedBackgroundTask | None:
    """Stage alongside an accepted bill; capacity refusal must not discard that bill."""
    try:
        return _prepare_automatic_fx(db, expense=expense,
            initiator_account_id=initiator_account_id, initiator_device_id=initiator_device_id)
    except BackgroundTaskCapacityFullError:
        return None


def _prepare_automatic_fx(
    db: Session, *, expense: Expense, initiator_account_id: int | None, initiator_device_id: int | None,
) -> background_task_service.PreparedBackgroundTask | None:
    # Materialize staged SQL version increments before interpreting the input.
    db.flush()
    if _current_input(expense) is None and expense.row_version <= 1:
        # A new inapplicable bill cannot have a superseded positive-version FX input.
        return None
    current = resolve_expense(db, expense.tenant_id, expense.id, for_update=True)
    if current is None:
        return None
    db.refresh(current)
    original = _current_input(current)
    _retire_obsolete_fx_tasks(db, tenant_id=current.tenant_id, expense_id=current.id, current=original)
    if not get_settings().fx_rate_auto_sync_enabled or original is None:
        return None
    latest = latest_pending_expense_fx_tasks(db, tenant_id=current.tenant_id, expense_ids=[current.id]).get(current.id)
    try:
        if latest is not None and _original_input(latest) == original:
            return None
        return _prepare_input(db, original, account_id=initiator_account_id, device_id=initiator_device_id)
    except ValueError:
        return None


def submit_pending_expense_fx(db: Session, prepared: background_task_service.PreparedBackgroundTask) -> str:
    with suppress(background_task_service.BackgroundTaskSubmissionError):
        background_task_service.submit_committed(db, prepared)
    return prepared.task_public_id


def refill_pending_expense_fx(*, after_id: int = 0) -> int:
    """Admit saved bills left outside capacity; return the next scan's in-memory cursor."""
    if not get_settings().fx_rate_auto_sync_enabled:
        return 0
    with SessionLocal() as db:
        expense_ids = list(db.scalars(select(Expense.id).where(
            Expense.id > after_id, Expense.status == "pending", Expense.fx_status == "pending",
            Expense.original_amount_minor.is_not(None), Expense.exchange_rate_date.is_not(None),
            Expense.home_currency_code != Expense.original_currency_code,
        ).order_by(Expense.id).limit(_REFILL_BATCH_SIZE)))
    for expense_id in expense_ids:
        try:
            # Never carry the admission lock into the next Expense transaction.
            with SessionLocal() as db:
                expense = db.get(Expense, expense_id)
                if expense is not None:
                    prepared = _prepare_automatic_fx(db, expense=expense,
                        initiator_account_id=None, initiator_device_id=None)
                    db.commit()
                    if prepared is not None:
                        submit_pending_expense_fx(db, prepared)
        except BackgroundTaskCapacityFullError:
            # Keep the blocked bill first, including when later bills keep arriving.
            return after_id
        after_id = expense_id
    return after_id if len(expense_ids) == _REFILL_BATCH_SIZE else 0


def _can_resume(task: BackgroundTask) -> bool:
    return task.status in {"queued", "running"} or (
        task.status == "failed" and task.error_code == "orphaned_after_restart"
        and task.cancellation_requested_at is None
    )


def _resume_task(db: Session, task: BackgroundTask, original: PendingFxInput) -> BackgroundTask:
    if task.status == "failed":
        recovered = readmit_orphaned_task(db, task.id)
        if recovered is not None:
            task = recovered
    # Release both the bill lock and admission before waking a worker.
    db.commit()
    if task.status == "queued":
        with suppress(background_task_service.BackgroundTaskSubmissionError):
            background_task_service.submit_existing(db, task, original.model_dump(mode="json"))
    return task


def _matches_committed_result(task: BackgroundTask, original: PendingFxInput, expected_row_version: int) -> bool:
    if task.result_summary_json is None:
        return False
    result = json.loads(task.result_summary_json)
    return (isinstance(result, dict) and result.get("expense_id") == original.expense_id
        and (expected_row_version == original.expected_row_version or (
            result.get("outcome") in {"updated", "no_result"} and expected_row_version == result.get("row_version"))))


def _require_request_actor(db: Session, *, tenant_id: str, account_id: int, device_id: int | None) -> None:
    # The HTTP adapters admit their real credential scope. The command rechecks
    # the active actor/membership under the existing identity lifecycle lock.
    lock_bootstrap_owner_transaction(db)
    account = db.scalar(select(Account.id).where(Account.id == account_id, Account.disabled_at.is_(None)))
    if account is None:
        raise AppError("invalid_token", status_code=401)
    _, role = get_ledger_for_account(db, account_id=account_id, ledger_id=tenant_id)
    if role not in ROLES_WRITE:
        raise AppError("permission_denied", status_code=403)
    if device_id is not None and db.scalar(select(Device.id).where(
        Device.id == device_id, Device.account_id == account_id, Device.revoked_at.is_(None),
    )) is None:
        raise AppError("invalid_token", status_code=401)


def request_pending_expense_fx(
    db: Session, *, tenant_id: str, initiator_account_id: int, initiator_device_id: int | None,
    expense_id: int, expected_row_version: int,
) -> BackgroundTask:
    _require_request_actor(db, tenant_id=tenant_id, account_id=initiator_account_id, device_id=initiator_device_id)
    resolve_write_capability(db)
    expense = resolve_expense(db, tenant_id, expense_id, for_update=True)
    if expense is None or expense.status == "rejected":
        raise AppError("expense_not_found", status_code=404)
    db.refresh(expense)
    latest = latest_pending_expense_fx_tasks(db, tenant_id=tenant_id, expense_ids=[expense.id]).get(expense.id)
    try:
        return _request_for_expense(db, expense, latest, expected_row_version,
            account_id=initiator_account_id, device_id=initiator_device_id)
    except BackgroundTaskCapacityFullError as exc:
        raise AppError("fx_capacity_full", "汇率队列暂时已满，账单已保留，请稍后重试。", status_code=503) from exc


def _request_for_expense(
    db: Session, expense: Expense, latest: BackgroundTask | None, expected_row_version: int,
    *, account_id: int, device_id: int | None,
) -> BackgroundTask:
    previous = None
    if latest is not None:
        try:
            previous = _original_input(latest)
            if _matches_committed_result(latest, previous, expected_row_version):
                return _resume_task(db, latest, previous) if _can_resume(latest) else latest
        except ValueError:
            previous = None
    if expense.row_version != expected_row_version:
        raise AppError("state_conflict", status_code=409)
    original = _current_input(expense)
    if original is None:
        raise AppError("fx_input_required", "请先核对待确认账单的原币金额和日期。", status_code=409)
    _retire_obsolete_fx_tasks(db, tenant_id=expense.tenant_id, expense_id=expense.id, current=original)
    if latest is not None and previous == original and _can_resume(latest):
        return _resume_task(db, latest, original)
    prepared = _prepare_input(db, original, account_id=account_id, device_id=device_id)
    db.commit()
    submit_pending_expense_fx(db, prepared)
    return prepared.task


def _assert_not_cancelled(db: Session, task_id: int) -> None:
    if check_cancellation_requested(db, task_id):
        raise TaskCancelledError


def _resolve_pending_fx(db: Session, task_id: int, original: PendingFxInput) -> PendingFxResult:
    _assert_not_cancelled(db, task_id)
    current = check_pending_fx(db, original)
    if isinstance(current, PendingFxResult):
        return current
    rate, _, _, _ = resolve_payload_rate(db, tenant_id=original.tenant_id,
        currency_code=original.original_currency_code, home_currency_code=original.home_currency_code,
        rate_date=original.rate_date)
    daily = None
    if rate is None:
        # Nothing has been written in the preflight; release its transaction and
        # connection before provider IO, then recheck cancellation and the original OCC.
        db.rollback()
        daily = fetch_pending_fx_reference(original)
    _assert_not_cancelled(db, task_id)
    return apply_pending_fx(db, original, daily)


def _publish_failure(db: Session, task_id: int, exc: Exception) -> None:
    code = "fx_reference_unavailable"
    if isinstance(exc, SQLAlchemyError):
        code = "fx_storage_unavailable"
    elif isinstance(exc, AppError):
        code = exc.error
    try:
        db.rollback()
        current = db.get(BackgroundTask, task_id)
        if current is not None and current.result_summary_json is not None:
            # A commit may have succeeded even when its acknowledgement failed.
            # Its result remains authoritative; let the worker finish publication.
            return
        mark_failed(db, task_id, expected_status="running", error_code=code, error_message=_FAILURE_MESSAGE)
    except SQLAlchemyError as storage_error:
        db.rollback()
        raise PendingFxTaskError(_FAILURE_MESSAGE) from storage_error


def run_pending_expense_fx_task(db: Session, task: BackgroundTask, payload: dict[str, object]) -> None:
    """The saved input owns execution; a saved result needs only worker completion."""
    del payload
    task_id = task.id
    try:
        original = _original_input(task)
        if task.result_summary_json is not None:
            return
        result = _resolve_pending_fx(db, task_id, original)
        # apply_pending_fx owns the Expense lock before this task lock. Re-read
        # after IO/OCC so an old ORM object cannot overwrite retirement or receipt.
        db.refresh(task, with_for_update=True)
        if task.cancellation_requested_at is not None or task.status == "cancelled":
            raise TaskCancelledError
        if task.result_summary_json is not None:
            return
        task.result_summary_json = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        task.progress_current = task.progress_total = 1
        task.progress_message = _PROGRESS_MESSAGES[result.outcome]
        db.commit()
    except TaskCancelledError:
        db.rollback()
        raise
    except (AppError, FxFetchError, ParseError, SQLAlchemyError, ValueError, TypeError, ArithmeticError) as exc:
        # Transport, decoding, money and persistence failures preserve the bill
        # without publishing provider payloads or SQL details.
        _publish_failure(db, task_id, exc)
