"""/web expense fact correction routes — confirmed 账单的显式更正命令（薄路由）。

- ``GET  /web/expenses/{id}/correct``      — 更正表单页（读当前事实快照预填）。
- ``POST /web/expenses/{id}/corrections``  — no-JS 安全的一次性更正：
  标量 + 明细 + 拆账同一 correction intent（A1 片合同）。

责任拆分：表单解析/段落 diff → ``_web_correction_form``；命令/幂等/OCC 执行
→ ``_web_correction_command``；页面 context/错误重渲 → ``_web_correction_page``。
本文件只做 HTTP 形状与编排。
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_correction_command import (
    ClaimedWebCorrection,
    CorrectionCommandOutcome,
    claim_web_correction,
    execute_correction,
)
from app.routes._web_correction_form import (
    CorrectionFormData,
    CorrectionParseOutcome,
    correction_form_data,
    parse_correction_form,
    web_correction_idempotency_body,
)
from app.routes._web_correction_page import (
    correction_form_error_response,
    web_correction_context,
)
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.expense_service import get_expense

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/correct", response_class=HTMLResponse)
def web_correct_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    try:
        expense = get_expense(db, expense_id, selected_id)
    except AppError as exc:
        return _web_redirect("/web/confirmed", selected_id, msg=exc.message, flash_type="error")
    if expense.status != "confirmed":
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="只有已确认账单才能创建更正记录。",
            flash_type="error",
        )
    selected = next((opt for opt in options if opt.ledger_id == selected_id), None)
    if selected is None or selected.role not in {"owner", "member"}:
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="当前角色为只读，无法更正账单。",
            flash_type="error",
        )
    ctx = web_correction_context(db, request, options, selected_id, expense_id)
    return templates.TemplateResponse(request=request, name="expense_correct.html", context=ctx)


def _correction_error_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    parsed: CorrectionParseOutcome,
    *,
    message: str,
    status_code: int,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
    form_values: dict[str, str] | None = None,
) -> Response:
    return correction_form_error_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error=message,
        status_code=status_code,
        form_values=form_values if form_values is not None else parsed.form_values,
        field_errors=field_errors,
        conflict=conflict,
        receipt_item_rows=parsed.item_form_rows,
        split_form_rows=parsed.split_form_rows,
    )


def _claim_correction_submission(
    db: Session,
    request: Request,
    *,
    selected_id: str,
    expense_id: int,
    form: CorrectionFormData,
) -> tuple[str, ClaimedWebCorrection | None]:
    key = form.idempotency_key.strip() or str(uuid4())
    submitted_row_version = parse_form_row_version_token(form.expected_row_version)
    if submitted_row_version is None:
        return key, None
    return key, claim_web_correction(
        db,
        request,
        expense_id=expense_id,
        selected_id=selected_id,
        expected_row_version=submitted_row_version,
        idempotency_key=key,
        intent_body=web_correction_idempotency_body(form),
    )


def _submission_error_response(
    db: Session,
    request: Request,
    *,
    options,
    selected_id: str,
    expense_id: int,
    parsed: CorrectionParseOutcome,
    claimed: ClaimedWebCorrection | None,
) -> Response | None:
    if claimed is not None and claimed.error is not None:
        values = parsed.form_values
        if claimed.error.rotate_idempotency_key:
            values = {**values, "idempotency_key": ""}
        return _correction_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            parsed,
            message=claimed.error.error or "提交参数不正确，请检查后重试。",
            status_code=claimed.error.error_status,
            conflict=claimed.error.conflict,
            form_values=values,
        )
    if parsed.payload is None:
        if claimed is not None and claimed.claim is not None:
            db.rollback()
        return _correction_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            parsed,
            message=parsed.error or "提交参数不正确，请检查后重试。",
            status_code=parsed.error_status,
            field_errors=parsed.field_errors,
        )
    if claimed is not None and claimed.claim is not None:
        return None
    db.rollback()
    return _correction_error_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        parsed,
        message="页面已过期，请刷新后重新提交。",
        status_code=422,
    )


def _command_failure_response(
    db: Session,
    request: Request,
    *,
    options,
    selected_id: str,
    expense_id: int,
    parsed: CorrectionParseOutcome,
    command: CorrectionCommandOutcome,
) -> Response | None:
    if command.error is None:
        return None
    values = parsed.form_values
    if command.rotate_idempotency_key:
        values = {**values, "idempotency_key": ""}
    return _correction_error_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        parsed,
        message=command.error,
        status_code=command.error_status,
        conflict=command.conflict,
        form_values=values,
    )


def _handle_correction_post(
    db: Session,
    request: Request,
    *,
    options,
    selected_id: str,
    expense_id: int,
    form: CorrectionFormData,
) -> Response:
    try:
        expense = get_expense(db, expense_id, selected_id)
    except AppError as exc:
        return _web_redirect("/web/confirmed", selected_id, msg=exc.message, flash_type="error")
    if expense.status != "confirmed":
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="只有已确认账单才能创建更正记录。",
            flash_type="error",
        )
    key, claimed = _claim_correction_submission(
        db,
        request,
        selected_id=selected_id,
        expense_id=expense_id,
        form=form,
    )
    if claimed is not None and claimed.replayed:
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="已记录更正。",
            flash_type="success",
        )
    parsed = parse_correction_form(
        db, expense=expense, selected_id=selected_id, form=form
    )
    validation_error = _submission_error_response(
        db,
        request,
        options=options,
        selected_id=selected_id,
        expense_id=expense_id,
        parsed=parsed,
        claimed=claimed,
    )
    if validation_error is not None:
        return validation_error
    assert claimed is not None and parsed.payload is not None
    command = execute_correction(
        db,
        claimed=claimed,
        expense_id=expense_id,
        selected_id=selected_id,
        payload=parsed.payload,
        idempotency_key=key,
    )
    command_error = _command_failure_response(
        db,
        request,
        options=options,
        selected_id=selected_id,
        expense_id=expense_id,
        parsed=parsed,
        command=command,
    )
    if command_error is not None:
        return command_error
    return _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg="已记录更正。",
        flash_type="success",
    )


@router.post("/expenses/{expense_id}/corrections", response_class=HTMLResponse)
def web_correct_post(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    form: CorrectionFormData = Depends(correction_form_data),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    return _handle_correction_post(
        db,
        request,
        options=options,
        selected_id=selected_id,
        expense_id=expense_id,
        form=form,
    )
