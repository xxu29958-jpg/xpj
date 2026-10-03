"""Local product controls for existing upload and maintenance capabilities."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.owner_console._settings import _settings_ctx
from app.routes.owner_console._shared import LocalOnly, templates
from app.services import operations_settings_service as operations

router = APIRouter(prefix="/owner/settings", tags=["owner-console"])


def _render(request: Request, db: Session, group: str, *, form: dict | None = None,
            error: str | None = None, message: str | None = None, status_code: int = 200) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active=group, error=error, message=message)
    if group == "uploads":
        ctx["form"] = operations.upload_form() if form is None else form
    else:
        ctx["form"] = operations.maintenance_form() if form is None else form
        ctx["statuses"] = operations.maintenance_status()
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
