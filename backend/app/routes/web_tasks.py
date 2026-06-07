"""ADR-0030 PR-2: /web tasks page — list recent background tasks + cancel.

Account-scoped (matches /api/tasks): owner-console loopback acts as the
owner of the selected ledger, cookie session acts as session.account.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.services import background_task_service as bgtasks
from app.services.ledger_service import find_owner_account_id_for_ledger

router = APIRouter(prefix="/web", tags=["web"])


def _resolve_account_id(db: Session, request: Request, ledger_id: str) -> int:
    """Reuse the same resolver as /web/bill-splits."""
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.account_id
    account_id = find_owner_account_id_for_ledger(db, ledger_id=ledger_id)
    if account_id is None:
        raise AppError("invalid_request", "未找到 owner 账号。", status_code=400)
    return account_id


@router.get("/tasks", response_class=HTMLResponse)
def web_tasks(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _resolve_account_id(db, request, selected_id)

    raw = bgtasks.list_recent_tasks(db, account_id=account_id, tenant_id=selected_id)
    rows: list[dict[str, Any]] = []
    for task in raw:
        result_summary: dict[str, Any] | None = None
        if task.result_summary_json:
            try:
                decoded = json.loads(task.result_summary_json)
                if isinstance(decoded, dict):
                    result_summary = decoded
            except json.JSONDecodeError:
                result_summary = None
        rows.append({
            "public_id": task.public_id,
            "task_type": task.task_type,
            "status": task.status,
            "progress_current": task.progress_current,
            "progress_total": task.progress_total,
            "progress_message": task.progress_message,
            "error_code": task.error_code,
            "error_message": task.error_message,
            "result_summary": result_summary,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "cancellation_requested_at": task.cancellation_requested_at,
            "is_cancellable": task.status in ("queued", "running")
            and task.cancellation_requested_at is None,
        })

    active = [r for r in rows if r["status"] in ("queued", "running")]
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="后台任务",
    )
    ctx["task_rows"] = rows
    ctx["active_task_count"] = len(active)
    ctx["message"] = msg
    return templates.TemplateResponse(
        request=request, name="tasks.html", context=ctx
    )


@router.post(
    "/tasks/{public_id}/cancel",
    response_class=HTMLResponse,
)
def web_task_cancel(
    public_id: str,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    # ADR-0043 review (P1 family): cancelling sets cancellation_requested_at — a
    # write. A paired *viewer* Web session must be 403'd here (ENGINEERING_RULES
    # §14), not merely account-matched inside request_cancellation. The GET list
    # stays local-only-rendering; only this mutate is writer-only.
    _require_selected_ledger_write(options, selected_id)
    account_id = _resolve_account_id(db, request, selected_id)
    bgtasks.request_cancellation(db, public_id, account_id=account_id, tenant_id=selected_id)
    return _web_redirect("/web/tasks", selected_id, msg="已请求取消任务。")
