"""/web merchant governance routes.

The first v0.7 web slice exposes merchant aliases only. It does not merge
historical expenses or overwrite the original merchant text.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
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
    parse_form_updated_at_token,
    templates,
)
from app.services.merchant_alias_service import (
    create_merchant_alias,
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    update_merchant_alias,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/merchants", response_class=HTMLResponse)
def web_merchants(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    aliases = list_merchant_aliases(db, selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["aliases"] = aliases
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request,
        name="merchants.html",
        context=ctx,
    )


@router.post("/merchants/aliases/create", response_class=HTMLResponse)
def web_merchant_alias_create(
    request: Request,
    canonical_merchant: str = Form(""),
    alias: str = Form(""),
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        item = create_merchant_alias(
            db,
            tenant_id=selected_id,
            canonical_merchant=canonical_merchant,
            alias=alias,
        )
        msg = f"已新增别名：{item.alias} → {item.canonical_merchant}"
    except AppError as exc:
        msg = "新增失败：" + exc.message
    return _web_redirect("/web/merchants", selected_id, msg=msg)


@router.post("/merchants/aliases/{public_id}/toggle", response_class=HTMLResponse)
def web_merchant_alias_toggle(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    expected_updated_at: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 PR-2e: /web mutate forms carry the hidden ``expected_updated_at``
    # so cross-window race (PR-4 cookie sessions reach /web from public host
    # too) surfaces as 409 → "页面已过期/已在其它端修改" UX instead of silently
    # toggling a stale snapshot.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_updated_at_token(expected_updated_at)
    if parsed is None:
        return _web_redirect(
            "/web/merchants",
            selected_id,
            msg="页面已过期，请刷新后重试。",
        )
    try:
        item = get_merchant_alias(db, tenant_id=selected_id, public_id=public_id)
        # Use the refreshed instance returned by update_merchant_alias so
        # the success message reflects the post-write enabled state.
        # Reading ``item.enabled`` after the helper depends on SQLAlchemy
        # ``synchronize_session="auto"`` having run, which is not a
        # contract — the helper is the authoritative read.
        updated = update_merchant_alias(
            db, item, expected_updated_at=parsed, enabled=not item.enabled
        )
        msg = f"别名 [{updated.alias}] {'已启用' if updated.enabled else '已停用'}。"
    except AppError as exc:
        msg = (
            "别名已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
    return _web_redirect("/web/merchants", selected_id, msg=msg)


@router.post("/merchants/aliases/{public_id}/delete", response_class=HTMLResponse)
def web_merchant_alias_delete(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    expected_updated_at: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 PR-2e: see web_merchant_alias_toggle.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_updated_at_token(expected_updated_at)
    if parsed is None:
        return _web_redirect(
            "/web/merchants",
            selected_id,
            msg="页面已过期，请刷新后重试。",
        )
    try:
        item = get_merchant_alias(db, tenant_id=selected_id, public_id=public_id)
        alias = item.alias
        delete_merchant_alias(db, item, expected_updated_at=parsed)
        msg = f"别名 [{alias}] 已删除。"
    except AppError as exc:
        msg = (
            "别名已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
    return _web_redirect("/web/merchants", selected_id, msg=msg)
