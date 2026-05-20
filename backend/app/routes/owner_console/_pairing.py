"""Owner Console pairing-code page (GET form + POST submit)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc


router = APIRouter(prefix="/owner", tags=["owner-console"])


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
        ctx["error"] = (
            "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
            if not choices
            else "请选择一个有权限的账本。"
        )
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    result = svc.do_create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)
    ctx = _base(request, db)
    ctx["pairing_result"] = result
    ctx["ledger_choices"] = choices
    ctx["ledger_id"] = ledger_id
    ctx["selected_ledger_id"] = ledger_id
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
