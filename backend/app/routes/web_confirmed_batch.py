"""Confirmed-list batch correction HTTP adapter.

The confirmed page remains a read concern in ``web_app``. This router owns the
single batch command surface and delegates financial mutation to the confirmed
correction service.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_bulk_snapshot import parse_bulk_snapshot
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_app import _confirmed_redirect, _render_confirmed_page
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
)
from app.schemas import ConfirmedExpenseBatchUpdateRequest, ConfirmedExpenseBatchUpdateResponse
from app.services.expense_correction_service import batch_update_confirmed_expenses
from app.tag_text import parse_tags

router = APIRouter(prefix="/web", tags=["web"])


def _confirmed_batch_payload(
    *,
    action: str,
    expense_ids: list[int],
    expected_row_version_by_id: dict[int, int],
    category: str,
    tags: str,
    reason: str,
) -> tuple[ConfirmedExpenseBatchUpdateRequest | None, str]:
    reason_clean = reason.strip()
    if not reason_clean:
        return None, "请说明这次批量更正的原因。"
    try:
        if action.strip() == "set_category":
            if not category.strip():
                return None, "请填写分类。"
            return ConfirmedExpenseBatchUpdateRequest(
                expense_ids=expense_ids,
                expected_row_version_by_id=expected_row_version_by_id,
                category=category.strip(),
                reason=reason_clean,
            ), ""
        if action.strip() == "set_tags":
            tag_names = parse_tags(tags.strip())
            if not tag_names:
                return None, "请填写标签。"
            return ConfirmedExpenseBatchUpdateRequest(
                expense_ids=expense_ids,
                expected_row_version_by_id=expected_row_version_by_id,
                tags=", ".join(tag_names),
                reason=reason_clean,
            ), ""
        return None, "批处理操作不正确。"
    except ValidationError as exc:
        first_field = str(exc.errors(include_url=False)[0]["loc"][-1])
        if first_field == "category":
            return None, "分类最多 64 个字符。"
        if first_field == "tags" and len(tags) > 500:
            return None, "标签最多 500 个字符。"
        return None, "单个标签最多 64 个字符。" if first_field == "tags" else "批处理参数不正确。"


def _confirmed_batch_result_message(result: ConfirmedExpenseBatchUpdateResponse) -> str:
    parts: list[str] = []
    if result.updated_count:
        parts.append(f"已更新 {result.updated_count} 条")
    if result.skipped_not_found:
        parts.append(f"跳过 {result.skipped_not_found} 条：不属于当前账本")
    if result.skipped_not_confirmed:
        parts.append(f"跳过 {result.skipped_not_confirmed} 条：不是已入账")
    return "；".join(parts or ["没有可更新的账单"]) + "。"


@dataclass(frozen=True)
class _ConfirmedBatchOutcome:
    selected_expense_ids: list[int]
    result: ConfirmedExpenseBatchUpdateResponse | None = None
    error_message: str = ""
    error_status: int = 422


def _execute_confirmed_batch(
    db: Session,
    *,
    selected_id: str,
    action: str,
    expense_ids: list[int],
    expected_row_version: list[str],
    expense_snapshot: list[str],
    category: str,
    tags: str,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
    idempotency_key: str,
) -> _ConfirmedBatchOutcome:
    parsed = parse_bulk_snapshot(expense_ids, expected_row_version, expense_snapshot)
    if parsed is None:
        return _ConfirmedBatchOutcome([], error_message="页面已过期，请刷新后重新批处理。")
    selected_expense_ids, expected_by_id = parsed
    if not selected_expense_ids:
        return _ConfirmedBatchOutcome([], error_message="请先勾选账单。")
    payload, error = _confirmed_batch_payload(
        action=action,
        expense_ids=selected_expense_ids,
        expected_row_version_by_id=expected_by_id,
        category=category,
        tags=tags,
        reason=reason,
    )
    if payload is None:
        return _ConfirmedBatchOutcome(selected_expense_ids, error_message=error)
    try:
        result = batch_update_confirmed_expenses(
            db,
            tenant_id=selected_id,
            payload=payload,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            idempotency_key=idempotency_key,
        )
    except AppError as exc:
        db.rollback()
        message = "账单已在其它端被修改，请刷新后重试。" if exc.error == "state_conflict" else exc.message
        return _ConfirmedBatchOutcome(selected_expense_ids, error_message=message, error_status=exc.status_code)
    return _ConfirmedBatchOutcome(selected_expense_ids, result=result)


@router.post("/confirmed/batch-update", response_class=HTMLResponse)
def web_confirmed_batch_update(
    request: Request,
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    expected_row_version: list[str] = Form(default=[]),
    expense_snapshot: list[str] = Form(default=[]),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    reason: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    month: str = Form(default=""),
    tag: str = Form(default=""),
    page: int = Form(default=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    actor_account_id, actor_device_id = resolve_web_actor(
        db,
        request,
        selected_id,
    )
    outcome = _execute_confirmed_batch(
        db,
        selected_id=selected_id,
        action=action,
        expense_ids=expense_ids,
        expected_row_version=expected_row_version,
        expense_snapshot=expense_snapshot,
        category=category,
        tags=tags,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=idempotency_key,
    )
    if outcome.error_message:
        return _render_confirmed_page(
            request,
            db,
            options,
            selected_id,
            page=page,
            month=month or None,
            tag=tag or None,
            msg=outcome.error_message,
            status_code=outcome.error_status,
            flash_type="error",
            batch_category_input=category,
            batch_tags_input=tags,
            batch_reason_input=reason,
            batch_idempotency_key=idempotency_key,
            selected_expense_ids=outcome.selected_expense_ids,
        )
    if outcome.result is None:
        raise AppError("server_error", status_code=500)
    return _confirmed_redirect(
        selected_id,
        month=month,
        tag=tag,
        page=page,
        msg=_confirmed_batch_result_message(outcome.result),
    )
