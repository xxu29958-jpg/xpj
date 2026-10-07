"""Bound native Web forms for independently adding category/tag options."""
import json
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.schemas._reference_creation import ReferenceKind
from app.services.reference_creation_service import create_reference

router = APIRouter(prefix="/web/reference", tags=["web"])


class ReferenceCreateForm(BaseModel):
    ledger_id: str = ""
    name: str = ""
    month: str = ""
    unused: str = ""
    draft_scope: str = ""
    idempotency_key: str = ""
    review_new: bool = False


def _render(request, db, options, selected_id, kind, values, *, error="", result="", status=200):
    context = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    label = "标签" if kind == "tag" else "分类"
    query = urlencode({"ledger_id": values.ledger_id, "month": values.month, "unused": values.unused})
    context.update(kind=kind, label=label, values=values.model_dump(), error=error, draft_result=result,
        reference_draft_scope=browser_draft_scope(db, request) if values.draft_scope else None,
        return_href=f"/web/{'tags' if kind == 'tag' else 'categories'}?{query}")
    return templates.TemplateResponse(request=request, name="reference_create.html", context=context,
        status_code=status, headers={"Cache-Control": "no-store"})


@router.get("/{kind}/new")
def reference_create_form(request: Request, kind: ReferenceKind, ledger_id: str = "", month: str = "", unused: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    scope = browser_draft_scope(db, request)
    values = ReferenceCreateForm(ledger_id=selected_id, month=month, unused=unused,
        draft_scope=json.dumps(scope) if scope else "", idempotency_key=str(uuid4()))
    return _render(request, db, options, selected_id, kind, values)


@router.post("/{kind}/create")
def reference_create_submit(request: Request, kind: ReferenceKind, values: Annotated[ReferenceCreateForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values.ledger_id or None, options, request=request)
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=values.model_dump(), task="添加标签" if kind == "tag" else "添加分类")
        if retained is not None:
            return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        values.draft_scope = reviewed_draft_scope(db, request, values.draft_scope, review=values.review_new)
        require_draft_binding(db, request, ledger_id=values.ledger_id or selected_id,
            draft_scope=values.draft_scope, require_session=False)
        if values.review_new:
            values.idempotency_key = str(uuid4())
            return _render(request, db, options, selected_id, kind, values, result="prepared")
        actor, _ = resolve_web_actor(db, request, selected_id)
        receipt = create_reference(db, tenant_id=selected_id, actor_account_id=actor, kind=kind,
            name=values.name, idempotency_key=values.idempotency_key)
    except AppError as exc:
        db.rollback()
        refusal = "rejected" if exc.error in {"invalid_request", "reference_name_conflict", "idempotency_key_reused"} else "blocked"
        return draft_error_response(request, exc, refusal_result=refusal) or _render(
            request, db, options, selected_id, kind, values, error=exc.message, result=refusal, status=exc.status_code)
    redirect = _web_redirect("/web/tags" if kind == "tag" else "/web/categories", selected_id,
        month=values.month, unused=values.unused, msg=f"已确认添加「{receipt.name}」。", flash_type="success")
    redirect.headers["location"] += f"#{kind}-{receipt.public_id}"
    return draft_ack_response(request, draft_scope=values.draft_scope, idempotency_key=values.idempotency_key,
        receipt=receipt, next_href=redirect.headers["location"]) or redirect
