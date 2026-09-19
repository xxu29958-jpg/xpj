"""Human review of saved CSV events through the financial fact owner."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_money_views import _expense_view, _minor_amount_label
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    LedgerOption,
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import CsvImportReviewRequest, CsvImportRowResponse
from app.services.csv_import_batch_service._queries import get_csv_import_row
from app.services.csv_import_batch_service._review import review_csv_import_row
from app.services.expense_query import get_expense, search_import_root_expenses

if TYPE_CHECKING:
    from app.models import Expense

router = APIRouter(prefix="/web", tags=["web"])


def _optional_positive_int(raw: str) -> int | None:
    if not raw:
        return None
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or int(raw) < 1:
        raise AppError("invalid_request", "原单或页面版本无效，请重新选择原单。", status_code=422)
    return int(raw)


def _review_payload(draft: dict[str, str]) -> CsvImportReviewRequest:
    try:
        return CsvImportReviewRequest(
            expense_id=_optional_positive_int(draft["expense_id"]),
            expected_row_version=_optional_positive_int(draft["expected_row_version"]),
            reason=draft["reason"],
            acknowledge_incomplete_lineage=draft["acknowledge_incomplete_lineage"] == "true",
            manual_exchange_rate=draft["manual_exchange_rate"] or None,
            exchange_rate_date=draft["exchange_rate_date"] or None,
        )
    except ValidationError as exc:
        raise AppError("invalid_request", "请填写复核原因（1 至 500 字），并核对补录汇率和日期。", status_code=422) from exc


def _selected_root(db: Session, selected_id: str, row: CsvImportRowResponse,
                   draft: dict[str, str]) -> tuple[Expense | None, str]:
    try:
        expense_id = row.resolved_expense_id or _optional_positive_int(draft["expense_id"])
        root = get_expense(db, expense_id, selected_id) if expense_id else None
    except AppError as exc:
        return None, exc.message
    if root is not None:
        draft.update(expense_id=str(root.id), expected_row_version=str(root.row_version))
    return root, ""


def _review_context(db: Session, request: Request, options: list[LedgerOption], selected_id: str,
                    public_id: str, line_number: int, *, draft: dict[str, str], query: str,
                    page: int) -> dict[str, object]:
    row = get_csv_import_row(db, tenant_id=selected_id, public_id=public_id, line_number=line_number)
    root, selection_error = _selected_root(db, selected_id, row, draft)
    candidates, total = ([], 0)
    page = max(1, page)
    if row.entry_kind == "offset" and not row.resolved_expense_id:
        candidates, total = search_import_root_expenses(
            db, tenant_id=selected_id, query=query, page=page, page_size=20,
        )
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    path = f"/web/import/{public_id}/rows/{line_number}/review"
    origin = {"ledger_id": selected_id, "return_to": "csv_import_event",
              "return_import_public_id": public_id, "return_import_line_number": str(line_number),
              "return_import_expense_id": str(root.id) if root else ""}
    ctx.update(
        row=row, public_id=public_id, review_path=path, draft=draft, error=selection_error,
        root=_expense_view(root) if root else None,
        root_edit_href=f"/web/expenses/{root.id}/edit?{urlencode(origin)}" if root else "",
        candidates=[_expense_view(candidate) for candidate in candidates],
        query=query, page=page, total=total, total_pages=max(1, (total + 19) // 20),
        row_amount_label=_minor_amount_label,
        batch_href=f"/web/import/{public_id}?{urlencode({'ledger_id': selected_id})}",
        review_href=f"{path}?{urlencode({'ledger_id': selected_id})}",
    )
    return ctx


def _render_review(db: Session, request: Request, options: list[LedgerOption], selected_id: str,
                   public_id: str, line_number: int, *, draft: dict[str, str], query: str = "",
                   page: int = 1, error: AppError | None = None, message: str = "") -> Response:
    try:
        ctx = _review_context(db, request, options, selected_id, public_id, line_number,
                              draft=draft, query=query, page=page)
    except AppError as exc:
        return _web_redirect("/web/import", selected_id, msg=exc.message, flash_type="error")
    if error is not None:
        ctx["error"] = error.message
        if error.error == "state_conflict":
            ctx["error"] = "原单事实已变化，已载入最新原单和版本。你的原因已保留，请核对后再次提交。"
    ctx["flash_message"] = message
    return templates.TemplateResponse(request=request, name="import_event_review.html", context=ctx,
        status_code=error.status_code if error else 200, headers={"Cache-Control": "no-store"})


@router.get("/import/{public_id}/rows/{line_number}/review", response_class=HTMLResponse)
def web_import_event_review(request: Request, public_id: str, line_number: int, ledger_id: str = "",
                            expense_id: str = "", query: str = "", page: int = 1, msg: str = "",
                            reason: str = "", acknowledge_incomplete_lineage: str = "",
                            manual_exchange_rate: str = "", exchange_rate_date: str = "",
                            _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {"expense_id": expense_id, "expected_row_version": "", "reason": reason,
             "acknowledge_incomplete_lineage": acknowledge_incomplete_lineage,
             "manual_exchange_rate": manual_exchange_rate, "exchange_rate_date": exchange_rate_date}
    return _render_review(db, request, options, selected_id, public_id, line_number,
                          draft=draft, query=query, page=page, message=msg)


@router.post("/import/{public_id}/rows/{line_number}/review", response_class=HTMLResponse)
def web_import_event_submit(request: Request, public_id: str, line_number: int,
                            ledger_id: str = Form(default=""), expense_id: str = Form(default=""),
                            expected_row_version: str = Form(default=""), reason: str = Form(default=""),
                            acknowledge_incomplete_lineage: str = Form(default=""),
                            manual_exchange_rate: str = Form(default=""), exchange_rate_date: str = Form(default=""),
                            _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {"expense_id": expense_id, "expected_row_version": expected_row_version,
             "reason": reason, "acknowledge_incomplete_lineage": acknowledge_incomplete_lineage,
             "manual_exchange_rate": manual_exchange_rate, "exchange_rate_date": exchange_rate_date}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**draft, "ledger_id": ledger_id}, task="复核原 CSV 事件")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        payload = _review_payload(draft)
        account_id, device_id = resolve_web_actor(db, request, selected_id)
        auth = getattr(request.state, "web_session_auth", None)
        row = review_csv_import_row(db, tenant_id=selected_id, public_id=public_id,
            line_number=line_number, payload=payload, actor_account_id=account_id, actor_device_id=device_id,
            actor_device_public_id=getattr(auth, "device_public_id", None),
            actor_device_name=getattr(auth, "device_name", None))
    except AppError as exc:
        db.rollback()
        return _render_review(db, request, options, selected_id, public_id, line_number, draft=draft, error=exc)
    if row.status == "matched":
        message = "已关联本账本已有记录，没有重复导入。"
    elif row.status == "applied":
        message = "事件已入账。" if row.entry_kind == "offset" else "原消费已进入待确认，请复核后确认。"
    else:
        return _render_review(db, request, options, selected_id, public_id, line_number, draft=draft,
            error=AppError(row.error_code or "invalid_request", row.error_message or "此行仍需复核。", status_code=409))
    return _web_redirect(f"/web/import/{public_id}/rows/{line_number}/review", selected_id,
                         msg=message, flash_type="success")
