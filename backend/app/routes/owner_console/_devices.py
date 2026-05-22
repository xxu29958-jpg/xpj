"""Owner Console device list + per-device actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc

router = APIRouter(prefix="/owner", tags=["owner-console"])


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


@router.post("/devices/{public_id}/delete", response_class=HTMLResponse)
def owner_delete_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_delete_device(db, public_id, current_device_public_id="")
    return RedirectResponse(url="/owner/devices", status_code=303)
