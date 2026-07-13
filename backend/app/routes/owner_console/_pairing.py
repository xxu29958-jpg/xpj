"""Owner Console pairing-code page (GET form + POST submit)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.installation_health_service import (
    configured_mobile_endpoint_url,
    owner_recovery_message,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _runtime_recovery_message() -> str:
    return owner_recovery_message(get_settings().owner_recovery_channel)


def _add_android_connection_context(context: dict[str, object]) -> None:
    context["android_server_url"] = configured_mobile_endpoint_url(get_settings().public_base_url)


@router.get("/pairing", response_class=HTMLResponse)
def owner_pairing_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["pairing_result"] = None
    choices = svc.list_console_ledger_choices(db)
    default_id = svc.get_default_ledger_id(db)
    selected_id = default_id if default_id else (choices[0].ledger_id if choices else None)
    ctx["ledger_choices"] = choices
    ctx["ledger_id"] = selected_id
    ctx["selected_ledger_id"] = selected_id
    ctx["owner_recovery_message"] = _runtime_recovery_message()
    _add_android_connection_context(ctx)
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


@router.post("/pairing", response_class=HTMLResponse)
def owner_pairing_post(
    request: Request,
    ledger_id: str = Form(...),
    ttl_minutes: int = Form(default=15),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    choices = svc.list_console_ledger_choices(db)
    account_id = svc.get_owner_account_id(db)
    valid_ids = {c.ledger_id for c in choices}
    if not choices or account_id is None or ledger_id not in valid_ids:
        ctx = _base(request, db)
        ctx["pairing_result"] = None
        ctx["ledger_choices"] = choices
        ctx["ledger_id"] = None
        ctx["selected_ledger_id"] = ledger_id if ledger_id in valid_ids else None
        ctx["owner_recovery_message"] = _runtime_recovery_message()
        _add_android_connection_context(ctx)
        ctx["error"] = (
            _runtime_recovery_message()
            if not choices
            else "请选择一个有权限的账本。"
        )
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    android_server_url = configured_mobile_endpoint_url(get_settings().public_base_url)
    if android_server_url is None:
        ctx = _base(request, db)
        ctx["pairing_result"] = None
        ctx["ledger_choices"] = choices
        ctx["ledger_id"] = ledger_id
        ctx["selected_ledger_id"] = ledger_id
        ctx["owner_recovery_message"] = _runtime_recovery_message()
        ctx["android_server_url"] = None
        ctx["error"] = "请先在设置中完成手机连接配置，再生成绑定码。"
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    result = svc.do_create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)
    ctx = _base(request, db)
    ctx["pairing_result"] = result
    ctx["ledger_choices"] = choices
    ctx["ledger_id"] = ledger_id
    ctx["selected_ledger_id"] = ledger_id
    ctx["error"] = None
    ctx["android_server_url"] = android_server_url
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
