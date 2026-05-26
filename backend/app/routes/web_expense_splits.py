"""/web expense splits routes (v1.0 家庭拆账)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import split_replace_payload, web_edit_context
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_updated_at_token,
    templates,
)
from app.schemas import ExpenseSplitReplaceRequest
from app.services.expense_split_service import replace_expense_splits

router = APIRouter(prefix="/web", tags=["web"])


@router.post("/expenses/{expense_id}/splits/save", response_class=HTMLResponse)
def web_splits_save(
    expense_id: int,
    request: Request,
    split_member_id: list[str] = Form(default=[]),
    split_amount_yuan: list[str] = Form(default=[]),
    split_note: list[str] = Form(default=[]),
    expected_updated_at: str = Form(default=""),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseSplitReplaceRequest | None = None
    parsed_updated_at = parse_form_updated_at_token(expected_updated_at)
    if parsed_updated_at is None:
        error = "页面已过期，请刷新后重新保存拆账。"
    try:
        if error is None:
            payload = split_replace_payload(
                expected_updated_at=parsed_updated_at,
                split_member_id=split_member_id,
                split_amount_yuan=split_amount_yuan,
                split_note=split_note,
            )
    except AppError as exc:
        error = exc.message
    if error is None and payload is not None:
        try:
            replace_expense_splits(
                db,
                expense_id,
                selected_id,
                payload,
                actor_account_id=None,
            )
        except AppError as exc:
            error = exc.message
    if error is not None:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
        ctx["splits_error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect(f"/web/expenses/{expense_id}/edit", selected_id, msg="拆账已保存。")
