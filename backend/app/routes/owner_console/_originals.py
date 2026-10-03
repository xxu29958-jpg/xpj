"""A local, ledger-bound consumer of durable orphan inspection and disposal."""

from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError, retain_handled_error
from app.routes._original_file_response import OriginalFileResponse
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import orphan_maintenance_tasks as maintenance
from app.services.background_task_admission import BackgroundTaskCapacityFullError
from app.services.original_read_service import read_original_snapshot
from app.services.orphan_task_results import DISPOSE_ORPHANS, INSPECT_ORPHANS, public_task_result

if TYPE_CHECKING:
    from app.models import BackgroundTask

router = APIRouter(prefix="/owner", tags=["owner-console"])
PAGE_SIZE = 12
STATUS_LABELS = {"queued": "等待开始", "running": "正在处理", "completed": "本次已完成",
    "failed": "尚未完成", "cancelled": "已停止"}


def _href(ledger_id: str, **values) -> str:
    return "/owner/originals?" + urlencode({"ledger_id": ledger_id, **values})


def _bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.2f} MB" if value >= 1024 * 1024 else f"{value / 1024:.1f} KB"


def _task_vm(task: "BackgroundTask") -> dict:
    result = maintenance.task_result(task)
    remaining = len(maintenance.remaining_candidates(task)) if task.task_type == DISPOSE_ORPHANS else 0
    origin = maintenance.task_origin(task)
    return {"public_id": task.public_id, "kind": task.task_type, "status": task.status,
        "kind_label": "检查未引用文件" if task.task_type == INSPECT_ORPHANS else "处置本次文件",
        "status_label": "仍有文件待处理" if task.status == "completed" and remaining else STATUS_LABELS[task.status],
        "created_at": task.created_at,
        "progress_current": task.progress_current, "progress_total": task.progress_total,
        "result": public_task_result(task.task_type, result),
        "size_label": _bytes(result.get("candidate_bytes", result.get("deleted_bytes", 0))),
        "can_continue": task.status not in {"queued", "running"} and (
            bool(remaining) if task.task_type == DISPOSE_ORPHANS else task.status != "completed"),
        "inspection_href": _href(task.tenant_id, task_id=origin["inspection_id"]) if origin.get("inspection_id") else None,
        "previous_task_href": _href(task.tenant_id, task_id=origin["continued_from"]) if origin.get("continued_from") else None,
        "href": _href(task.tenant_id, task_id=task.public_id)}


def _render_originals(request: Request, db: Session, *, ledger_id: str | None = None,
                      task_id: UUID | None = None, page: int = 1, files_page: int = 1,
                      client_ref: UUID | None = None, error: str | None = None,
                      status_code: int = 200) -> HTMLResponse:
    choices = maintenance.maintenance_ledgers(db)
    selected = ledger_id or (choices[0].ledger_id if choices else None)
    context = {**_base(request, db), "choices": choices, "selected": selected, "task": None,
        "tasks": [], "files": [], "disposal": None, "client_ref": str(client_ref or uuid4()),
        "page": page, "files_page": files_page, "error": error}
    if selected is not None:
        rows = maintenance.list_maintenance_tasks(db, ledger_id=selected, offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE + 1)
        context.update(tasks=[_task_vm(row) for row in rows[:PAGE_SIZE]],
            previous_href=_href(selected, page=page - 1) if page > 1 else None,
            next_href=_href(selected, page=page + 1) if len(rows) > PAGE_SIZE else None)
        if task_id:
            task = maintenance.read_maintenance_task(db, str(task_id), ledger_id=selected)
            context["task"] = _task_vm(task)
            if task.task_type == INSPECT_ORPHANS:
                disposal = maintenance.disposal_for_inspection(db, task)
                context["disposal"] = _task_vm(disposal) if disposal is not None else None
            candidates = maintenance.task_result(task).get("_candidates", [])
            start = (files_page - 1) * PAGE_SIZE
            context["files"] = [{"number": index + 1, "size": _bytes(item["size"]), "modified_at": item["modified_at"],
                "href": f"/owner/originals/tasks/{task.public_id}/files/{index}?" + urlencode({"ledger_id": selected})}
                for index, item in enumerate(candidates[start:start + PAGE_SIZE], start=start)]
            context["files_previous_href"] = _href(selected, task_id=task.public_id, files_page=files_page - 1) if files_page > 1 else None
            context["files_next_href"] = _href(selected, task_id=task.public_id, files_page=files_page + 1) if start + PAGE_SIZE < len(candidates) else None
    return templates.TemplateResponse(request=request, name="originals.html", context=context, status_code=status_code)


@router.get("/originals", response_class=HTMLResponse)
def owner_originals(request: Request, ledger_id: str | None = None, task_id: UUID | None = None,
                    page: int = Query(1, ge=1), files_page: int = Query(1, ge=1),
                    _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render_originals(request, db, ledger_id=ledger_id, task_id=task_id, page=page, files_page=files_page)


@router.post("/originals/inspect")
def owner_inspect_originals(request: Request, ledger_id: str = Form(...), client_ref: UUID = Form(...),
                           _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    try:
        task = maintenance.start_inspection(db, ledger_id=ledger_id, client_ref=client_ref)
    except BackgroundTaskCapacityFullError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_originals(request, db, ledger_id=ledger_id, client_ref=client_ref, status_code=503,
            error="后台任务正在处理其他工作，这次检查尚未开始。请稍后在此重试。")
    return RedirectResponse(_href(ledger_id, task_id=task.public_id), status_code=303)


@router.post("/originals/tasks/{public_id}/{action}")
def owner_original_action(request: Request, public_id: UUID, action: Literal["dispose", "continue", "cancel"],
                          ledger_id: str = Form(...), confirmed: bool = Form(False),
                          _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    try:
        if action == "dispose":
            if not confirmed:
                raise AppError("invalid_request", "请先核对候选文件，并勾选本次永久删除确认。", status_code=422)
            task = maintenance.start_disposal(db, ledger_id=ledger_id, inspection_id=str(public_id))
        elif action == "continue":
            task = maintenance.continue_maintenance(db, ledger_id=ledger_id, public_id=str(public_id))
        else:
            task = maintenance.cancel_maintenance(db, ledger_id=ledger_id, public_id=str(public_id))
    except BackgroundTaskCapacityFullError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _render_originals(request, db, ledger_id=ledger_id, task_id=public_id, status_code=503,
            error="后台任务正在处理其他工作，本次操作尚未开始。原任务和候选范围仍保留，请稍后继续。")
    return RedirectResponse(_href(ledger_id, task_id=task.public_id), status_code=303)


@router.get("/originals/tasks/{public_id}/files/{index}")
def owner_orphan_preview(public_id: UUID, index: int, ledger_id: str,
                         _local: None = LocalOnly, db: Session = Depends(get_db)) -> OriginalFileResponse:
    task = maintenance.read_maintenance_task(db, str(public_id), ledger_id=ledger_id)
    candidates = maintenance.task_result(task).get("_candidates", [])
    if task.task_type != INSPECT_ORPHANS or not 0 <= index < len(candidates):
        raise AppError("image_not_found", status_code=404)
    candidate = candidates[index]
    snapshot = read_original_snapshot(relative_path=candidate["reference"], tenant_id=ledger_id,
        expected_sha256=candidate["sha256"])
    response = OriginalFileResponse(snapshot)
    response.headers["Cache-Control"] = "no-store"
    return response
