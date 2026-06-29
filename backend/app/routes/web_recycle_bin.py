"""ADR-0051 /web current-ledger recycle-bin page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.owner_console_service import get_owner_account_id
from app.services.recycle_bin_service import (
    list_recycle_bin_items,
    restore_recycle_bin_item,
)

router = APIRouter(prefix="/web/recycle-bin", tags=["web"])


@router.get("", response_class=HTMLResponse)
def page_recycle_bin(
    request: Request,
    ledger_id: str | None = Query(default=None),
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    can_write = True
    try:
        _require_selected_ledger_write(options, selected)
    except AppError:
        can_write = False
    listing = list_recycle_bin_items(db, tenant_id=selected)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected,
        page_title="回收站",
    )
    ctx.update(
        recycle_bin=listing,
        can_write=can_write,
        message=message,
        error=error,
    )
    return templates.TemplateResponse(
        request=request,
        name="recycle_bin.html",
        context=ctx,
    )


@router.post("/restore")
def post_restore_recycle_bin(
    request: Request,
    ledger_id: str | None = Form(default=None),
    kind: str = Form(default=""),
    resource_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    db: Session = Depends(get_db),
    _local: None = LocalOnly,
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    _require_selected_ledger_write(options, selected)
    actor_id = _actor_account_id(request, db)
    parsed = parse_form_row_version_token(expected_row_version)
    try:
        message = restore_recycle_bin_item(
            db,
            tenant_id=selected,
            kind=kind,
            resource_id=resource_id,
            expected_row_version=parsed,
            actor_account_id=actor_id,
        )
    except AppError as exc:
        if exc.error in {"state_conflict", "invalid_request"}:
            return _web_redirect(
                "/web/recycle-bin",
                selected,
                error="页面已过期，请刷新后重新操作。",
            )
        raise
    return _web_redirect("/web/recycle-bin", selected, message=message)


def _actor_account_id(request: Request, db: Session) -> int | None:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.account_id
    return get_owner_account_id(db)
