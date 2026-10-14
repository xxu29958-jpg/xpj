"""Owner Console FX rate page — status + manual "立即拉取" trigger.

The daily FX sync is a background daemon (09:10 / 23:10 Asia/Shanghai). Without
this page a silent failure (network drop, schema change) is only visible by
tailing logs, and there is no way to force a refresh between scheduled runs. The
GET surfaces ``fx_rate_sync_status()`` + the latest stored rates (assembled by
``owner_console_service.get_fx_panel_vm``); the POST runs one sync synchronously
(loopback-only, ~1s) through the same code path as the scheduler so both update
the same status counters.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.owner_console._settings import _settings_ctx
from app.routes.owner_console._shared import LocalOnly, templates
from app.services import integration_settings_service as integration
from app.services import owner_console_service as svc
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.fx_rate_scheduler import run_fx_sync_once

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _fx_context(request: Request, db: Session, *, refreshed: str | None = None) -> dict:
    ctx = _settings_ctx(request, db)
    home_currency = require_runtime_home_currency_code(db)
    vm = svc.get_fx_panel_vm(db, home_currency_code=home_currency)
    ctx.update(
        fx_source=vm.source,
        fx_auto_enabled=vm.auto_enabled,
        fx_scheduler_running=vm.scheduler_running,
        fx_scheduler_config_error=vm.scheduler_config_error,
        fx_sync_times=vm.sync_times,
        fx_sync_timezone=vm.sync_timezone,
        fx_success_count=vm.success_count,
        fx_failed_count=vm.failed_count,
        fx_last_error=vm.last_error,
        fx_last_success_at=vm.last_success_at,
        fx_rows=vm.rows,
        fx_latest_date=vm.latest_date,
        refreshed=refreshed,
        fx_form=integration.fx_form(),
    )
    return ctx


@router.get("/fx", response_class=HTMLResponse)
def owner_fx_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _fx_context(request, db)
    return templates.TemplateResponse(request=request, name="fx.html", context=ctx)


@router.post("/fx/settings", response_class=HTMLResponse)
def owner_fx_settings_post(
    request: Request,
    auto_enabled: bool = Form(False), source: str = Form("frankfurter_v2"),
    sync_times: str = Form("09:10,23:10"), timezone: str = Form("Asia/Shanghai"),
    url: str = Form(""), action: str = Form("save"),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    form = integration.FxSettingsForm(auto_enabled, source, sync_times, timezone, url)
    error = None
    status_code = 200
    try:
        integration.save_fx(form)
    except AppError as exc:
        error, status_code = exc.message, exc.status_code
    refreshed = ("ok" if run_fx_sync_once(db) else "fail") if not error and action == "refresh" else None
    ctx = _fx_context(request, db, refreshed=refreshed)
    ctx.update(fx_form=replace(form, url=integration.display_fx_url(source, url)) if error else integration.fx_form(), error=error,
               message=None if error else "汇率设置已保存。开启自动更新后，后台会在初始化或配置变化后主动获取，再按每日计划更新。保存设置本身不代表获取成功。")
    return templates.TemplateResponse(request=request, name="fx.html", context=ctx, status_code=status_code)


@router.post("/fx/refresh", response_class=HTMLResponse)
def owner_fx_refresh(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ok = run_fx_sync_once(db)
    ctx = _fx_context(request, db, refreshed="ok" if ok else "fail")
    return templates.TemplateResponse(request=request, name="fx.html", context=ctx)
