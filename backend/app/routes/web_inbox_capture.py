"""Native Web receipt capture for the Inbox journey."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._upload_request import handle_upload
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
)
from app.services import background_task_service
from app.services.pending_enrichment_task_service import (
    PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
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
    background_tasks: BackgroundTasks,
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
    actor_account_id = resolve_web_actor_account_id(db, request, selected_id)
    timezone_name = timezone.strip() or None
    upload = await handle_upload(
        request=request,
        background_tasks=background_tasks,
        tenant_id=selected_id,
        db=db,
        source="网页上传",
        endpoint="web_product",
        timezone_name=timezone_name,
        schedule_enrichment=False,
    )
    try:
        task = background_task_service.enqueue(
            db,
            task_type=PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
            initiator_account_id=actor_account_id,
            ledger_id=selected_id,
            payload={
                "expense_id": upload.response.id,
                "tenant_id": selected_id,
                "timezone_name": timezone_name,
                "expected_row_version": upload.predecessor_row_version,
            },
            progress_total=1,
        )
        task_public_id = task.public_id
    except background_task_service.BackgroundTaskSubmissionError as exc:
        # The upload and failed task row are already durable. Keep that truth
        # visible instead of returning 500 and inviting a duplicate upload.
        task_public_id = exc.task_public_id
    return _web_redirect(
        "/web/pending",
        selected_id,
        msg="小票已收到，正在识别；完成后本页会自动更新。",
        flash_type="success",
        watch=task_public_id,
    )
