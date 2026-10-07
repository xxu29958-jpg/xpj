"""Bind native drafts and acknowledgements to the installed browser identity."""

import json

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import manual_expense_draft_presenter
from app.tenants import AuthContext


def browser_draft_scope(db: Session, request: Request) -> dict | None:
    auth = getattr(request.state, "web_session_auth", None)
    return manual_expense_draft_presenter.manual_draft_scope(db, auth) if auth is not None else None


def rendered_draft_scope(db: Session, request: Request, captured_scope: str | None) -> tuple[dict | None, bool]:
    """A native form without captured identity exposes review before browser draft enhancement."""
    scope = browser_draft_scope(db, request)
    binding_required = scope is not None and captured_scope == ""
    return (None if binding_required else scope), binding_required


def reviewed_draft_scope(db: Session, request: Request, draft_scope: str, *, review: bool) -> str:
    """An older native form acquires identity only through explicit, non-writing review."""
    if review and not draft_scope and (current := browser_draft_scope(db, request)) is not None:
        return json.dumps(current)
    return draft_scope


def draft_refusal_result(exc: AppError) -> str:
    # These command-owner failures precede a financial commit. Access refusal
    # or an unknown/in-progress key says nothing about an earlier request.
    return "rejected" if exc.error in {"state_conflict", "budget_currency_conflict", "invalid_request",
        "amount_invalid", "recurring_merchant_required", "exchange_rate_pending",
        "expense_refund_exceeds_remaining", "expense_refund_exists", "expense_reversal_active",
        "expense_offset_not_active", "calendar_revision_conflict", "accounting_time_invalid"} else "blocked"


def draft_error_response(request: Request, exc: AppError, *, refusal_result: str | None = None) -> JSONResponse | None:
    if "application/json" not in request.headers.get("accept", ""):
        return None
    return JSONResponse({"error": exc.error, "message": exc.message,
        "draft_result": refusal_result or draft_refusal_result(exc)}, status_code=exc.status_code,
        headers={"Cache-Control": "no-store"})


def require_draft_binding(db: Session, request: Request, *, ledger_id: str,
                          draft_scope: str, require_session: bool = True) -> AuthContext | None:
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None:
        if require_session or draft_scope:
            raise AppError("invalid_token", "请先恢复原浏览器身份，再继续这份草稿。", status_code=401)
        return None
    try:
        captured = json.loads(draft_scope)
    except (ValueError, TypeError) as exc:
        raise AppError("session_binding_changed", "原任务身份无法确认，请保留输入并重新打开原账本。", status_code=409) from exc
    if ledger_id != auth.ledger_id or captured != manual_expense_draft_presenter.manual_draft_scope(db, auth):
        raise AppError("session_binding_changed", "身份或账本已切换；原草稿仍保留，请切回后继续。", status_code=409)
    return auth


def draft_ack_response(request: Request, *, draft_scope: str, idempotency_key: str,
                       receipt: dict | BaseModel, next_href: str) -> JSONResponse | None:
    if not draft_scope or "application/json" not in request.headers.get("accept", ""):
        return None
    if isinstance(receipt, BaseModel):
        receipt = receipt.model_dump(mode="json")
    return JSONResponse({"ack": {"scope": json.loads(draft_scope), "clientRef": idempotency_key},
                         "receipt": receipt, "next": next_href}, headers={"Cache-Control": "no-store"})
