"""Account settings consume the same device commands as the mobile client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import LedgerOption, _base_ctx, _read_ui_theme, templates
from app.services import owner_device_service
from app.services.identity_service import PairingCodeResult
from app.services.ledger_service import list_ledgers_for_account
from app.services.spending_contract_service import accounting_datetime_label
from app.tenants import AuthContext, SessionPrincipal
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web/settings", tags=["web-app"])
_MESSAGES = {"renamed": "设备名称已保存。", "revoked": "设备已停用，原登录和上传链接已失效。",
             "deleted": "已移除停用的设备记录，账本中的记录仍然保留。"}
_PLATFORMS = {"web": "浏览器", "android": "Android", "iphone": "iPhone", "desktop": "桌面管理器"}


@dataclass(frozen=True)
class DeviceForm:
    public_id: str = ""
    name: str = ""


def _principal(request: Request) -> SessionPrincipal:
    principal = getattr(request.state, "web_session_principal", None)
    if not isinstance(principal, SessionPrincipal):
        raise AppError("invalid_token", "请先连接当前账户，再管理自己的设备。", status_code=401)
    return principal


def _settings_context(request: Request, db: Session, principal: SessionPrincipal) -> dict:
    auth = getattr(request.state, "web_session_auth", None)
    if isinstance(auth, AuthContext):
        options = [LedgerOption(item.ledger_id, item.name, item.role, item.is_default, 0, 0)
                   for item in list_ledgers_for_account(db, account_id=principal.account_id)]
        if getattr(request.state, "web_session_platform", "") == "desktop":
            options = [option for option in options if option.ledger_id == auth.ledger_id]
        if any(option.ledger_id == auth.ledger_id for option in options):
            return {**_base_ctx(request, db=db, options=options, selected_ledger_id=auth.ledger_id, page_title="设置与设备"),
                    "can_pair_devices": True}
    return {"request": request, "backend_version": BACKEND_VERSION, "asset_version": STATIC_ASSET_VERSION,
            "page_title": "设置与设备", "ui_theme": _read_ui_theme(request), "account_without_ledger": True,
            "selected_ledger_id": "", "selected_ledger_name": principal.account_name,
            "selected_ledger_role": "", "ledger_options": [], "can_write": False, "can_pair_devices": False}


def _moment(value: str | None) -> str:
    return accounting_datetime_label(datetime.fromisoformat(value)) if value else "尚无记录"


def _render_settings(request: Request, db: Session, *, error: str = "", status_code: int = 200,
                     form: DeviceForm = DeviceForm(), pairing: PairingCodeResult | None = None) -> HTMLResponse:
    principal = _principal(request)
    devices = owner_device_service.list_my_devices(db, principal)
    current_platform = next((item.summary.platform for item in devices if item.is_current), "")
    ctx = _settings_context(request, db, principal)
    ctx.update(principal=principal, devices=devices, current_platform=current_platform, platforms=_PLATFORMS,
               device_form=form, error=error, pairing=pairing, moment=_moment,
               message=_MESSAGES.get(request.query_params.get("done", ""), ""))
    return templates.TemplateResponse(request=request, name="settings.html", context=ctx, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def web_settings(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render_settings(request, db)


def _device_response(request: Request, db: Session, *, command: Callable[[], object], done: str,
                     form: DeviceForm = DeviceForm()) -> Response:
    try:
        command()
    except AppError as exc:
        db.rollback()
        return _render_settings(request, db, error=exc.message, status_code=exc.status_code, form=form)
    return RedirectResponse(url=f"/web/settings?done={done}", status_code=303)


def _confirmed(value: str) -> None:
    if value != "yes":
        raise AppError("invalid_request", "请先勾选确认这次设备操作的影响。", status_code=422)


@router.post("/devices/{public_id}/rename")
def web_device_rename(request: Request, public_id: str, device_name: str = Form(default=""),
                      db: Session = Depends(get_db)) -> Response:
    principal = _principal(request)
    return _device_response(request, db, done="renamed", form=DeviceForm(public_id, device_name),
        command=lambda: owner_device_service.rename_my_device(db, principal, public_id=public_id, new_name=device_name))


@router.post("/devices/{public_id}/revoke")
def web_device_revoke(request: Request, public_id: str, confirmed: str = Form(default=""),
                      db: Session = Depends(get_db)) -> Response:
    principal = _principal(request)

    def revoke() -> object:
        _confirmed(confirmed)
        return owner_device_service.revoke_my_device(db, principal, public_id=public_id)

    return _device_response(request, db, command=revoke, done="revoked")


@router.post("/devices/{public_id}/delete")
def web_device_delete(request: Request, public_id: str, confirmed: str = Form(default=""),
                      db: Session = Depends(get_db)) -> Response:
    principal = _principal(request)

    def remove() -> None:
        _confirmed(confirmed)
        owner_device_service.delete_my_device(db, principal, public_id=public_id)

    return _device_response(request, db, command=remove, done="deleted")


@router.post("/devices/pairing-codes", response_class=HTMLResponse)
def web_device_pairing(request: Request, recovery_device_public_id: str = Form(default=""),
                       confirmed: str = Form(default=""), db: Session = Depends(get_db)) -> HTMLResponse:
    _principal(request)
    try:
        auth = getattr(request.state, "web_session_auth", None)
        if not isinstance(auth, AuthContext):
            raise AppError("permission_denied", "请先选择一个仍有访问权限的账本，再生成连接码。", status_code=409)
        if recovery_device_public_id:
            _confirmed(confirmed)
        pairing = owner_device_service.create_my_pairing_code(db, auth, device_name_hint=None, ttl_minutes=15,
            recovery_device_public_id=recovery_device_public_id or None)
    except AppError as exc:
        db.rollback()
        return _render_settings(request, db, error=exc.message, status_code=exc.status_code)
    return _render_settings(request, db, pairing=pairing)
