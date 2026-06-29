"""Owner Console unified recycle bin (ADR-0051 first implementation)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import owner_console_service as svc

router = APIRouter(prefix="/owner", tags=["owner"])


def _redirect(*, msg: str = "", error: str = "") -> RedirectResponse:
    params = []
    if msg:
        params.append("msg=" + quote(msg))
    if error:
        params.append("error=" + quote(error))
    suffix = ("?" + "&".join(params)) if params else ""
    return RedirectResponse(url="/owner/recycle-bin" + suffix, status_code=303)


def _parse_token(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@router.get("/recycle-bin", response_class=HTMLResponse)
def owner_recycle_bin_get(
    request: Request,
    msg: str = "",
    error: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["recycle_bin"] = svc.get_recycle_bin_vm(db)
    ctx["flash_message"] = msg
    ctx["error"] = error
    return templates.TemplateResponse(
        request=request,
        name="recycle_bin.html",
        context=ctx,
    )


@router.post("/recycle-bin/restore", response_class=HTMLResponse)
def owner_recycle_bin_restore(
    kind: str = Form(...),
    ledger_id: str = Form(default=""),
    resource_id: str = Form(...),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        msg = svc.restore_recycle_bin_item(
            db,
            kind=kind,
            ledger_id=ledger_id,
            resource_id=resource_id,
            expected_row_version=_parse_token(expected_row_version),
        )
    except AppError as exc:
        if exc.error in {
            "state_conflict",
            "rule_not_found",
            "merchant_alias_not_found",
            "tag_undo_not_found",
            "tag_not_found",
        }:
            return _redirect(error="这条记录已经变化或过了恢复窗口，请刷新后再看。")
        return _redirect(error=exc.message)
    return _redirect(msg=msg)
