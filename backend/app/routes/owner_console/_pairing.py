"""Owner Console pairing-code page (GET form + POST submit)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError, retain_handled_error
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc
from app.services.installation_health_service import (
    configured_mobile_endpoint_url,
    owner_recovery_message,
)

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _add_connection_context(context: dict[str, object]) -> None:
    settings = get_settings()
    context["android_server_url"] = configured_mobile_endpoint_url(settings.public_base_url)
    context["owner_recovery_message"] = owner_recovery_message(settings.owner_recovery_channel)


def _add_recovery_context(
    context: dict[str, object],
    db: Session,
    *,
    account_id: int | None,
    selected_public_id: str | None,
) -> bool:
    choices = svc.list_recovery_device_choices(db, account_id=account_id)
    valid_ids = {choice.public_id for choice in choices}
    selected = (selected_public_id or "").strip()
    context["recovery_devices"] = choices
    context["selected_recovery_device_id"] = selected
    context["recovery_selection_unavailable"] = bool(selected and selected not in valid_ids)
    return not selected or selected in valid_ids


@router.get("/pairing", response_class=HTMLResponse)
def owner_pairing_get(
    request: Request,
    recovery_device: str | None = None,
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
    ctx["submitted_ttl_minutes"] = 15
    recovery_is_valid = _add_recovery_context(
        ctx,
        db,
        account_id=svc.get_owner_account_id(db),
        selected_public_id=recovery_device,
    )
    if not recovery_is_valid:
        ctx["error"] = "要恢复的设备不存在，请重新选择。"
    _add_connection_context(ctx)
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


@router.post("/pairing", response_class=HTMLResponse)
def owner_pairing_post(
    request: Request,
    ledger_id: str = Form(...),
    ttl_minutes: int = Form(default=15),
    recovery_device_public_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    choices = svc.list_console_ledger_choices(db)
    account_id = svc.get_owner_account_id(db)
    valid_ids = {c.ledger_id for c in choices}
    ctx = _base(request, db)
    recovery_is_valid = _add_recovery_context(
        ctx,
        db,
        account_id=account_id,
        selected_public_id=recovery_device_public_id,
    )
    ctx.update(
        pairing_result=None,
        ledger_choices=choices,
        ledger_id=ledger_id if ledger_id in valid_ids else None,
        selected_ledger_id=ledger_id,
        submitted_ttl_minutes=ttl_minutes,
        error=None,
    )
    _add_connection_context(ctx)
    if not choices or account_id is None or ledger_id not in valid_ids or not recovery_is_valid:
        if not choices:
            ctx["error"] = ctx["owner_recovery_message"]
        elif not recovery_is_valid:
            ctx["error"] = "要恢复的设备不存在，请重新选择。"
        else:
            ctx["error"] = "请选择一个有权限的账本。"
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    try:
        ctx["pairing_result"] = svc.do_create_pairing_code(
            db,
            ledger_id=ledger_id,
            account_id=account_id,
            ttl_minutes=ttl_minutes,
            recovery_device_public_id=recovery_device_public_id or None,
        )
    except AppError as exc:
        db.rollback()
        if exc.status_code >= 500:
            retain_handled_error(request, exc)
        ctx["error"] = exc.message
        return templates.TemplateResponse(
            request=request, name="pairing.html", context=ctx, status_code=exc.status_code
        )
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
