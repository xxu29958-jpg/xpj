"""Native Web receipt capture for the Inbox journey."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._upload_request import handle_upload
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
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Accept one real image into the selected ledger's pending queue."""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
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
        )
    except AppError as exc:
        if exc.error != "enrichment_capacity_full":
            raise
        return _web_redirect(
            "/web/pending",
            selected_id,
            msg="识别队列暂时已满，这张小票还没有保存；请稍等片刻重新选择上传。",
            flash_type="error",
        )
    return _web_redirect(
        "/web/pending",
        selected_id,
        msg="小票已收到，正在识别；完成后本页会自动更新。",
        flash_type="success",
        watch=upload.enrichment_task_public_id,
    )
