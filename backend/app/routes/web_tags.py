"""/web tag-management routes (ADR-0043 slice C).

Mirror of ``web_merchants`` (OCC + soft-delete + 5s 撤销 banner), adapted to the
tag surface: list + usage count, rename (self-inverse), delete, merge A→B, and
undo. Tags are created implicitly when an expense is tagged, so there is NO
create form here — only governance of existing tags.

Every mutate form carries the hidden ``expected_row_version`` (OCC); a stale
token surfaces as a "页面已过期/已在其它端修改" redirect instead of clobbering a
stale snapshot. rename colliding with an existing key returns 409 ``tag_conflict``
— the operator is told to use 合并 (契约 5). delete/merge soft-delete the source
tag and offer a 5s 撤销 affordance that POSTs to the undo route with the
mutation's handle + the soft-deleted tag's undo token (契约 2).
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
from app.services.tag_management_service import (
    delete_tag,
    list_tags_with_usage,
    merge_tags,
    rename_tag,
)
from app.services.tag_undo_service import undo_tag_mutation

router = APIRouter(prefix="/web", tags=["web"])


def _stale_redirect(selected_id: str) -> RedirectResponse:
    return _web_redirect("/web/tags", selected_id, msg="页面已过期，请刷新后重试。")


def _conflict_message(exc: AppError) -> str:
    """Map a tag service error code to a 生活化 Chinese flash message."""
    if exc.error == "state_conflict":
        return "标签已在其它端被修改，请刷新后重试。"
    if exc.error == "tag_not_found":
        return "标签不存在或已被删除。"
    if exc.error == "tag_conflict":
        # 契约 5: the key is taken by another (possibly soft-deleted) tag; the
        # honest degraded path on /web is to point the operator at 合并.
        return "标签名已被占用，如需归并请使用『合并』。"
    if exc.error == "tag_undo_not_found":
        return "无法撤销：撤销窗口已过，或该操作不存在。"
    return exc.message


@router.get("/tags", response_class=HTMLResponse)
def web_tags(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    undo: str = "",
    undo_rv: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    tags = list_tags_with_usage(db, selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["tags"] = tags
    ctx["flash_message"] = msg
    # ADR-0043 undo: a just-deleted/merged tag's mutation handle + the
    # soft-deleted source tag's undo token, so the flash can offer a 5s 撤销
    # affordance that POSTs to the undo route (契约 2 needs BOTH).
    ctx["undo_mutation_public_id"] = undo
    ctx["undo_row_version"] = undo_rv
    return templates.TemplateResponse(request=request, name="tags.html", context=ctx)


@router.post("/tags/{public_id}/rename", response_class=HTMLResponse)
def web_tag_rename(
    request: Request,
    public_id: str,
    name: str = Form(""),
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
        return _stale_redirect(selected_id)
    try:
        tag = rename_tag(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
            name=name,
        )
        msg = f"标签已重命名为 [{tag.name}]。"
    except AppError as exc:
        msg = _conflict_message(exc)
    return _web_redirect("/web/tags", selected_id, msg=msg)


@router.post("/tags/{public_id}/delete", response_class=HTMLResponse)
def web_tag_delete(
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
        return _stale_redirect(selected_id)
    try:
        result = delete_tag(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
        )
    except AppError as exc:
        return _web_redirect("/web/tags", selected_id, msg=_conflict_message(exc))
    # ADR-0043 undo: pass the mutation handle + the soft-deleted tag's undo token
    # so the page renders a 5s 撤销 banner; recoverable until cleanup purges it.
    return _web_redirect(
        "/web/tags",
        selected_id,
        msg=f"标签已删除（影响 {result.affected_expense_count} 笔账单）。",
        undo=result.mutation_public_id,
        undo_rv=str(result.source_tag_row_version),
    )


@router.post("/tags/{public_id}/merge", response_class=HTMLResponse)
def web_tag_merge(
    request: Request,
    public_id: str,
    target: str = Form(""),
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    source_rv = parse_form_row_version_token(expected_row_version)
    # The target option carries "<public_id>:<row_version>" (the page is a
    # snapshot; both OCC tokens must ride the form). Partition on the LAST colon —
    # a UUID public_id has no colon, so this is unambiguous.
    target_public_id, _, target_rv_raw = target.rpartition(":")
    target_rv = parse_form_row_version_token(target_rv_raw)
    if source_rv is None or not target_public_id or target_rv is None:
        return _stale_redirect(selected_id)
    try:
        result = merge_tags(
            db,
            tenant_id=selected_id,
            source_public_id=public_id,
            source_row_version=source_rv,
            target_public_id=target_public_id,
            target_row_version=target_rv,
        )
    except AppError as exc:
        return _web_redirect("/web/tags", selected_id, msg=_conflict_message(exc))
    return _web_redirect(
        "/web/tags",
        selected_id,
        msg=f"标签已合并（影响 {result.affected_expense_count} 笔账单）。",
        undo=result.mutation_public_id,
        undo_rv=str(result.source_tag_row_version),
    )


@router.post("/tags/mutations/{mutation_public_id}/undo", response_class=HTMLResponse)
def web_tag_undo(
    request: Request,
    mutation_public_id: str,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # ADR-0043 undo (契约 2): restore a soft-deleted tag + replay its expense
    # snapshot. Unlike merchant undo, this carries the soft-deleted tag's
    # ``expected_row_version`` (the undo token from the delete/merge response).
    # 404 once cleanup has purged the snapshot (window elapsed) → degrade.
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _stale_redirect(selected_id)
    try:
        result = undo_tag_mutation(
            db,
            tenant_id=selected_id,
            mutation_public_id=mutation_public_id,
            expected_row_version=parsed,
        )
        if result.skipped:
            msg = f"已撤销标签操作（恢复 {result.applied} 笔，{result.skipped} 笔已改动跳过）。"
        else:
            msg = f"已撤销标签操作（恢复 {result.applied} 笔账单）。"
    except AppError as exc:
        msg = _conflict_message(exc)
    return _web_redirect("/web/tags", selected_id, msg=msg)
