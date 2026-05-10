"""Owner Console routes — local-only HTML admin UI.

All endpoints check that the request comes from the loopback address
(127.0.0.1 or ::1). Remote or Cloudflare-forwarded requests are rejected with
403. This is *not* a public admin backend.

Navigation:
    GET  /owner                     — dashboard / index
    GET  /owner/devices             — device list
    POST /owner/devices/{id}/revoke — revoke device
    POST /owner/devices/{id}/rename — rename device
    GET  /owner/pairing             — generate pairing code
    POST /owner/pairing             — create and display new code
    GET  /owner/upload-links        — upload link list
    POST /owner/upload-links        — create new upload link
    POST /owner/upload-links/{id}/rotate  — rotate key (one-shot reveal)
    POST /owner/upload-links/{id}/revoke  — revoke link
    GET  /owner/diagnostics         — diagnostics page
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.network_boundary import require_owner_console_local
from app.services import owner_console_service as svc
from app.version import BACKEND_VERSION

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "owner"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _require_local(request: Request) -> None:
    """Block non-loopback clients.

    v0.3-rc1-preflight: also reject public Host headers (Cloudflare Tunnel
    forwards to loopback so the TCP peer alone is insufficient).
    """
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


# ── helpers ─────────────────────────────────────────────────────────────────

def _base(request: Request, db: Session) -> dict:
    """Common template context injected into every page."""
    cfg = get_settings()
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"
    return {
        "backend_version": BACKEND_VERSION,
        "upload_dir_status": upload_status,
    }


# ── index ────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def owner_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


# ── devices ──────────────────────────────────────────────────────────────────

@router.get("/devices", response_class=HTMLResponse)
def owner_devices(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    devices = svc.get_devices(db)
    ctx = _base(request, db)
    ctx["devices"] = devices
    return templates.TemplateResponse(request=request, name="devices.html", context=ctx)


@router.post("/devices/{public_id}/revoke", response_class=HTMLResponse)
def owner_revoke_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # Owner Console does not track which device "this" console session is from;
    # supply an empty string so the service rejects self-revoke only when the
    # admin uses the API directly with a token.
    svc.do_revoke_device(db, public_id, current_device_public_id="")
    return RedirectResponse(url="/owner/devices", status_code=303)


@router.post("/devices/{public_id}/rename", response_class=HTMLResponse)
def owner_rename_device(
    public_id: str,
    request: Request,
    device_name: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_rename_device(db, public_id, device_name)
    return RedirectResponse(url="/owner/devices", status_code=303)


# ── pairing ──────────────────────────────────────────────────────────────────

@router.get("/pairing", response_class=HTMLResponse)
def owner_pairing_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["pairing_result"] = None
    ledger_id = svc.get_default_ledger_id(db)
    ctx["ledger_id"] = ledger_id
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


@router.post("/pairing", response_class=HTMLResponse)
def owner_pairing_post(
    request: Request,
    ttl_minutes: int = Form(default=15),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ledger_id = svc.get_default_ledger_id(db)
    account_id = svc.get_owner_account_id(db)
    if ledger_id is None or account_id is None:
        ctx = _base(request, db)
        ctx["pairing_result"] = None
        ctx["ledger_id"] = None
        ctx["error"] = "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    result = svc.do_create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)
    ctx = _base(request, db)
    ctx["pairing_result"] = result
    ctx["ledger_id"] = ledger_id
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


# ── upload links ─────────────────────────────────────────────────────────────

@router.get("/upload-links", response_class=HTMLResponse)
def owner_upload_links_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links", response_class=HTMLResponse)
def owner_upload_links_create(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ledger_id = svc.get_default_ledger_id(db)
    account_id = svc.get_owner_account_id(db)
    if ledger_id is None or account_id is None:
        ctx = _base(request, db)
        ctx["links"] = []
        ctx["new_secret"] = None
        ctx["error"] = "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
        return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)
    cfg = get_settings()
    tz = (cfg.ocr_default_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    _summary, secret = svc.do_create_upload_link(
        db, ledger_id=ledger_id, admin_account_id=account_id, default_timezone=tz
    )
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/rotate", response_class=HTMLResponse)
def owner_upload_links_rotate(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _summary, secret = svc.do_rotate_upload_link(db, public_id)
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/revoke", response_class=HTMLResponse)
def owner_upload_links_revoke(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_revoke_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)


# ── diagnostics ──────────────────────────────────────────────────────────────

@router.get("/diagnostics", response_class=HTMLResponse)
def owner_diagnostics(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    cfg = get_settings()
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["ocr_provider"] = cfg.ocr_provider
    ctx["ocr_auto_run"] = cfg.ocr_auto_run
    ctx["enable_http_bootstrap"] = cfg.enable_http_bootstrap
    ctx["max_upload_size_mb"] = cfg.max_upload_size_mb
    return templates.TemplateResponse(request=request, name="diagnostics.html", context=ctx)
