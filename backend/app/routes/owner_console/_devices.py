"""Owner Console device list + per-device actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError, retain_handled_error
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _render_devices(
    request: Request,
    db: Session,
    *,
    error: AppError | None = None,
    failed_device_id: str | None = None,
    submitted_name: str | None = None,
) -> HTMLResponse:
    inventory = svc.get_devices(db)
    ctx = _base(request, db)
    ctx.update(
        devices=inventory.devices,
        ended_browser_sessions=inventory.ended_browser_sessions,
        error=error.message if error else None,
        failed_device_id=failed_device_id,
        submitted_device_name=submitted_name,
    )
    if error and error.status_code >= 500:
        retain_handled_error(request, error)
    return templates.TemplateResponse(
        request=request, name="devices.html", context=ctx, status_code=error.status_code if error else 200
    )


@router.get("/devices", response_class=HTMLResponse)
def owner_devices(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return _render_devices(request, db)


@router.post("/devices/{public_id}/revoke", response_class=HTMLResponse)
def owner_revoke_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    # Owner Console does not track which device "this" console session is from;
    # supply an empty string so the service rejects self-revoke only when the
    # admin uses the API directly with a token.
    try:
        svc.do_revoke_device(db, public_id, current_device_public_id="")
    except AppError as exc:
        db.rollback()
        return _render_devices(request, db, error=exc, failed_device_id=public_id)
    return RedirectResponse(url="/owner/devices", status_code=303)


@router.post("/devices/{public_id}/rename", response_class=HTMLResponse)
def owner_rename_device(
    public_id: str,
    request: Request,
    device_name: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    try:
        svc.do_rename_device(db, public_id, device_name)
    except AppError as exc:
        db.rollback()
        return _render_devices(request, db, error=exc, failed_device_id=public_id, submitted_name=device_name)
    return RedirectResponse(url="/owner/devices", status_code=303)


@router.post("/devices/{public_id}/delete", response_class=HTMLResponse)
def owner_delete_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    try:
        svc.do_delete_device(db, public_id, current_device_public_id="")
    except AppError as exc:
        db.rollback()
        return _render_devices(request, db, error=exc, failed_device_id=public_id)
    return RedirectResponse(url="/owner/devices", status_code=303)
