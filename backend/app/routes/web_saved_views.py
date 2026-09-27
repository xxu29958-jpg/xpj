"""Native Web consumers for ledger-shared saved financial queries."""

from dataclasses import asdict
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.services import saved_view_service as saved_views
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
    return {"save_view_tag_public_id": tag_id or "", "save_view_key": str(uuid4())}


def _error_message(exc: AppError) -> str:
    if exc.error == "state_conflict":
        return "视图已在别处修改。你的输入仍保留，请先重新载入最新条件，核对后再编辑。"
    if exc.error == "permission_denied":
        return "当前角色只读，本次修改未执行，输入仍保留。恢复写入权限后可以重试。"
    return exc.message


def _render_views(request, db, *, options, selected, message="", error="", draft=None,
                  editing_public_id="", status_code=200) -> HTMLResponse:
    actor = resolve_web_actor_account_id(db, request, selected)
    views = saved_views.list_views(db, tenant_id=selected, actor_account_id=actor)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected,
                    page_title="保存的视图")
    ctx.update(views=[asdict(view) for view in views], flash_message=message, error=error,
        draft=draft, editing_public_id=editing_public_id,
        tag_options=list_tags_with_usage(db, selected), currency_codes=sorted(supported_currency_codes()),
        q="?" + urlencode({"ledger_id": selected}))
    return templates.TemplateResponse(request=request, name="saved_views.html", context=ctx,
                                      status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/saved-views", response_class=HTMLResponse)
def web_saved_views(request: Request, ledger_id: str = "", msg: str = "",
                    _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return _render_views(request, db, options=options, selected=selected, message=msg)


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
            error=_error_message(exc), status_code=exc.status_code)
    return RedirectResponse("/web/confirmed?" + urlencode(query), status_code=303)


def _save_view(request, db, *, fields, public_id="") -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, fields["ledger_id"] or None, options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=fields, task="保存视图的名称和查询条件")
    if retained is not None:
        return retained
    actor = resolve_web_actor_account_id(db, request, selected)
    definition = {key: fields[key] for key in (
        "name", "month_mode", "month", "filter", "tag_public_id", "home_currency_code")}
    try:
        if public_id:
            token = parse_form_row_version_token(fields["expected_row_version"])
            if token is None:
                raise AppError("state_conflict", status_code=409)
            saved_views.update_view(db, tenant_id=selected, actor_account_id=actor,
                public_id=public_id, expected_row_version=token, **definition)
        else:
            saved_views.create_view(db, tenant_id=selected, actor_account_id=actor,
                idempotency_key=fields["idempotency_key"], **definition)
    except AppError as exc:
        db.rollback()
        return _render_views(request, db, options=options, selected=selected,
            error=_error_message(exc), draft=fields, editing_public_id=public_id, status_code=exc.status_code)
    return _web_redirect("/web/saved-views", selected,
                         msg="视图已更新。" if public_id else "视图已保存，可从资料库重新打开。")


@router.post("/saved-views", response_class=HTMLResponse)
def web_saved_view_create(
    request: Request, ledger_id: str = Form(""), name: str = Form(""),
    month_mode: str = Form("fixed"), month: str = Form(""), filter: str = Form(""),
    tag_public_id: str = Form(""), home_currency_code: str = Form(""),
    idempotency_key: str = Form(""), _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return _save_view(request, db, fields={"ledger_id": ledger_id, "name": name,
        "month_mode": month_mode, "month": month, "filter": filter, "tag_public_id": tag_public_id,
        "home_currency_code": home_currency_code, "idempotency_key": idempotency_key})


@router.post("/saved-views/{public_id}/rename", response_class=HTMLResponse)
def web_saved_view_update(
    request: Request, public_id: str, ledger_id: str = Form(""), name: str = Form(""),
    month_mode: str = Form("fixed"), month: str = Form(""), filter: str = Form(""),
    tag_public_id: str = Form(""), home_currency_code: str = Form(""),
    expected_row_version: str = Form(""), _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    return _save_view(request, db, public_id=public_id, fields={"ledger_id": ledger_id, "name": name,
        "month_mode": month_mode, "month": month, "filter": filter, "tag_public_id": tag_public_id,
        "home_currency_code": home_currency_code, "expected_row_version": expected_row_version})


@router.post("/saved-views/{public_id}/delete", response_class=HTMLResponse)
def web_saved_view_delete(request: Request, public_id: str, ledger_id: str = Form(""),
                          expected_row_version: str = Form(""), _local: None = LocalOnly,
                          db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={"ledger_id": ledger_id, "expected_row_version": expected_row_version}, task="删除保存的视图")
    if retained is not None:
        return retained
    actor = resolve_web_actor_account_id(db, request, selected)
    try:
        token = parse_form_row_version_token(expected_row_version)
        if token is None:
            raise AppError("state_conflict", status_code=409)
        saved_views.delete_view(db, tenant_id=selected, actor_account_id=actor,
                               public_id=public_id, expected_row_version=token)
    except AppError as exc:
        db.rollback()
        return _render_views(request, db, options=options, selected=selected,
                              error=_error_message(exc), status_code=exc.status_code)
    return _web_redirect("/web/saved-views", selected, msg="视图已删除，账单保持不变。")
