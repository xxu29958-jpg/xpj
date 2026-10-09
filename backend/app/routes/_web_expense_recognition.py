"""Recognition task presentation keeps original input separate from current bill facts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_draft_binding import draft_refusal_result, rendered_draft_scope
from app.routes._web_expense_return_context import ExpenseReturnContext, edit_context_params
from app.routes.web_common import _base_ctx, _with_ledger, templates
from app.services.expense_service import get_expense

if TYPE_CHECKING:
    from app.models import Expense


def _recognition_controls(current: Expense | None, text: bool, error: AppError | None) -> dict:
    active = current is not None and current.status == "pending" and (text or bool(current.image_path))
    editable = active and (not error or error.error == "invalid_request")
    retry_allowed = error and (error.status_code >= 500 or error.status_code == 429 or error.error == "idempotency_key_in_progress")
    return {"recognition_active": active, "recognition_editable": editable,
        "recognition_can_submit": bool(retry_allowed or editable)}


def recognition_page(request: Request, db: Session, options: list, selected: str, expense_id: int,
                     fields: dict[str, str], *, error: AppError | None = None, prepared: bool = False) -> Response:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
    try:
        current = get_expense(db, expense_id, selected)
    except AppError as exc:
        current = None
        error = error or exc
    scope, binding_required = rendered_draft_scope(db, request, fields.get("draft_scope"))
    text = request.url.path.endswith("recognize-text")
    original = {"ledger_id": selected, "expense_id": str(expense_id),
        "expected_row_version": str(current.row_version) if current else "",
        "idempotency_key": str(uuid4()), "draft_ref": str(uuid4()),
        "draft_scope": json.dumps(scope) if scope else "", **fields}
    if text:
        original.setdefault("raw_text", "")
    origin = edit_context_params(**{name: fields.get(name, "") for name in ExpenseReturnContext().as_kwargs()})
    result = "prepared" if prepared else draft_refusal_result(error) if error else ""
    ctx.update(original_fields=original, recognition_text=text,
        recognition_family="expensetext" if text else "expenseocr", recognition_scope=scope,
        recognition_result=result, recognition_binding_required=binding_required,
        recognition_current=current, error=error.message if error else "",
        current_href=_with_ledger(f"/web/expenses/{expense_id}/edit", selected, **origin),
        original_href=_with_ledger(f"/web/expenses/{expense_id}/original", selected, **origin),
        **_recognition_controls(current, text, error))
    return templates.TemplateResponse(request=request, name="expense_recognition.html", context=ctx,
        status_code=error.status_code if error else 200, headers={"Cache-Control": "no-store"})
