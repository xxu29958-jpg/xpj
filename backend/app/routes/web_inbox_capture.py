"""Native Web receipt capture for the Inbox journey."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._upload_request import handle_upload
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.post("/pending/upload", response_class=RedirectResponse, status_code=303)
async def web_pending_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    receipt: UploadFile = File(alias="file"),
    ledger_id: str = Form(default=""),
    timezone: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Accept one real image into the selected ledger's pending queue."""
    del receipt  # Parsed and cached on Request; the shared upload owner consumes it.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    await handle_upload(
        request=request,
        background_tasks=background_tasks,
        tenant_id=selected_id,
        db=db,
        source="网页上传",
        endpoint="web_product",
        timezone_name=timezone.strip() or None,
    )
    return _web_redirect(
        "/web/pending",
        selected_id,
        msg="小票已收到，识别结果会显示在待确认队列。",
        flash_type="success",
    )
