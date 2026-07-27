"""ADR-0051 /web current-ledger recycle-bin page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

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
    RecycleBinListing,
    list_recycle_bin_items,
    restore_recycle_bin_item,
)

router = APIRouter(prefix="/web/recycle-bin", tags=["web"])

# C5b-2 硬门 (照 #248 web_debt_proposal_actions 422 原地重渲染+锚定范式)：
# restore 失败不再 redirect+error flash，而是 db.rollback() 后走共享渲染入口 422
# 原地重渲染，错误按 data-restore-key 身份锚定到被提交行，零写入、幂等键不旋转。
_STALE_RESTORE_MESSAGE = "页面已过期，请刷新后重新操作。"
_GONE_RESTORE_MESSAGE = "这条项目已不在回收站，可能已恢复或超过保留期，请刷新查看最新状态。"


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
    return _render_recycle_bin(
        request,
        db,
        options=options,
        selected=selected,
        message=message,
        error=error,
    )


def _render_recycle_bin(
    request: Request,
    db: Session,
    *,
    options,
    selected: str,
    message: str | None = None,
    error: str | None = None,
    restore_error: str | None = None,
    restore_error_key: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """回收站页唯一渲染入口：GET 与 restore 失败 422 原地重渲染共用 (照
    ``web_debts._render_debt_detail`` 同页重渲染范式)，保证错误重渲染与正常渲染
    的页面结构零漂移。``restore_error_key`` 是被提交行的身份锚 (``kind:resource_id``)；
    被提交行已不在列表 (已恢复/超窗/他账本构造直 POST) 时 ``restore_error_orphan``
    让模板渲染裸块兜底，错误文案永不整页消失。"""
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
        restore_error=restore_error,
        restore_error_key=restore_error_key,
        restore_error_orphan=_restore_error_is_orphan(
            restore_error,
            restore_error_key,
            listing,
        ),
    )
    return templates.TemplateResponse(
        request=request,
        name="recycle_bin.html",
        context=ctx,
        status_code=status_code,
    )


def _restore_key(kind: str, resource_id: str) -> str:
    """行身份锚：``kind:resource_id`` (回收站行的稳定身份，不是位置索引)。
    与服务层同一 ``strip`` 口径，保证与列表行的 key 可比。"""
    return f"{(kind or '').strip()}:{(resource_id or '').strip()}"


def _restore_error_is_orphan(
    restore_error: str | None,
    restore_error_key: str | None,
    listing: RecycleBinListing,
) -> bool:
    if restore_error is None or restore_error_key is None:
        return False
    listed = {f"{item.kind}:{item.resource_id}" for item in listing.items}
    return restore_error_key not in listed


def _restore_error_message(exc: AppError) -> str:
    """restore 失败文案：OCC 冲突 → 过期提示；不存在族 (已恢复/超窗/他账本) →
    「已不在回收站」；其余 (参数不完整、别名指向冲突等) 沿用服务层原文。"""
    if exc.error == "state_conflict":
        return _STALE_RESTORE_MESSAGE
    if exc.error == "not_found" or exc.error.endswith("_not_found"):
        return _GONE_RESTORE_MESSAGE
    return exc.message


def _restore_error_rerender(
    request: Request,
    db: Session,
    *,
    options,
    selected: str,
    kind: str,
    resource_id: str,
    exc: AppError,
) -> HTMLResponse:
    """restore 失败 (OCC 冲突/已恢复/超窗/不存在/参数缺失) → 422 原地重渲染：
    ``db.rollback()`` 归零写入，错误按 ``data-restore-key`` 身份锚定到被提交的
    那一行；重渲染页重新列表带出最新 ``expected_row_version``，隐藏字段身份不旋转，
    用户可直接从该页重试。"""
    db.rollback()
    return _render_recycle_bin(
        request,
        db,
        options=options,
        selected=selected,
        restore_error=_restore_error_message(exc),
        restore_error_key=_restore_key(kind, resource_id),
        status_code=422,
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
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options=options, request=request)
    # viewer 直 POST 保持 403，不进 422 原地重渲染族。
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
        return _restore_error_rerender(
            request,
            db,
            options=options,
            selected=selected,
            kind=kind,
            resource_id=resource_id,
            exc=exc,
        )
    return _web_redirect("/web/recycle-bin", selected, message=message)


def _actor_account_id(request: Request, db: Session) -> int | None:
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.account_id
    return get_owner_account_id(db)
