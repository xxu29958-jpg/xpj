"""Tag catalogue and bound online editors; the tag services own every mutation."""
from __future__ import annotations

import json
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
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
from app.services.tag_management_service import delete_tag, list_tags_with_usage, merge_tags, rename_tag
from app.services.tag_undo_service import undo_tag_mutation

router = APIRouter(prefix="/web", tags=["web"])
TagAction = Literal["rename", "merge", "delete"]
ACTION_LABELS = {"rename": "重命名标签", "merge": "合并标签", "delete": "删除标签"}


class TagEditForm(BaseModel):
    ledger_id: str = ""
    expected_row_version: str = ""
    name: str = ""
    target: str = ""
    target_name: str = ""
    unused: str = ""
    source_name: str = ""
    source_usage_count: str = ""
    draft_scope: str = ""
    draft_ref: str = ""
    review_latest: bool = False


def _stale_redirect(selected_id: str, unused: str = "") -> RedirectResponse:
    return _web_redirect("/web/tags", selected_id, unused=unused, msg="页面已过期，请刷新后重试。", flash_type="error")


def _conflict_message(exc: AppError, unused: str = "") -> str:
    if unused == "1" and exc.error in {"state_conflict", "tag_not_found"}:
        return "标签可能已被使用或状态已变化。原稿仍保留，请核对当前状态。"
    if exc.error == "state_conflict":
        return "标签状态已变化，本次未执行。原输入和版本已保留；请核对当前记录及之前提交的结果。"
    if exc.error == "tag_not_found":
        return "标签不存在或已被删除。原稿仍保留，可到回收站核对。"
    if exc.error == "tag_conflict":
        return "标签名已被占用，如需归并请使用『合并』。"
    if exc.error == "tag_undo_not_found":
        return "无法撤销：撤销窗口已过，或该操作不存在。"
    return exc.message


def _render_tags(request, db, *, options, selected_id, unused="", msg="", flash_type="", undo="", undo_rv=""):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    tags = list_tags_with_usage(db, selected_id)
    ctx.update(tags=[tag for tag in tags if tag.usage_count == 0] if unused == "1" else tags,
        unused=unused == "1", flash_message=msg, flash_type=flash_type,
        undo_mutation_public_id=undo, undo_row_version=undo_rv, tag_draft_scope=browser_draft_scope(db, request))
    return templates.TemplateResponse(request=request, name="tags.html", context=ctx)


@router.get("/tags", response_class=HTMLResponse)
def web_tags(
    request: Request, ledger_id: str = "", unused: str = "", msg: str = "",
    flash_type: str = "", undo: str = "", undo_rv: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return _render_tags(request, db, options=options, selected_id=selected_id,
        unused=unused, msg=msg, flash_type=flash_type, undo=undo, undo_rv=undo_rv)


def _render_editor(request, db, options, selected_id, public_id, action, *, values=None,
                   unused="", error="", status_code=200, draft_result=""):
    tags = list_tags_with_usage(db, selected_id)
    current = next((tag for tag in tags if tag.public_id == public_id), None)
    scope = browser_draft_scope(db, request)
    if values is None:
        values = TagEditForm(ledger_id=selected_id, unused=unused,
            expected_row_version=str(current.row_version) if current else "",
            name=current.name if current else "", source_name=current.name if current else "",
            source_usage_count=str(current.usage_count) if current else "",
            draft_scope=json.dumps(scope) if scope else "", draft_ref=str(uuid4()))
    if not values.draft_ref:
        values = values.model_copy(update={"draft_ref": str(uuid4())})
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    target_id = values.target.rpartition(":")[0]
    ctx.update(current=current, merge_targets=[tag for tag in tags if tag.public_id != public_id],
        current_target=next((tag for tag in tags if tag.public_id == target_id), None),
        values=values.model_dump(), public_id=public_id, action=action, action_label=ACTION_LABELS[action],
        tag_draft_scope=scope if values.draft_scope else None, tag_draft_result=draft_result,
        edit_key=f"{public_id}:{action}:{values.unused}", error=error)
    return templates.TemplateResponse(request=request, name="tag_edit.html", context=ctx,
        status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/tags/{public_id}/edit", response_class=HTMLResponse)
def web_tag_edit(
    request: Request, public_id: str, action: TagAction = "rename", ledger_id: str = "", unused: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return _render_editor(request, db, options, selected_id, public_id, action, unused=unused)


def _review_editor(db, selected_id, public_id, values):
    tags = list_tags_with_usage(db, selected_id)
    source = next((tag for tag in tags if tag.public_id == public_id), None)
    if source is None:
        raise AppError("tag_not_found", status_code=404)
    if values.unused == "1" and source.usage_count:
        raise AppError("state_conflict", status_code=409)
    target_id = values.target.rpartition(":")[0]
    target = next((tag for tag in tags if tag.public_id == target_id), None)
    return values.model_copy(update={"expected_row_version": str(source.row_version),
        "source_name": source.name, "source_usage_count": str(source.usage_count), "review_latest": False,
        "target_name": target.name if target else values.target_name,
        "target": f"{target.public_id}:{target.row_version}" if target else values.target})


def _apply_tag_edit(db, request, selected_id, public_id, action, values):
    source_rv = parse_form_row_version_token(values.expected_row_version)
    if source_rv is None:
        raise AppError("state_conflict", status_code=409)
    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    common = {"tenant_id": selected_id, "actor_account_id": actor_account_id,
        "actor_device_id": actor_device_id, "require_orphan": values.unused == "1"}
    if action == "rename":
        tag = rename_tag(db, public_id=public_id, expected_row_version=source_rv, name=values.name, **common)
        return {"msg": f"标签已重命名为「{tag.name}」。"}, public_id
    if action == "merge":
        target_id, _, raw_target_rv = values.target.rpartition(":")
        target_rv = parse_form_row_version_token(raw_target_rv)
        if not target_id or target_rv is None:
            raise AppError("invalid_request", "请选择要保留的标签。原选择仍保留。", status_code=422)
        result = merge_tags(db, source_public_id=public_id, source_row_version=source_rv,
            target_public_id=target_id, target_row_version=target_rv, **common)
    else:
        target_id = ""
        result = delete_tag(db, public_id=public_id, expected_row_version=source_rv, **common)
    label = "合并" if action == "merge" else "删除"
    return {"msg": f"标签已{label}（影响 {result.affected_expense_count} 笔账单）。",
        "undo": result.mutation_public_id, "undo_rv": str(result.source_tag_row_version)}, target_id


def _submit_editor(request, db, public_id, action, values):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values.ledger_id or None, options, request=request)
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=values.model_dump(), task=ACTION_LABELS[action])
        if retained is not None:
            return retained
    try:
        if not values.review_latest:
            _require_selected_ledger_write(options, selected_id)
        values.draft_scope = reviewed_draft_scope(db, request, values.draft_scope, review=values.review_latest)
        require_draft_binding(db, request, ledger_id=values.ledger_id or selected_id,
            draft_scope=values.draft_scope, require_session=False)
        if values.review_latest:
            prepared = _review_editor(db, selected_id, public_id, values)
            return _render_editor(request, db, options, selected_id, public_id, action,
                values=prepared, draft_result="prepared")
        result, focus = _apply_tag_edit(db, request, selected_id, public_id, action, values)
    except AppError as exc:
        db.rollback()
        message = _conflict_message(exc, values.unused)
        refused = "rejected" if exc.error in {"state_conflict", "tag_conflict", "invalid_request", "tag_not_found"} else "blocked"
        response = draft_error_response(request, AppError(exc.error, message, status_code=exc.status_code), refusal_result=refused)
        return response or _render_editor(request, db, options, selected_id, public_id, action,
            values=values, error=message, status_code=exc.status_code, draft_result=refused)
    redirect = _web_redirect("/web/tags", selected_id, unused=values.unused, flash_type="success", **result)
    redirect.headers["location"] += "#tag-" + (quote(focus, safe="") if focus else "result")
    # draft_ref correlates the browser acknowledgement only. The domain command
    # remains online OCC; this is not a financial idempotency key or an Outbox.
    return draft_ack_response(request, draft_scope=values.draft_scope, idempotency_key=values.draft_ref,
        receipt={"public_id": public_id, "action": action}, next_href=redirect.headers["location"]) or redirect


@router.post("/tags/{public_id}/rename", response_class=HTMLResponse)
def web_tag_rename(request: Request, public_id: str, values: Annotated[TagEditForm, Form()],
                   _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _submit_editor(request, db, public_id, "rename", values)


@router.post("/tags/{public_id}/delete", response_class=HTMLResponse)
def web_tag_delete(request: Request, public_id: str, values: Annotated[TagEditForm, Form()],
                   _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _submit_editor(request, db, public_id, "delete", values)


@router.post("/tags/{public_id}/merge", response_class=HTMLResponse)
def web_tag_merge(request: Request, public_id: str, values: Annotated[TagEditForm, Form()],
                  _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    return _submit_editor(request, db, public_id, "merge", values)


@router.post("/tags/mutations/{mutation_public_id}/undo", response_class=HTMLResponse)
def web_tag_undo(
    request: Request,
    mutation_public_id: str,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    unused: str = Form(""),
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
        return _stale_redirect(selected_id, unused)
    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    try:
        result = undo_tag_mutation(
            db,
            tenant_id=selected_id,
            mutation_public_id=mutation_public_id,
            expected_row_version=parsed,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )
        if result.skipped:
            msg = f"已撤销标签操作（恢复 {result.applied} 笔，{result.skipped} 笔已改动跳过）。"
        else:
            msg = f"已撤销标签操作（恢复 {result.applied} 笔账单）。"
    except AppError as exc:
        return _web_redirect("/web/tags", selected_id, unused=unused, msg=_conflict_message(exc), flash_type="error")
    return _web_redirect("/web/tags", selected_id, unused=unused, msg=msg, flash_type="success")
