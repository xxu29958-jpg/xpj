"""Local product controls for existing upload and maintenance capabilities."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import AppError
from app.routes.owner_console._settings import _settings_ctx
from app.routes.owner_console._shared import LocalOnly, templates
from app.services import operations_settings_service as operations

router = APIRouter(prefix="/owner/settings", tags=["owner-console"])


def _render(request: Request, db: Session, group: str, *, form: dict | None = None,
            error: str | None = None, message: str | None = None, status_code: int = 200) -> HTMLResponse:
    ctx = _settings_ctx(request, db, error=error, message=message)
    if group == "uploads":
        ctx["form"] = operations.upload_form() if form is None else form
    else:
        ctx["form"] = operations.maintenance_form() if form is None else form
        ctx["saved_form"] = operations.maintenance_form()
        ctx["statuses"] = operations.maintenance_status()
        workers = getattr(request.app.state, "maintenance_workers", {})
        ctx["running_workers"] = {key for key, worker in workers.items()
                                  if worker and worker.thread and worker.thread.is_alive()}
    return templates.TemplateResponse(request=request, name=f"settings/{group}.html", context=ctx, status_code=status_code)


@router.get("/uploads", response_class=HTMLResponse)
def owner_upload_settings_get(request: Request, _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render(request, db, "uploads")


@router.post("/uploads", response_class=HTMLResponse)
def owner_upload_settings_post(
    request: Request, max_upload_size_mb: str = Form("10"), upload_link_ttl_days: str = Form("90"),
    daily_budget_mb: str = Form("200"), upload_link_default_per_remote_interval_seconds: str = Form("2"),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    form = {"max_upload_size_mb": max_upload_size_mb, "upload_link_ttl_days": upload_link_ttl_days,
            "daily_budget_mb": daily_budget_mb,
            "upload_link_default_per_remote_interval_seconds": upload_link_default_per_remote_interval_seconds}
    try:
        operations.save_uploads(form)
    except AppError as exc:
        return _render(request, db, "uploads", form=form, error=exc.message, status_code=exc.status_code)
    return _render(request, db, "uploads", message="上传设置已保存。大小和默认配额从下一次上传生效；有效期用于此后新建或轮换的链接。")


@router.get("/maintenance", response_class=HTMLResponse)
def owner_maintenance_settings_get(request: Request, _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render(request, db, "maintenance")


@router.post("/maintenance", response_class=HTMLResponse)
async def owner_maintenance_settings_post(
    request: Request, _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    posted = await request.form()
    form = {name: posted.get(name) == "on" if isinstance(default, bool) else str(posted.get(name, ""))
            for name, default in operations.maintenance_form().items()}
    try:
        operations.save_maintenance(form, confirmed=posted.get("confirm_cleanup") == "on")
    except AppError as exc:
        return _render(request, db, "maintenance", form=form, error=exc.message, status_code=exc.status_code)
    return _render(request, db, "maintenance", message="维护设置已保存。后台空闲时在 30 秒内采用新计划；正在进行的清理完成后切换。")


def _cleanup_page(request: Request, db: Session, task: str, *, message: str | None = None,
                  error: str | None = None, status_code: int = 200) -> HTMLResponse:
    ctx = _settings_ctx(request, db, message=message, error=error)
    ctx["preview"] = operations.cleanup_preview(db, task)
    return templates.TemplateResponse(request=request, name="settings/cleanup_preview.html", context=ctx, status_code=status_code)


@router.get("/maintenance/preview", response_class=HTMLResponse)
def owner_cleanup_preview(request: Request, task: str, _local: None = LocalOnly,
                          removed: int | None = Query(None, ge=0, le=500), db: Session = Depends(get_db)) -> HTMLResponse:
    unit = "台撤销设备及关联失效凭证" if task == "device_cleanup" else "条过期 AI 调用记录"
    message = f"已清理 {removed} {unit}。账目和原件保持不变，下方数量已重新核对。" if removed is not None else None
    return _cleanup_page(request, db, task, message=message)


@router.post("/maintenance/run", response_class=HTMLResponse)
def owner_cleanup_run(request: Request, task: str = Form(...), confirmed: bool = Form(False),
                      retention_days: str = Form(""), _local: None = LocalOnly,
                      db: Session = Depends(get_db)) -> Response:
    try:
        removed = operations.run_cleanup(db, task, confirmed=confirmed, retention_days=retention_days)
    except AppError as exc:
        return _cleanup_page(request, db, task, error=exc.message, status_code=exc.status_code)
    except SQLAlchemyError as exc:
        db.rollback()
        retain_handled_error(request, exc)
        return _cleanup_page(request, db, task, status_code=503,
                             error="未能确认清理结果。下方已重新核对当前候选，确认范围后可以重试。")
    return RedirectResponse("/owner/settings/maintenance/preview?" + urlencode({"task": task, "removed": removed}), status_code=303)
