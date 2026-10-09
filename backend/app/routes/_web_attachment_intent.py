"""Bind native attachment forms to the existing logical draft and receipt owners."""

import json
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.services import manual_expense_draft_presenter


def attachment_form_context(db: Session, request: Request, *, action: str, ledger_id: str,
                            return_context: dict[str, str] | None = None) -> dict:
    auth = getattr(request.state, "web_session_auth", None)
    scope = manual_expense_draft_presenter.manual_draft_scope(db, auth) if auth is not None else None
    ref = uuid4().hex
    query = {"ledger_id": ledger_id, "idempotency_key": ref, **(return_context or {})}
    if scope is not None:
        query["draft_scope"] = json.dumps(scope, separators=(",", ":"))
    return {"action": action + "?" + urlencode(query), "client_ref": ref, "scope": scope}
