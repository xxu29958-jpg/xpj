"""/web/import + /web/export pages.

CSV export is a thin LocalOnly wrapper around the existing service so the
desktop user does not have to copy an app token. CSV import now uses the same
server-side batch tables as ``/api/imports/csv``: upload creates a durable
preview batch, the detail page pages through row results, and apply inserts
valid rows as ``pending`` expenses in chunks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.services.csv_import_batch_service import (
    MAX_CSV_IMPORT_ROWS,
    apply_csv_import_batch,
    build_csv_import_errors_csv,
    create_csv_import_batch,
    get_csv_import_batch,
    list_csv_import_rows,
)
from app.services.stats_service import export_confirmed_csv

router = APIRouter(prefix="/web", tags=["web"])


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
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["max_rows"] = MAX_CSV_IMPORT_ROWS
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
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
    _require_selected_ledger_write(options, selected_id)
    batch = create_csv_import_batch(
        db,
        tenant_id=selected_id,
        file_name=csv_file.filename,
        file_obj=csv_file.file,
    )
    msg = f"已解析 {batch.total_rows} 行，{batch.valid_rows} 行可导入。"
    target = _with_ledger(f"/web/import/{batch.public_id}", selected_id, msg=msg)
    return RedirectResponse(url=target, status_code=303)


@router.get("/import/{public_id}", response_class=HTMLResponse)
def web_import_batch_detail(
    request: Request,
    public_id: str,
    ledger_id: str = "",
    page: int = 1,
    page_size: int = 100,
    status: str | None = None,
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    batch = get_csv_import_batch(db, tenant_id=selected_id, public_id=public_id)
    rows_page = list_csv_import_rows(
        db,
        tenant_id=selected_id,
        public_id=public_id,
        page=page,
        page_size=page_size,
        status=status,
    )
    total_pages = max(1, (rows_page.total + rows_page.page_size - 1) // rows_page.page_size)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx.update(
        {
            "batch": batch,
            "rows": rows_page.items,
            "page": rows_page.page,
            "page_size": rows_page.page_size,
            "total": rows_page.total,
            "total_pages": total_pages,
            "status": status or "",
            "flash_message": msg,
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
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    safe_batch_size = min(max(batch_size, 1), 1000)
    applied = apply_csv_import_batch(
        db,
        tenant_id=selected_id,
        public_id=public_id,
        batch_size=safe_batch_size,
    )
    msg = f"本次导入 {applied.inserted_count} 条，剩余 {applied.remaining_valid_rows} 条可导入。"
    target = _with_ledger(f"/web/import/{public_id}", selected_id, msg=msg)
    return RedirectResponse(url=target, status_code=303)


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
    content = "\ufeff" + build_csv_import_errors_csv(
        db,
        tenant_id=selected_id,
        public_id=public_id,
    )
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
    target = _with_ledger(
        "/web/import",
        selected_id,
        msg="CSV 导入已升级为服务端批次流程，请重新上传 CSV。",
    )
    return RedirectResponse(url=target, status_code=303)
