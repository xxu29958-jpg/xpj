"""Bind native attachment forms to the existing logical draft and receipt owners."""

import json
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import manual_expense_draft_presenter
from app.tenants import AuthContext


def attachment_form_context(db: Session, request: Request, *, action: str, ledger_id: str) -> dict:
    auth = getattr(request.state, "web_session_auth", None)
    scope = manual_expense_draft_presenter.manual_draft_scope(db, auth) if auth is not None else None
    ref = uuid4().hex
    query = {"ledger_id": ledger_id, "idempotency_key": ref}
    if scope is not None:
        query["draft_scope"] = json.dumps(scope, separators=(",", ":"))
    return {"action": action + "?" + urlencode(query), "client_ref": ref, "scope": scope}


def require_attachment_binding(db: Session, request: Request, *, ledger_id: str,
                               draft_scope: str, require_session: bool = True) -> AuthContext | None:
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None:
        if require_session or draft_scope:
            raise AppError("invalid_token", "请先恢复原浏览器身份，再继续这份原件任务。", status_code=401)
        return None
    try:
        captured = json.loads(draft_scope)
    except (ValueError, TypeError) as exc:
        raise AppError("session_binding_changed", "原任务身份无法确认，请保留输入并重新打开原账本。", status_code=409) from exc
    if ledger_id != auth.ledger_id or captured != manual_expense_draft_presenter.manual_draft_scope(db, auth):
        raise AppError("session_binding_changed", "身份或账本已切换；原文件与任务仍保留，请切回后继续。", status_code=409)
    return auth


def attachment_ack_response(request: Request, *, draft_scope: str, idempotency_key: str,
                            receipt: dict, next_href: str) -> JSONResponse | None:
    if not draft_scope or "application/json" not in request.headers.get("accept", ""):
        return None
    return JSONResponse({"ack": {"scope": json.loads(draft_scope), "clientRef": idempotency_key},
                         "receipt": receipt, "next": next_href}, headers={"Cache-Control": "no-store"})
