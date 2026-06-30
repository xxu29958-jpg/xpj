"""/web merchant governance routes.

The web surface exposes merchant catalog management and merchant aliases. It
does not merge historical expenses or overwrite the original merchant text.
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
    parse_form_row_version_token,
    templates,
)
from app.services.merchant_alias_service import (
    create_merchant_alias,
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    undo_delete_merchant_alias,
    update_merchant_alias,
)
from app.services.merchant_catalog_service import (
    create_merchant_catalog,
    delete_merchant_catalog,
    get_merchant_catalog,
    list_merchant_catalog,
    update_merchant_catalog,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/merchants", response_class=HTMLResponse)
def web_merchants(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    undo: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    catalog = list_merchant_catalog(db, tenant_id=selected_id, include_hidden=True)
    aliases = list_merchant_aliases(db, selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["catalog"] = catalog
    ctx["aliases"] = aliases
    ctx["flash_message"] = msg
    # ADR-0038 undo: a just-deleted alias's public_id, so the flash can offer a
    # 5s 撤销 affordance that POSTs to the undo route.
    ctx["undo_public_id"] = undo
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request,
        name="merchants.html",
        context=ctx,
    )


@router.post("/merchants/catalog/create", response_class=HTMLResponse)
def web_merchant_catalog_create(
    request: Request,
    display_name: str = Form(""),
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        item = create_merchant_catalog(
            db,
            tenant_id=selected_id,
            display_name=display_name,
        )
        msg = f"已新增商家：{item.display_name}"
    except AppError as exc:
        msg = "新增失败：" + exc.message
    return _web_redirect("/web/merchants", selected_id, msg=msg)


@router.post("/merchants/catalog/{public_id}/toggle", response_class=HTMLResponse)
def web_merchant_catalog_toggle(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/merchants",
            selected_id,
            msg="页面已过期，请刷新后重试。",
        )
    try:
        item = get_merchant_catalog(db, tenant_id=selected_id, public_id=public_id)
        next_status = "hidden" if item.status == "active" else "active"
        updated = update_merchant_catalog(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
            status=next_status,
        )
        msg = f"商家「{updated.display_name}」{'已显示' if updated.status == 'active' else '已隐藏'}。"
    except AppError as exc:
        msg = (
            "商家已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
    return _web_redirect("/web/merchants", selected_id, msg=msg)


@router.post("/merchants/catalog/{public_id}/delete", response_class=HTMLResponse)
def web_merchant_catalog_delete(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/merchants",
            selected_id,
            msg="页面已过期，请刷新后重试。",
        )
    try:
        item = get_merchant_catalog(db, tenant_id=selected_id, public_id=public_id)
        display_name = item.display_name
        delete_merchant_catalog(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
        )
    except AppError as exc:
        msg = (
            "商家已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
        return _web_redirect("/web/merchants", selected_id, msg=msg)
    return _web_redirect(
        "/web/merchants",
        selected_id,
        msg=f"商家「{display_name}」已移入回收站。",
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
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 PR-2e: /web mutate forms carry the hidden ``expected_row_version``
    # so cross-window race (PR-4 cookie sessions reach /web from public host
    # too) surfaces as 409 → "页面已过期/已在其它端修改" UX instead of silently
    # toggling a stale snapshot.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
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
            db, item, expected_row_version=parsed, enabled=not item.enabled
        )
        msg = f"别名「{updated.alias}」{'已启用' if updated.enabled else '已停用'}。"
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
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 PR-2e: see web_merchant_alias_toggle.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/merchants",
            selected_id,
            msg="页面已过期，请刷新后重试。",
        )
    try:
        item = get_merchant_alias(db, tenant_id=selected_id, public_id=public_id)
        alias = item.alias
        delete_merchant_alias(db, item, expected_row_version=parsed)
    except AppError as exc:
        msg = (
            "别名已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
        return _web_redirect("/web/merchants", selected_id, msg=msg)
    # ADR-0038 undo: pass the soft-deleted public_id so the page renders a 5s
    # 撤销 banner; the row is recoverable until cleanup purges it.
    return _web_redirect(
        "/web/merchants", selected_id, msg=f"别名「{alias}」已删除。", undo=public_id
    )


@router.post("/merchants/aliases/{public_id}/undo", response_class=HTMLResponse)
def web_merchant_alias_undo(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0038 undo: restore a soft-deleted alias from the 5s banner. No
    # ``expected_row_version`` — this restores the row the operator just deleted
    # (near-zero contention inside the window). 404 once cleanup has purged it.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        item = undo_delete_merchant_alias(db, tenant_id=selected_id, public_id=public_id)
        msg = f"已恢复别名 「{item.alias}」。"
    except AppError as exc:
        msg = (
            "无法恢复：该别名已被永久清理或不存在。"
            if exc.error == "merchant_alias_not_found"
            else exc.message
        )
    return _web_redirect("/web/merchants", selected_id, msg=msg)
