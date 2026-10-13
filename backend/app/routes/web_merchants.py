"""/web merchant governance routes.

The web surface exposes merchant catalog management and merchant aliases. It
does not merge historical expenses or overwrite the original merchant text.
"""

from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_merchant_catalog import (
    MerchantCommandForm,
    catalog_form_context,
    catalog_payload,
    review_catalog_form,
)
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import MerchantAliasCreateRequest, MerchantCatalogCreateRequest
from app.services.merchant_alias_service import (
    delete_merchant_alias,
    get_merchant_alias,
    list_merchant_aliases,
    undo_delete_merchant_alias,
    update_merchant_alias,
)
from app.services.merchant_catalog_command_service import submit_catalog_command
from app.services.merchant_catalog_service import list_merchant_catalog
from app.services.merchant_creation_service import submit_merchant_creation

router = APIRouter(prefix="/web", tags=["web"])


class MerchantCreateForm(BaseModel):
    ledger_id: str = ""
    display_name: str = ""
    canonical_merchant: str = ""
    alias: str = ""
    search: str = ""
    status: str = "all"
    merchant: str = ""
    draft_scope: str = ""
    idempotency_key: str = ""
    review_new: bool = False


def _stale_catalog_redirect(selected_id: str) -> RedirectResponse:
    return _web_redirect("/web/merchants", selected_id, msg="页面已过期，请刷新后重试。")


def _catalog_conflict_message(exc: AppError) -> str:
    if exc.error == "not_found":
        return "商家不存在或已被删除。"
    if exc.error != "state_conflict":
        return exc.message
    details = exc.details or {}
    conflict_name = details.get("conflict_merchant_display_name")
    if isinstance(conflict_name, str) and conflict_name:
        return f"商家名已被「{conflict_name}」占用；如需归并请使用『合并』。"
    if "conflict_alias_public_id" in details:
        return "来源商家名已被现有别名占用，无法自动创建来源别名；请先处理该别名，或选择不创建别名。"
    return "商家已在其它端被修改，或仍被启用别名/固定支出引用；请核对最新资料后再确认。"


def _catalog_rename_error_message(exc: AppError) -> str:
    if exc.error == "invalid_request":
        return "请填写商家名称，最多255个字。"
    if exc.error == "state_conflict" and not exc.details:
        return "商家状态已变化，或仍被启用别名/固定支出引用；请根据当前信息重试。"
    return _catalog_conflict_message(exc)


def _merchant_directory_context(request: Request, ctx: dict) -> dict:
    """Keep alias-aware filtering and the return location together."""
    query = request.query_params
    status = query.get("status", "all")
    status = status if status in {"all", "active", "hidden", "merged"} else "all"
    search = query.get("search", "").strip()[:255]
    term = search.casefold()
    matching_keys = {item.canonical_key for item in ctx["aliases"]
                     if term in item.alias.casefold() or term in item.canonical_merchant.casefold()}
    visible = [item for item in ctx["catalog"]
               if (status == "all" or item.status == status)
               and (not term or term in item.display_name.casefold() or item.merchant_key in matching_keys)]
    directory_query = urlencode({"ledger_id": ctx["selected_ledger_id"], "status": status, "search": search})
    return {"merchant_search": search, "merchant_status": status, "visible_catalog": visible,
            "directory_href": "/web/merchants?" + directory_query}


def _merchant_view_context(request: Request, ctx: dict) -> dict:
    """Project the existing directory and independent aliases into focused tasks."""
    query = request.query_params
    view = query.get("view", "directory")
    if view not in {"directory", "merchant", "new", "aliases"}:
        view = "directory"
    public_id = query.get("merchant", "")
    if ctx["catalog_create_error"]:
        view = "new"
    if ctx["alias_create_error"]:
        view = "aliases"
    selected = next((item for item in ctx["catalog"] if item.public_id == public_id), None)
    return {"merchant_view": view, "selected_merchant": selected,
            **_merchant_directory_context(request, ctx),
            "visible_aliases": [item for item in ctx["aliases"]
                                if view != "merchant" or selected and item.canonical_key == selected.merchant_key]}


def _render_merchants(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    msg: str = "",
    undo: str = "",
    catalog_create_error: str = "",
    catalog_create_value: str = "",
    catalog_create_recycle: bool = False,
    alias_create_error: str = "",
    alias_create_draft: dict[str, str] | None = None,
    command_kind: str = "",
    command_form: MerchantCommandForm | None = None,
    command_result: str = "",
    command_error: str = "",
    creation_kind: str = "",
    creation_form: MerchantCreateForm | None = None,
    creation_result: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
    )
    ctx.update(
        catalog=list_merchant_catalog(
            db,
            tenant_id=selected_id,
            include_hidden=True,
        ),
        aliases=list_merchant_aliases(db, selected_id),
        flash_message=msg,
        undo_public_id=undo,
        catalog_create_error=catalog_create_error,
        catalog_create_value=catalog_create_value,
        catalog_create_recycle=catalog_create_recycle,
        alias_create_error=alias_create_error,
        alias_create_draft=alias_create_draft or {},
        q="?ledger_id=" + selected_id,
    )
    ctx.update(_merchant_view_context(request, ctx))
    scope = browser_draft_scope(db, request)
    initial = MerchantCreateForm(ledger_id=selected_id, search=ctx["merchant_search"], status=ctx["merchant_status"],
        merchant=request.query_params.get("merchant", ""), draft_scope=json.dumps(scope) if scope else "")
    ctx.update(merchant_draft_scope=scope, creation_kind=creation_kind, creation_result=creation_result,
        catalog_form=creation_form if creation_kind == "catalog" else initial.model_copy(update={"idempotency_key": str(uuid4())}),
        alias_form=creation_form if creation_kind == "alias" else initial.model_copy(update={"idempotency_key": str(uuid4())}))
    if creation_form:
        ctx.update(merchant_view="new" if creation_kind == "catalog" else "aliases",
            directory_href="/web/merchants?" + urlencode({"ledger_id": creation_form.ledger_id,
                "search": creation_form.search, "status": creation_form.status}))
    ctx.update(catalog_form_context(request, ctx, scope, kind=command_kind, values=command_form,
        result=command_result, error=command_error))
    return templates.TemplateResponse(
        request=request,
        name="merchants.html",
        context=ctx,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


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
    return _render_merchants(
        request,
        db,
        options=options,
        selected_id=selected_id,
        msg=msg,
        undo=undo,
    )


def _merchant_creation_failure(request: Request, db: Session, *, kind: str,
    values: MerchantCreateForm, options: list, selected_id: str, exc: AppError) -> Response:
    """Present the refusal beside its original input for both browser transports."""
    db.rollback()
    recycle = bool((exc.details or {}).get("conflict_merchant_deleted"))
    message = ("同名商家已在回收站。请先恢复该商家，或改用其它名称。" if recycle
        else "商家已存在，无需重复添加。" if kind == "catalog" and exc.error == "state_conflict"
        else ("请填写商家名称，最多255个字。" if kind == "catalog" else "请填写标准商家名和别名。") if exc.error == "invalid_request"
        else exc.message)
    refusal = "rejected" if exc.error in {"invalid_request", "state_conflict", "merchant_alias_conflict", "idempotency_key_reused"} else "blocked"
    return draft_error_response(request, AppError(exc.error, message, status_code=exc.status_code), refusal_result=refusal) or _render_merchants(
        request, db, options=options, selected_id=selected_id,
        creation_kind=kind, creation_form=values, creation_result=refusal,
        catalog_create_error=message if kind == "catalog" else "", catalog_create_value=values.display_name,
        catalog_create_recycle=recycle, alias_create_error=message if kind == "alias" else "",
        alias_create_draft={"canonical_merchant": values.canonical_merchant, "alias": values.alias},
        status_code=422 if refusal == "rejected" else exc.status_code)


def _create_merchant(request: Request, db: Session, kind: str, values: MerchantCreateForm) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values.ledger_id or None, options, request=request)
    label = "商家" if kind == "catalog" else "别名"
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=values.model_dump(), task="添加" + label)
        if retained is not None:
            return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        if values.ledger_id != selected_id:
            raise AppError("session_binding_changed", "原账本无法确认，请保留输入并重新打开原账本。", status_code=409)
        values.draft_scope = reviewed_draft_scope(db, request, values.draft_scope, review=values.review_new)
        require_draft_binding(db, request, ledger_id=values.ledger_id or selected_id,
            draft_scope=values.draft_scope, require_session=False)
        if values.review_new:
            values.idempotency_key = str(uuid4())
            return _render_merchants(request, db, options=options, selected_id=selected_id,
                creation_kind=kind, creation_form=values, creation_result="prepared")
        try:
            payload = (MerchantCatalogCreateRequest(display_name=values.display_name) if kind == "catalog"
                else MerchantAliasCreateRequest(canonical_merchant=values.canonical_merchant, alias=values.alias))
        except ValidationError as exc:
            raise AppError("invalid_request", "请填写商家名称和适用的别名，最多255个字。", status_code=422) from exc
        actor, _ = resolve_web_actor(db, request, selected_id)
        receipt = submit_merchant_creation(db, tenant_id=selected_id, actor_account_id=actor,
            payload=payload, idempotency_key=values.idempotency_key)
    except AppError as exc:
        return _merchant_creation_failure(request, db, kind=kind, values=values,
            options=options, selected_id=selected_id, exc=exc)
    redirect = _web_redirect("/web/merchants", selected_id, search=values.search, status=values.status,
        view="directory" if kind == "catalog" else "aliases", msg="已确认添加" + label + "。")
    return draft_ack_response(request, draft_scope=values.draft_scope, idempotency_key=values.idempotency_key,
        receipt=receipt, next_href=redirect.headers["location"]) or redirect


@router.post("/merchants/catalog/create", response_class=HTMLResponse)
def web_merchant_catalog_create(request: Request, values: Annotated[MerchantCreateForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _create_merchant(request, db, "catalog", values)


def _catalog_command_failure(request: Request, db: Session, *, kind: str, values: MerchantCommandForm,
    options: list, selected_id: str, exc: AppError) -> Response:
    db.rollback()
    message = _catalog_rename_error_message(exc) if kind == "rename" else _catalog_conflict_message(exc)
    refusal = "rejected" if exc.error in {"state_conflict", "invalid_request", "idempotency_key_reused", "idempotency_key_required", "not_found"} else "blocked"
    return draft_error_response(request, AppError(exc.error, message, status_code=exc.status_code), refusal_result=refusal) or _render_merchants(
        request, db, options=options, selected_id=selected_id, command_kind=kind, command_form=values,
        command_result=refusal, command_error=message, status_code=422 if refusal == "rejected" else exc.status_code)


def _catalog_command(request: Request, db: Session, public_id: str, kind: str, values: MerchantCommandForm) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values.ledger_id or None, options, request=request)
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=values.model_dump(), task="商家操作")
        if retained is not None:
            return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        if values.ledger_id != selected_id or values.merchant not in {"", public_id}:
            raise AppError("session_binding_changed", "原账本或商家无法确认，原输入仍保留。", status_code=409)
        values.merchant = public_id
        values.draft_scope = reviewed_draft_scope(db, request, values.draft_scope, review=values.review_latest)
        require_draft_binding(db, request, ledger_id=values.ledger_id,
            draft_scope=values.draft_scope, require_session=False)
        if values.review_latest:
            reviewed = review_catalog_form(db, kind, values)
            reviewed.idempotency_key = str(uuid4())
            return _render_merchants(request, db, options=options, selected_id=selected_id,
                command_kind=kind, command_form=reviewed, command_result="prepared")
        actor, _ = resolve_web_actor(db, request, selected_id)
        receipt = submit_catalog_command(db, tenant_id=selected_id, actor_account_id=actor, public_id=public_id,
            payload=catalog_payload(kind, values), idempotency_key=values.idempotency_key)
    except AppError as exc:
        return _catalog_command_failure(request, db, kind=kind, values=values, options=options, selected_id=selected_id, exc=exc)
    message = (f"商家「{receipt.source.display_name}」已合并到「{receipt.target.display_name}」。历史账单不会改写；"
        + ("已创建来源别名。" if receipt.created_alias_public_id else "未创建来源别名。") if kind == "merge"
        else f"已确认商家「{receipt.display_name}」的原操作。")
    redirect = _web_redirect("/web/merchants", selected_id, search=values.search, status=values.status, msg=message)
    return draft_ack_response(request, draft_scope=values.draft_scope, idempotency_key=values.idempotency_key,
        receipt=receipt, next_href=redirect.headers["location"]) or redirect


@router.post("/merchants/catalog/{public_id}/rename", response_class=HTMLResponse)
def web_merchant_catalog_rename(request: Request, public_id: str, values: Annotated[MerchantCommandForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _catalog_command(request, db, public_id, "rename", values)


@router.post("/merchants/catalog/{public_id}/merge", response_class=HTMLResponse)
def web_merchant_catalog_merge(request: Request, public_id: str, values: Annotated[MerchantCommandForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _catalog_command(request, db, public_id, "merge", values)


@router.post("/merchants/catalog/{public_id}/toggle", response_class=HTMLResponse)
def web_merchant_catalog_toggle(request: Request, public_id: str, values: Annotated[MerchantCommandForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _catalog_command(request, db, public_id, "toggle", values)


@router.post("/merchants/catalog/{public_id}/delete", response_class=HTMLResponse)
def web_merchant_catalog_delete(request: Request, public_id: str, values: Annotated[MerchantCommandForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _catalog_command(request, db, public_id, "delete", values)


@router.post("/merchants/aliases/create", response_class=HTMLResponse)
def web_merchant_alias_create(request: Request, values: Annotated[MerchantCreateForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _create_merchant(request, db, "alias", values)


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
