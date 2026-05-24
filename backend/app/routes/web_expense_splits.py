"""/web expense splits routes (v1.0 家庭拆账)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import split_replace_payload, web_edit_context
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
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
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseSplitReplaceRequest | None = None
    try:
        payload = split_replace_payload(
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
    return RedirectResponse(
        url=_with_ledger(f"/web/expenses/{expense_id}/edit", selected_id, msg="拆账已保存。"),
        status_code=303,
    )
