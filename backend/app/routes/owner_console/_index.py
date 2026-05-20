"""Owner Console index page + rule-applications audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, logger, templates
from app.services import owner_console_service as svc


router = APIRouter(prefix="/owner", tags=["owner-console"])


@router.get("", response_class=HTMLResponse)
def owner_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["ledger_health"] = svc.list_ledger_health(db)
    ctx["rule_audit"] = svc.get_rule_application_audit(db, ledger_id=None, limit=5)
    try:
        from app.services import windows_task_status_service as wts

        ctx["windows_tasks"] = wts.list_windows_tasks()
    except Exception:  # noqa: BLE001 — index must not 500 if Windows task lookup fails
        logger.exception("owner_console index: list_windows_tasks failed")
        ctx["windows_tasks"] = []
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


@router.get("/rule-applications", response_class=HTMLResponse)
def owner_rule_applications(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    audit = svc.get_rule_application_audit(db, ledger_id=ledger_id, limit=20)
    ctx = _base(request, db)
    ctx["rule_audit"] = audit
    return templates.TemplateResponse(request=request, name="rule_applications.html", context=ctx)
