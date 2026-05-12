"""/web/import + /web/export pages (v0.4-alpha3 slice 2 / PR17).

CSV export is a thin LocalOnly wrapper around the existing service so the
desktop user does not have to copy an app token. CSV import is a two-step
preview/confirm form: upload → preview rows + warnings → confirm to
insert as ``pending`` rows for review on /web/pending.

Hard limits keep the in-memory parser safe:

* upload size ≤ 1 MiB
* row count ≤ ``MAX_PREVIEW_ROWS`` (500)
* preview payload kept in a hidden field so the confirm step does not
  need a server-side cache (and stays stateless across reboots).
"""

from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.services.import_service import (
    MAX_PREVIEW_ROWS,
    ParsedRow,
    import_rows,
    parse_csv_preview,
)
from app.services.stats_service import export_confirmed_csv


router = APIRouter(prefix="/web", tags=["web"])

MAX_UPLOAD_BYTES = 1 * 1024 * 1024


@router.get("/export.csv")
def web_export_csv(
    ledger_id: str = "",
    month: str | None = None,
    category: str | None = None,
    timezone: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    content = "\ufeff" + export_confirmed_csv(
        db,
        tenant_id=selected_id,
        month=month,
        category=category,
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["preview"] = None
    ctx["max_rows"] = MAX_PREVIEW_ROWS
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="import_export.html", context=ctx
    )


def _serialize_rows_for_confirm(rows: list[ParsedRow]) -> str:
    valid = [
        {
            "amount_cents": r.amount_cents,
            "merchant": r.merchant,
            "category": r.category,
            "note": r.note,
            "expense_time": r.expense_time.isoformat() if r.expense_time else None,
            "tags": r.tags,
            "source": r.source,
        }
        for r in rows
        if r.is_valid
    ]
    return json.dumps(valid, ensure_ascii=False)


@router.post("/import/preview", response_class=HTMLResponse)
async def web_import_preview(
    request: Request,
    ledger_id: str = Form(""),
    csv_file: UploadFile = File(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    raw = await csv_file.read()
    if not raw:
        raise AppError("invalid_request", "请上传非空的 CSV 文件。", status_code=400)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AppError(
            "invalid_request",
            f"CSV 文件过大（>{MAX_UPLOAD_BYTES // 1024} KiB）。",
            status_code=400,
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030", errors="replace")
    preview = parse_csv_preview(text)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["preview"] = preview
    ctx["max_rows"] = MAX_PREVIEW_ROWS
    ctx["flash_message"] = ""
    ctx["q"] = "?ledger_id=" + selected_id
    ctx["confirm_payload"] = _serialize_rows_for_confirm(preview.rows)
    ctx["filename"] = csv_file.filename or "imported.csv"
    return templates.TemplateResponse(
        request=request, name="import_export.html", context=ctx
    )


@router.post("/import/confirm")
def web_import_confirm(
    ledger_id: str = Form(""),
    payload: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    try:
        items = json.loads(payload or "[]")
    except json.JSONDecodeError:
        raise AppError("invalid_request", "导入数据已损坏，请重新预览。", status_code=400)
    if not isinstance(items, list) or not items:
        target = _with_ledger("/web/import", selected_id, msg="没有可导入的有效行。")
        return RedirectResponse(url=target, status_code=303)
    if len(items) > MAX_PREVIEW_ROWS:
        raise AppError(
            "invalid_request",
            f"一次最多导入 {MAX_PREVIEW_ROWS} 行。",
            status_code=400,
        )
    rebuilt: list[ParsedRow] = []
    from datetime import datetime
    for index, item in enumerate(items, start=2):
        if not isinstance(item, dict):
            continue
        amount_cents = item.get("amount_cents")
        if not isinstance(amount_cents, int) or amount_cents < 0:
            continue
        expense_time_raw = item.get("expense_time")
        expense_time = None
        if isinstance(expense_time_raw, str) and expense_time_raw:
            try:
                expense_time = datetime.fromisoformat(expense_time_raw)
            except ValueError:
                expense_time = None
        rebuilt.append(
            ParsedRow(
                line_number=index,
                amount_cents=amount_cents,
                merchant=str(item.get("merchant") or "").strip(),
                category=str(item.get("category") or "其他").strip() or "其他",
                note=str(item.get("note") or "").strip(),
                expense_time=expense_time,
                tags=str(item.get("tags") or "").strip(),
                source=str(item.get("source") or "CSV导入").strip() or "CSV导入",
            )
        )
    inserted = import_rows(db, tenant_id=selected_id, rows=rebuilt)
    msg = f"已导入 {inserted} 条待确认账单。请到「待确认」页面复核。"
    target = _with_ledger("/web/import", selected_id, msg=msg)
    # quote msg to keep CJK readable when reflected
    return RedirectResponse(url=quote(target, safe="/?=&"), status_code=303)
