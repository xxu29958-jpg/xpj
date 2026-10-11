"""Native Web consumers for ledger-shared saved financial queries."""

import json
from dataclasses import asdict
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    rendered_draft_scope,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_session_common import resolve_web_actor_account_id
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
from app.routes.web_saved_view_forms import SavedViewDefinitionForm, SavedViewForm, saved_view_refusal
from app.services import saved_view_service as saved_views
from app.services.category_service import list_ledger_category_options
from app.services.currency_common import supported_currency_codes
from app.services.tag_management_service import list_tags_with_usage

router = APIRouter(prefix="/web", tags=["web"])


def confirmed_save_context(request: Request, db: Session, *, ledger_id: str, tag: str) -> dict:
    actor = resolve_web_actor_account_id(db, request, ledger_id)
    try:
        tag_id = saved_views.resolve_live_tag_public_id(db, tenant_id=ledger_id,
            actor_account_id=actor, tag_name=tag)
    except AppError as exc:
        if exc.error != "saved_view_tag_repair_required":
            raise
        return {"save_view_error": "这个标签已变更或移除。请重新选择标签后保存视图。"}
    return {"save_view_tag_public_id": tag_id or ""}


def _error_message(exc: AppError) -> str:
    if exc.error == "state_conflict":
        return "视图已在别处修改。你的输入仍保留，请先核对最新版本，再决定是否继续。"
    if exc.error == "permission_denied":
        return "当前角色只读，本次修改未执行，输入仍保留。恢复写入权限后可以重试。"
    return exc.message


def _render_views(request, db, *, options, selected, message="", error="", draft=None,
                  editing_public_id="", kind="edit", result="", status_code=200) -> HTMLResponse:
    actor = resolve_web_actor_account_id(db, request, selected)
    views = saved_views.list_views(db, tenant_id=selected, actor_account_id=actor)
    view = next((item for item in views if item.public_id == editing_public_id), None)
    scope, binding_required = rendered_draft_scope(db, request, draft.get("draft_scope", "") if draft and result else None)
    if editing_public_id and draft is None:
        draft = {**SavedViewForm().model_dump(), **(asdict(view) if view else {}),
            "expected_row_version": str(view.row_version) if view else ""}
    if draft is not None and not result and not draft.get("idempotency_key"):
        draft.update(ledger_id=selected, public_id=editing_public_id, idempotency_key=str(uuid4()),
            draft_ref=str(uuid4()), draft_scope=json.dumps(scope) if scope else "")
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected,
                    page_title="保存的视图")
    ctx.update(views=views, flash_message=message, error=error,
        draft=draft, editing_public_id=editing_public_id,
        command_kind=kind, command_result=result, saved_view_scope=scope, binding_required=binding_required,
        command_available=not editing_public_id or view is not None, current_view=view,
        tag_options=list_tags_with_usage(db, selected), currency_codes=sorted(supported_currency_codes()),
        category_options=list_ledger_category_options(db, tenant_id=selected),
        q="?" + urlencode({"ledger_id": selected}))
    return templates.TemplateResponse(request=request, name="saved_views.html", context=ctx,
                                      status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/saved-views", response_class=HTMLResponse)
def web_saved_views(request: Request, ledger_id: str = "", msg: str = "",
                    edit: str = "", delete: str = "", create: bool = False, month_mode: str = "current",
                    month: str = "", filter: str = "", tag_public_id: str = "", home_currency_code: str = "",
                    query_text: str = "", category: str = "",
                    _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {**SavedViewForm().model_dump(), "ledger_id": selected, "month_mode": month_mode, "month": month, "filter": filter,
        "tag_public_id": tag_public_id, "home_currency_code": home_currency_code,
        "query_text": query_text, "category": category} if create and not (edit or delete) else None
    return _render_views(request, db, options=options, selected=selected, message=msg,
                         draft=draft, editing_public_id=delete or edit, kind="delete" if delete else "edit")


@router.get("/saved-views/{public_id}/open", response_class=RedirectResponse)
def web_saved_view_open(request: Request, public_id: str, ledger_id: str = "",
                        _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    actor = resolve_web_actor_account_id(db, request, selected)
    try:
        query = saved_views.resolve_view_query(db, tenant_id=selected, actor_account_id=actor,
                                              public_id=public_id)
    except AppError as exc:
        return _render_views(request, db, options=options, selected=selected,
            error=_error_message(exc), status_code=exc.status_code,
            editing_public_id=public_id if exc.error == "saved_view_tag_repair_required" else "")
    return RedirectResponse("/web/confirmed?" + urlencode(query), status_code=303)


def _submit_view(db, *, selected, actor, fields, public_id, kind):
    command = {"tenant_id": selected, "actor_account_id": actor, "idempotency_key": fields["idempotency_key"]}
    if public_id:
        token = parse_form_row_version_token(fields["expected_row_version"])
        if token is None:
            raise AppError("state_conflict", status_code=409)
        command.update(public_id=public_id, expected_row_version=token)
    if kind == "delete":
        return saved_views.delete_view(db, **command)
    definition = {key: fields[key] for key in (
        "name", "month_mode", "month", "filter", "tag_public_id", "home_currency_code", "query_text", "category")}
    submit = saved_views.update_view if public_id else saved_views.create_view
    return submit(db, **command, **definition)


def _save_view(request, db, *, fields, public_id="", kind="edit") -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, fields["ledger_id"] or None, options, request=request)
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
            fields=fields, task="删除保存的查询" if kind == "delete" else "保存视图的名称和查询条件")
        if retained is not None:
            return retained
    actor = resolve_web_actor_account_id(db, request, selected)
    try:
        _require_selected_ledger_write(options, selected)
        if fields["ledger_id"] != selected or fields["public_id"] not in {"", public_id}:
            raise AppError("session_binding_changed", "原账本或查询无法确认，原输入仍保留。", status_code=409)
        fields["public_id"] = public_id
        review = fields["review_latest"] if public_id else fields["review_new"]
        fields["draft_scope"] = reviewed_draft_scope(db, request, fields["draft_scope"], review=review)
        require_draft_binding(db, request, ledger_id=selected, draft_scope=fields["draft_scope"], require_session=False)
        if review:
            if public_id:
                current = saved_views.read_view(db, tenant_id=selected, actor_account_id=actor, public_id=public_id)
                fields["expected_row_version"] = str(current.row_version)
            fields["idempotency_key"] = str(uuid4())
            fields["draft_ref"] = fields["draft_ref"] or str(uuid4())
            return _render_views(request, db, options=options, selected=selected, draft=fields,
                editing_public_id=public_id, kind=kind, result="prepared")
        receipt = _submit_view(db, selected=selected, actor=actor, fields=fields, public_id=public_id, kind=kind)
    except AppError as exc:
        db.rollback()
        result = saved_view_refusal(exc)
        error = AppError(exc.error, _error_message(exc), status_code=exc.status_code)
        return draft_error_response(request, error, refusal_result=result) or _render_views(
            request, db, options=options, selected=selected, error=error.message, draft=fields,
            editing_public_id=public_id, kind=kind, result=result, status_code=exc.status_code)
    redirect = _web_redirect("/web/saved-views", selected, msg=(
        f"已确认删除「{receipt.name}」的原请求，账单保持不变。" if kind == "delete" else
        f"已确认保存「{receipt.name}」的原请求，以下显示查询的当前状态。"))
    return draft_ack_response(request, draft_scope=fields["draft_scope"], idempotency_key=fields["idempotency_key"],
        receipt=asdict(receipt), next_href=redirect.headers["location"]) or redirect


@router.post("/saved-views", response_class=HTMLResponse)
def web_saved_view_create(
    request: Request, form: Annotated[SavedViewDefinitionForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return _save_view(request, db, fields=form.model_dump())


@router.post("/saved-views/{public_id}/rename", response_class=HTMLResponse)
def web_saved_view_update(
    request: Request, public_id: str, form: Annotated[SavedViewForm, Form()],
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return _save_view(request, db, public_id=public_id, fields=form.model_dump())


@router.post("/saved-views/{public_id}/delete", response_class=HTMLResponse)
def web_saved_view_delete(request: Request, public_id: str, form: Annotated[SavedViewForm, Form()], _local: None = LocalOnly,
                          db: Session = Depends(get_db)) -> Response:
    return _save_view(request, db, public_id=public_id, fields=form.model_dump(), kind="delete")
