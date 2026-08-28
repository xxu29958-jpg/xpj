"""Honest Web response for retired direct writes to confirmed facts."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_fact import web_fact_error_response
from app.services.expense_service import resolve_expense


def confirmed_write_guard_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    error_code: str,
    fragment: bool = False,
) -> Response | None:
    """Return the fact-page/fragment 409 when a retired command targets confirmed."""

    expense = resolve_expense(db, selected_id, expense_id)
    if expense is None or expense.status != "confirmed":
        return None
    message = AppError(error_code).message
    if fragment:
        return HTMLResponse(f'<div class="empty-cell">{message}</div>', status_code=409)
    return web_fact_error_response(db, request, options, selected_id, expense_id, message)
