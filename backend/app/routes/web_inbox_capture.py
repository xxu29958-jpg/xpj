"""Native Web receipt capture for the Inbox journey."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._upload_request import handle_upload
from app.routes._web_attachment_intent import attachment_ack_response, require_attachment_binding
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
)

router = APIRouter(prefix="/web", tags=["web"])

_WEB_PENDING_UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "csrf_token"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "csrf_token": {"type": "string"},
                    },
                    "additionalProperties": False,
                }
            }
        },
    }
}


@router.post(
    "/pending/upload",
    response_class=RedirectResponse,
    status_code=303,
    openapi_extra=_WEB_PENDING_UPLOAD_OPENAPI,
)
async def web_pending_upload(
    request: Request,
    ledger_id: str = Query(default=""),
    timezone: str = Query(default=""),
    idempotency_key: str = Query(min_length=1, max_length=64),
    draft_scope: str = Query(default="", max_length=2048),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    """Accept one real image into the selected ledger's pending queue."""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    require_attachment_binding(db, request, ledger_id=ledger_id, draft_scope=draft_scope, require_session=False)
    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    timezone_name = timezone.strip() or None
    try:
        upload = await handle_upload(
            request=request,
            tenant_id=selected_id,
            db=db,
            source="网页上传",
            endpoint="web_product",
            initiator_account_id=actor_account_id,
            initiator_device_id=actor_device_id,
            timezone_name=timezone_name,
            idempotency_key=idempotency_key,
        )
    except AppError as exc:
        if "application/json" in request.headers.get("accept", ""):
            raise
        if exc.error != "enrichment_capacity_full":
            raise
        return _web_redirect(
            "/web/pending",
            selected_id,
            msg="识别队列暂时已满，这张小票还没有保存；请稍等片刻重新选择上传。",
            flash_type="error",
        )
    redirect = _web_redirect(
        "/web/pending",
        selected_id,
        msg="小票已收到，正在识别；完成后本页会自动更新。",
        flash_type="success",
        watch=upload.enrichment_task_public_id,
    )
    return attachment_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=upload.model_dump(mode="json"), next_href=redirect.headers["location"]) or redirect
