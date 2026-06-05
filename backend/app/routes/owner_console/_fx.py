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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.fx_rate_scheduler import run_fx_sync_once

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _fx_context(request: Request, db: Session, *, refreshed: str | None = None) -> dict:
    ctx = _base(request, db)
    vm = svc.get_fx_panel_vm(db, home_currency_code=ctx["home_currency_code"])
    ctx.update(
        fx_source=vm.source,
        fx_source_url=vm.source_url,
        fx_auto_enabled=vm.auto_enabled,
        fx_sync_times=vm.sync_times,
        fx_sync_timezone=vm.sync_timezone,
        fx_success_count=vm.success_count,
        fx_failed_count=vm.failed_count,
        fx_last_error=vm.last_error,
        fx_last_success_at=vm.last_success_at,
        fx_rows=vm.rows,
        fx_latest_date=vm.latest_date,
        refreshed=refreshed,
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


@router.post("/fx/refresh", response_class=HTMLResponse)
def owner_fx_refresh(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ok = run_fx_sync_once(db)
    ctx = _fx_context(request, db, refreshed="ok" if ok else "fail")
    return templates.TemplateResponse(request=request, name="fx.html", context=ctx)
