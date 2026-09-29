"""/web/import + /web/export pages.

CSV export is a thin LocalOnly wrapper around the existing service so the
desktop user does not have to copy an app token. CSV import now uses the same
server-side batch tables as ``/api/imports/csv``: upload creates a durable
preview batch, the detail page pages through row results, and apply inserts
valid rows as ``pending`` expenses in chunks.
"""

from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._portable_file_response import PortableFileResponse, portable_request_cancelled
from app.routes._web_money_views import _expense_view, _minor_amount_label
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    _with_ledger,
    preserve_original_ledger_form,
    templates,
)
from app.services.category_service import list_ledger_category_options
from app.services.csv_import_batch_service import (
    MAX_CSV_IMPORT_ROWS,
    apply_csv_import_batch,
    build_csv_import_errors_csv,
    create_csv_import_batch,
    get_csv_import_batch_progress,
    list_csv_import_batches,
    list_csv_import_rows,
    list_imported_expenses,
)
from app.services.portable_export_access import list_portable_ledgers, resolve_portable_export_context
from app.services.portable_export_service import create_portable_ledger_export
from app.services.spending_contract_service import accounting_datetime_label
from app.services.stats_service import export_confirmed_csv
from app.services.tag_service import list_tags
from app.tenants import SessionPrincipal
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

router = APIRouter(prefix="/web", tags=["web"])


def _portable_principal(request: Request) -> SessionPrincipal:
    principal = getattr(request.state, "web_session_principal", None)
    if principal is None:
        raise AppError("invalid_token", "请先确认本机浏览器身份，再下载当前账本的数据包。", status_code=401)
    return principal


@router.get("/exports", response_class=HTMLResponse, include_in_schema=False)
def web_portable_selection(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    from app.routes.web_common import _read_ui_theme

    principal = _portable_principal(request)
    ledgers = list_portable_ledgers(db, principal)
    return templates.TemplateResponse(request=request, name="auth/local.html", context={
        "identity": {"account_name": principal.account_name, "ledgers": ledgers,
            "selected_ledger_id": ledgers[0].ledger_id if ledgers else ""},
        "page_title": "带走账本数据", "story_aria_label": "关于账本数据包",
        "story_title_line_one": "账本里的记录，", "story_title_line_two": "随时留一份在手边",
        "steps": ("选择有权下载的账本", "保留记录、历史与可用原件", "保存后直接查看"),
        "card_aria_label": "下载账本数据", "card_title": "选择要带走的账本",
        "hint_prefix": "当前账户是", "hint_suffix": "。已归档账本仅向当前拥有者提供下载。",
        "form_action": "/web/export/portable", "download_mode": True,
        "submit_label": "下载所选账本（ZIP）",
        "footnote": "包含服务器已保存的数据，尚未提交的离线草稿不在包内。数据包不是安装恢复包；下载不会取消归档。",
        "error_message": "" if ledgers else "当前账户没有可下载的账本。",
        "backend_version": BACKEND_VERSION, "asset_version": STATIC_ASSET_VERSION,
        "ui_theme": _read_ui_theme(request),
        "return_url": "/" if getattr(request.state, "web_session_platform", "") == "desktop" else "/web/auth/ledgers",
        "return_label": "返回系统管理" if getattr(request.state, "web_session_platform", "") == "desktop" else "返回账本选择",
    })


@router.get("/export/portable", include_in_schema=False)
def web_export_portable(request: Request, ledger_id: str = "",
                        db: Session = Depends(get_db)) -> PortableFileResponse:
    auth = resolve_portable_export_context(db, _portable_principal(request), ledger_id=ledger_id or None)
    # Scope resolution is complete; don't hold its read connection throughout
    # the independently authorized snapshot and archive build.
    db.close()
    return PortableFileResponse(create_portable_ledger_export(
        db, auth=auth, cancel_requested=partial(portable_request_cancelled, request),
    ))


@router.get("/export.csv")
def web_export_csv(
    request: Request,
    ledger_id: str = "",
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    content = "\ufeff" + export_confirmed_csv(
        db,
        tenant_id=selected_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone,
    )
    filename = f"ticketbox-{selected_id}"
    if month:
        filename += f"-{month}"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.csv"'
        },
    )


@router.get("/import", response_class=HTMLResponse)
def web_import_form(
    request: Request,
    ledger_id: str = "",
    page: int = 1,
    page_size: int = 20,
    msg: str = "",
    flash_type: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    batches = list_csv_import_batches(db, tenant_id=selected_id, page=page, page_size=page_size)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    ctx["max_rows"] = MAX_CSV_IMPORT_ROWS
    ctx["export_categories"] = list_ledger_category_options(db, tenant_id=selected_id)
    ctx["export_tags"] = list_tags(db, selected_id)
    ctx["flash_message"] = msg
    ctx["flash_type"] = "error" if flash_type == "error" else "success"
    ctx["q"] = "?ledger_id=" + selected_id
    ctx["portable_export_available"] = getattr(request.state, "web_session_auth", None) is not None
    ctx["batch_page"] = batches
    ctx["batch_created_labels"] = {
        item.batch.id: accounting_datetime_label(item.batch.created_at) for item in batches.items
    }
    return templates.TemplateResponse(
        request=request, name="import_export.html", context=ctx
    )


@router.post("/import/preview", response_class=HTMLResponse)
async def web_import_preview(
    request: Request,
    ledger_id: str = Form(""),
    csv_file: UploadFile = File(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    if ledger_id != selected_id:
        return _web_redirect("/web/import", selected_id,
            msg="当前账本已变更，本次文件尚未导入。请核对账本后重新选择文件上传。", flash_type="error")
    _require_selected_ledger_write(options, selected_id)
    # A bad upload (GBK/ANSI CSV from Excel, oversized, headerless …) is the
    # most common failure on this page — flash it back instead of letting the
    # global handler render a bare-JSON page.
    try:
        batch = create_csv_import_batch(
            db,
            tenant_id=selected_id,
            file_name=csv_file.filename,
            file_obj=csv_file.file,
        )
    except AppError as exc:
        return _web_redirect("/web/import", selected_id, msg=exc.message, flash_type="error")
    msg = f"已解析 {batch.total_rows} 行，{batch.valid_rows} 行可导入。"
    return _web_redirect(f"/web/import/{batch.public_id}", selected_id, msg=msg)


@router.get("/import/{public_id}", response_class=HTMLResponse)
def web_import_batch_detail(
    request: Request,
    public_id: str,
    ledger_id: str = "",
    page: int = 1,
    page_size: int = 100,
    status: str | None = None,
    msg: str = "",
    flash_type: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    try:
        progress = get_csv_import_batch_progress(db, tenant_id=selected_id, public_id=public_id)
        rows_page = list_csv_import_rows(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            page=page,
            page_size=page_size,
            status=status,
        )
    except AppError as exc:
        return _web_redirect("/web/import", selected_id, msg=exc.message, flash_type="error")
    batch = progress.batch
    expense_ids = list({row.resolved_expense_id or row.expense_id for row in rows_page.items
                        if row.resolved_expense_id or row.expense_id})
    current_expenses = {
        expense.id: _expense_view(expense)
        for expense in list_imported_expenses(db, tenant_id=selected_id, expense_ids=expense_ids)
    }
    total_pages = max(1, (rows_page.total + rows_page.page_size - 1) // rows_page.page_size)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    ctx.update(
        {
            "batch": batch,
            "progress": progress,
            "created_label": accounting_datetime_label(batch.created_at),
            "updated_label": accounting_datetime_label(batch.updated_at),
            "rows": rows_page.items,
            "current_expenses": current_expenses,
            "row_amount_label": _minor_amount_label,
            "page": rows_page.page,
            "page_size": rows_page.page_size,
            "total": rows_page.total,
            "total_pages": total_pages,
            "status": status or "",
            "flash_message": msg,
            "flash_type": "error" if flash_type == "error" else "success",
            "q": "?ledger_id=" + selected_id,
            "base_batch_url": _with_ledger(f"/web/import/{public_id}", selected_id),
        }
    )
    return templates.TemplateResponse(
        request=request, name="import_batch.html", context=ctx
    )


@router.post("/import/{public_id}/apply")
def web_import_batch_apply(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    batch_size: int = Form(500),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={"ledger_id": ledger_id, "batch_size": str(batch_size)}, task="继续原 CSV 批次")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    safe_batch_size = min(max(batch_size, 1), 1000)
    # The apply commits every row independently, so the handler-entry
    # revalidation above cannot cover a batch mid-flight: pass the bridged
    # desktop principal (already refreshed by _resolve_selected_ledger_id)
    # down for per-row revalidation. Web/console sessions pass None and pay
    # nothing.
    desktop_session = None
    if getattr(request.state, "web_session_platform", "") == "desktop":
        desktop_session = getattr(request.state, "web_session_auth", None)
    try:
        account_id, device_id = resolve_web_actor(db, request, selected_id)
        applied = apply_csv_import_batch(
            db,
            tenant_id=selected_id,
            initiator_account_id=account_id,
            initiator_device_id=device_id,
            public_id=public_id,
            batch_size=safe_batch_size,
            desktop_session=desktop_session,
        )
    except AppError as exc:
        target = "/web/import" if exc.status_code in {401, 404} else f"/web/import/{public_id}"
        return _web_redirect(target, selected_id, msg=exc.message, flash_type="error")
    msg = (f"本次新增 {applied.inserted_count} 条消费草稿，剩余 {applied.remaining_valid_rows} 条可导入。"
           "已存在记录和待复核事件请查看批次结果。")
    return _web_redirect(f"/web/import/{public_id}", selected_id, msg=msg)


@router.get("/import/{public_id}/errors.csv")
def web_import_batch_errors_csv(
    request: Request,
    public_id: str,
    ledger_id: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    try:
        content = "\ufeff" + build_csv_import_errors_csv(
            db,
            tenant_id=selected_id,
            public_id=public_id,
        )
    except AppError as exc:
        return _web_redirect("/web/import", selected_id, msg=exc.message, flash_type="error")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ticketbox-import-errors.csv"'},
    )


@router.post("/import/confirm")
def web_import_confirm(
    request: Request,
    ledger_id: str = Form(""),
    payload: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    del payload
    return _web_redirect(
        "/web/import",
        selected_id,
        msg="CSV 导入已升级为服务端批次流程，请重新上传 CSV。",
        flash_type="error",
    )
