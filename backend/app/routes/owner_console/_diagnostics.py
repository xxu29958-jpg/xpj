"""Owner Console diagnostics page (single endpoint)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.time_service import now_utc

router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("/diagnostics", response_class=HTMLResponse,
            responses={200: {"content": {"application/json": {}}}})
def owner_diagnostics(
    request: Request,
    download: bool = False,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    vm = svc.get_index_vm(db)
    cfg = get_settings()
    observed_at = now_utc()
    if download:
        # A support summary, not a settings dump or a database/original integrity attestation.
        return JSONResponse({
            "observed_at": observed_at.isoformat(),
            "backend_version": vm.backend_version,
            "identity_schema": vm.identity_schema,
            "database_reads": "completed",
            "upload_directory": "present" if vm.upload_dir_status == "ok" else "missing",
            "owner_console": vm.owner_console_status,
            "managed_ledger_counts": {"pending": vm.pending_count, "confirmed": vm.confirmed_count,
                "active_devices": vm.active_device_count, "active_upload_links": vm.active_upload_link_count},
            "recognition_configuration": {"provider": cfg.ocr_provider, "automatic": cfg.ocr_auto_run,
                "max_upload_size_mb": cfg.max_upload_size_mb},
            "http_bootstrap_enabled": cfg.enable_http_bootstrap,
            "scope": "本次数据库读取已完成；目录仅检查是否存在。未验证目录写入、原件完整性或识别引擎可用性。",
        }, headers={"Content-Disposition": 'attachment; filename="ticketbox-diagnostics.json"',
                    "Cache-Control": "no-store"})
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["observed_at"] = observed_at
    ctx["ocr_provider"] = cfg.ocr_provider
    ctx["ocr_auto_run"] = cfg.ocr_auto_run
    ctx["enable_http_bootstrap"] = cfg.enable_http_bootstrap
    ctx["max_upload_size_mb"] = cfg.max_upload_size_mb
    return templates.TemplateResponse(request=request, name="diagnostics.html", context=ctx)
