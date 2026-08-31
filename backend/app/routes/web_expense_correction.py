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
    refresh_correction_source_flags,
    web_correction_idempotency_body,
)
from app.routes._web_correction_page import (
    correction_form_error_response,
    web_correction_context,
)
from app.routes._web_expense_return_context import (
    edit_context_params,
    resolve_return_to,
    return_context_params,
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


def _correction_return_kwargs(form: CorrectionFormData) -> dict[str, str]:
    return {
        "return_to": form.return_to,
        "return_month": form.return_month,
        "return_filter": form.return_filter,
        "return_page": form.return_page,
        "return_tag": form.return_tag,
        "return_query": form.return_query,
    }


def _fact_redirect(
    expense_id: int,
    selected_id: str,
    form: CorrectionFormData,
    *,
    message: str,
    flash_type: str,
) -> Response:
    return _web_redirect(
        f"/web/expenses/{expense_id}/edit",
        selected_id,
        msg=message,
        flash_type=flash_type,
        **edit_context_params(**_correction_return_kwargs(form)),
    )


@router.get("/expenses/{expense_id}/correct", response_class=HTMLResponse)
def web_correct_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return_values = {
        "return_to": return_to,
        "return_month": return_month,
        "return_filter": return_filter,
        "return_page": return_page,
        "return_tag": return_tag,
        "return_query": return_query,
    }
    try:
        expense = get_expense(db, expense_id, selected_id)
    except AppError as exc:
        return _web_redirect(
            resolve_return_to(return_to, "/web/confirmed"),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(**return_values),
        )
    if expense.status != "confirmed":
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="只有已确认账单才能创建更正记录。",
            flash_type="error",
            **edit_context_params(**return_values),
        )
    selected = next((opt for opt in options if opt.ledger_id == selected_id), None)
    if selected is None or selected.role not in {"owner", "member"}:
        return _web_redirect(
            f"/web/expenses/{expense_id}/edit",
            selected_id,
            msg="当前角色为只读，无法更正账单。",
            flash_type="error",
            **edit_context_params(**return_values),
        )
    ctx = web_correction_context(
        db,
        request,
        options,
        selected_id,
        expense_id,
        **return_values,
    )
    return templates.TemplateResponse(request=request, name="expense_correct.html", context=ctx)


def _correction_error_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    form: CorrectionFormData,
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
        receipt_item_rows=None if parsed.item_sources_stale else parsed.item_form_rows,
        split_form_rows=None if parsed.split_sources_stale else parsed.split_form_rows,
        **_correction_return_kwargs(form),
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


def _current_scalar_form_values(values: dict[str, str]) -> dict[str, str]:
    """Keep the user's explanation, but never pair stale scalars with a fresh CAS token."""

    return {"reason": values.get("reason", ""), "idempotency_key": ""}


def _submission_error_response(
    db: Session,
    request: Request,
    *,
    options,
    selected_id: str,
    expense_id: int,
    form: CorrectionFormData,
    parsed: CorrectionParseOutcome,
    claimed: ClaimedWebCorrection | None,
) -> Response | None:
    if claimed is not None and claimed.error is not None:
        values = parsed.form_values
        if claimed.error.conflict:
            values = _current_scalar_form_values(values)
        elif claimed.error.rotate_idempotency_key:
            values = {**values, "idempotency_key": ""}
        message = claimed.error.error or "提交参数不正确，请检查后重试。"
        if claimed.error.conflict and (parsed.item_sources_stale or parsed.split_sources_stale):
            message = f"{message} {parsed.error}"
        return _correction_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            form,
            parsed,
            message=message,
            status_code=claimed.error.error_status,
            conflict=claimed.error.conflict,
            form_values=values,
        )
    if parsed.payload is None:
        if claimed is not None and claimed.claim is not None:
            db.rollback()
        source_conflict = parsed.error_status == 409 and (
            parsed.item_sources_stale or parsed.split_sources_stale
        )
        return _correction_error_response(
            db,
            request,
            options,
            selected_id,
            expense_id,
            form,
            parsed,
            message=parsed.error or "提交参数不正确，请检查后重试。",
            status_code=parsed.error_status,
            field_errors=parsed.field_errors,
            conflict=source_conflict,
            form_values=(
                _current_scalar_form_values(parsed.form_values)
                if source_conflict
                else parsed.form_values
            ),
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
        form,
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
    form: CorrectionFormData,
    parsed: CorrectionParseOutcome,
    command: CorrectionCommandOutcome,
) -> Response | None:
    if command.error is None:
        return None
    values = parsed.form_values
    message = command.error
    if command.conflict:
        values = _current_scalar_form_values(values)
        if refresh_correction_source_flags(
            db,
            expense_id=expense_id,
            selected_id=selected_id,
            form=form,
            outcome=parsed,
        ):
            message = f"{message} {parsed.error}"
    elif command.rotate_idempotency_key:
        values = {**values, "idempotency_key": ""}
    field_errors = {"splits": message} if command.error_code == "expense_split_total_exceeds_parent" else None
    return _correction_error_response(
        db,
        request,
        options,
        selected_id,
        expense_id,
        form,
        parsed,
        message=message,
        status_code=command.error_status,
        field_errors=field_errors,
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
        return _web_redirect(
            resolve_return_to(form.return_to, "/web/confirmed"),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(**_correction_return_kwargs(form)),
        )
    if expense.status != "confirmed":
        return _fact_redirect(
            expense_id,
            selected_id,
            form,
            message="只有已确认账单才能创建更正记录。",
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
        return _fact_redirect(
            expense_id,
            selected_id,
            form,
            message="已记录更正。",
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
        form=form,
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
        form=form,
        parsed=parsed,
        command=command,
    )
    if command_error is not None:
        return command_error
    return _fact_redirect(
        expense_id,
        selected_id,
        form,
        message="已记录更正。",
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
