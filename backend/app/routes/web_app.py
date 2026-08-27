"""Web account center — root redirect, confirmed, stats, expense edit.

v0.4-alpha3 slice 2: this module is the slim host for the /web pages that
remain in ``web_app.py``. Pending / bulk live in ``web_pending.py``, rules
live in ``web_rules.py``, helpers and the loopback gate live in
``web_common.py``.

218-D S4: ``/web`` no longer renders the legacy dashboard — it 303s into the
inbox domain home ``/web/pending`` (矿 IA 收件首域). The remaining
``/web/dashboard/cards`` routes own overview-card preferences only.

It re-exports ``_require_local`` and ``templates`` because existing tests
import them from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import projection_sum_to_int
from app.routes._web_bulk_snapshot import parse_bulk_snapshot
from app.routes._web_expense_return_context import edit_context_params
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _confirmed_by_day,
    _confirmed_source_breakdown,
    _expense_view,
    _list_ledger_options,
    _require_local,  # re-exported for tests
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import average_minor_amount
from app.services.expense_service import (
    batch_update_confirmed_expenses,
    list_confirmed,
)
from app.services.spending_contract_service import (
    accounting_timezone_key,
    current_accounting_month,
)
from app.services.stats_service import monthly_stats
from app.tag_text import parse_tags

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])
_CONFIRMED_PAGE_SIZE = 50


@router.get("", response_class=RedirectResponse, include_in_schema=False)
def web_root(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # 218-D S4 (裁决, 矿 IA): /web 根不再渲染仪表盘, 303 进收件域首页。
    # 账本解析保持原语义 (默认回落 owner), ledger_id 随跳转透传。
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _web_redirect("/web/pending", selected_id)


@router.get("/", response_class=RedirectResponse, include_in_schema=False)
def web_root_slash(
    ledger_id: str | None = None,
    _local: None = LocalOnly,
) -> RedirectResponse:
    if ledger_id:
        return _web_redirect("/web/pending", ledger_id)
    return RedirectResponse(url="/web/pending", status_code=303)


def _confirmed_redirect(
    selected_id: str,
    *,
    month: str = "",
    tag: str = "",
    page: int = 1,
    msg: str = "",
) -> RedirectResponse:
    page_value = str(page) if page > 1 else ""
    return _web_redirect(
        "/web/confirmed",
        selected_id,
        month=month,
        tag=tag,
        page=page_value,
        msg=msg,
    )


def _confirmed_month_context(
    db: Session,
    *,
    selected_id: str,
    effective_month: str,
    currency_code: str,
    tag: str | None,
) -> dict:
    """Build the confirmed-ledger summary without bloating the route handler."""

    month_stats = monthly_stats(
        db,
        effective_month,
        selected_id,
        timezone_name=accounting_timezone_key(),
        tag=tag,
    )
    month_total_cents = projection_sum_to_int(
        month_stats.get("total_amount_cents", 0),
        label="web.confirmed_month_total",
    )
    month_total_count = int(month_stats.get("count", 0))
    by_day = _confirmed_by_day(
        db,
        selected_id,
        effective_month,
        currency_code=currency_code,
        tag=tag,
    )
    peak_day_cents = max(
        (
            projection_sum_to_int(
                item["amount_cents"],
                label="web.confirmed_peak_day",
            )
            for item in by_day
        ),
        default=0,
    )
    return {
        "month_total_amount_yuan": _amount_yuan(month_total_cents, currency_code),
        "month_total_count": month_total_count,
        "month_average_amount_yuan": _amount_yuan(
            average_minor_amount(month_total_cents, month_total_count),
            currency_code,
        ),
        "month_peak_amount_yuan": _amount_yuan(peak_day_cents, currency_code),
        "by_day": by_day,
        "source_breakdown": _confirmed_source_breakdown(
            db,
            selected_id,
            effective_month,
            tag=tag,
        ),
    }


def _confirmed_items(expenses, home_currency_code: str) -> list[dict]:
    return [
        _expense_view(expense, presentation_currency_code=home_currency_code)
        for expense in expenses
    ]


def _confirmed_edit_query(
    selected_id: str,
    *,
    effective_month: str,
    page: int,
    tag: str | None,
) -> str:
    return urlencode(
        {
            "ledger_id": selected_id,
            **edit_context_params(
                "confirmed",
                return_month=effective_month,
                return_page=str(page),
                return_tag=tag or "",
            ),
        }
    )


def _render_confirmed_page(
    request: Request,
    db: Session,
    options,
    selected_id: str,
    *,
    page: int,
    month: str | None,
    tag: str | None,
    msg: str | None,
    status_code: int = 200,
    flash_type: str = "",
    selected_expense_ids: list[int] | None = None,
    batch_category_input: str = "",
    batch_tags_input: str = "",
) -> HTMLResponse:
    timezone_name = accounting_timezone_key()
    effective_month = month or current_accounting_month(timezone_name)
    expenses, total = list_confirmed(
        db,
        tenant_id=selected_id,
        page=page,
        page_size=_CONFIRMED_PAGE_SIZE,
        month=effective_month,
        tag=tag,
        timezone_name=timezone_name,
    )
    home = require_runtime_home_currency_code(db)
    items = _confirmed_items(expenses, home)
    total_pages = max(1, (total + _CONFIRMED_PAGE_SIZE - 1) // _CONFIRMED_PAGE_SIZE)
    pager_params = {"ledger_id": selected_id, "month": effective_month}
    if tag:
        pager_params["tag"] = tag
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="已确认",
        show_month_picker=True,
        selected_month=effective_month,
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx.update(
        expenses=items,
        page=page,
        total_pages=total_pages,
        total=total,
        month=effective_month,
        tag=tag or "",
        pager_query=urlencode(pager_params),
        confirmed_edit_query=_confirmed_edit_query(
            selected_id,
            effective_month=effective_month,
            page=page,
            tag=tag,
        ),
    )
    ctx.update(
        _confirmed_month_context(
            db,
            selected_id=selected_id,
            effective_month=effective_month,
            currency_code=home,
            tag=tag,
        )
    )
    ctx.update(
        flash_message=msg or "",
        flash_type=flash_type,
        selected_expense_ids=set(selected_expense_ids or []),
        batch_category_input=batch_category_input,
        batch_tags_input=batch_tags_input,
    )
    return templates.TemplateResponse(
        request=request,
        name="confirmed.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    tag: str | None = None,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_confirmed_page(
        request,
        db,
        options,
        selected_id,
        page=page,
        month=month,
        tag=tag,
        msg=msg,
    )


def _confirmed_batch_payload(
    *,
    action: str,
    expense_ids: list[int],
    expected_row_version_by_id: dict[int, int],
    category: str,
    tags: str,
) -> tuple[ConfirmedExpenseBatchUpdateRequest | None, str]:
    action_clean = (action or "").strip()
    try:
        if action_clean == "set_category":
            category_clean = category.strip()
            if not category_clean:
                return None, "请填写分类。"
            return (
                ConfirmedExpenseBatchUpdateRequest(
                    expense_ids=expense_ids,
                    expected_row_version_by_id=expected_row_version_by_id,
                    category=category_clean,
                ),
                "",
            )
        if action_clean == "set_tags":
            tags_clean = tags.strip()
            tag_names = parse_tags(tags_clean)
            if not tag_names:
                return None, "请填写标签。"
            tags_clean = ", ".join(tag_names)
            return (
                ConfirmedExpenseBatchUpdateRequest(
                    expense_ids=expense_ids,
                    expected_row_version_by_id=expected_row_version_by_id,
                    tags=tags_clean,
                ),
                "",
            )
        return None, "批处理操作不正确。"
    except ValidationError as exc:
        first_field = str(exc.errors(include_url=False)[0]["loc"][-1])
        if first_field == "category":
            return None, "分类最多 64 个字符。"
        if first_field == "tags" and len(tags) > 500:
            return None, "标签最多 500 个字符。"
        if first_field == "tags":
            return None, "单个标签最多 64 个字符。"
        return None, "批处理参数不正确。"


def _confirmed_batch_result_message(
    result: ConfirmedExpenseBatchUpdateResponse,
) -> str:
    parts: list[str] = []
    if result.updated_count:
        parts.append(f"已更新 {result.updated_count} 条")
    if result.skipped_not_found:
        parts.append(f"跳过 {result.skipped_not_found} 条：不属于当前账本")
    if result.skipped_not_confirmed:
        parts.append(f"跳过 {result.skipped_not_confirmed} 条：不是已入账")
    if not parts:
        parts.append("没有可更新的账单")
    return "；".join(parts) + "。"


@dataclass(frozen=True)
class _ConfirmedBatchOutcome:
    selected_expense_ids: list[int]
    result: ConfirmedExpenseBatchUpdateResponse | None = None
    error_message: str = ""
    error_status: int = 422


def _execute_confirmed_batch(
    db: Session,
    *,
    selected_id: str,
    action: str,
    expense_ids: list[int],
    expected_row_version: list[str],
    expense_snapshot: list[str],
    category: str,
    tags: str,
) -> _ConfirmedBatchOutcome:
    parsed_snapshot = parse_bulk_snapshot(
        expense_ids,
        expected_row_version,
        expense_snapshot,
    )
    if parsed_snapshot is None:
        return _ConfirmedBatchOutcome(
            [], error_message="页面已过期，请刷新后重新批处理。"
        )
    selected_expense_ids, expected_row_version_by_id = parsed_snapshot
    if not selected_expense_ids:
        return _ConfirmedBatchOutcome([], error_message="请先勾选账单。")

    payload, error_message = _confirmed_batch_payload(
        action=action,
        expense_ids=selected_expense_ids,
        expected_row_version_by_id=expected_row_version_by_id,
        category=category,
        tags=tags,
    )
    if error_message or payload is None:
        return _ConfirmedBatchOutcome(
            selected_expense_ids,
            error_message=error_message or "批处理参数不正确。",
        )
    try:
        result = batch_update_confirmed_expenses(
            db, tenant_id=selected_id, payload=payload
        )
    except AppError as exc:
        db.rollback()
        message = (
            "账单已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            else exc.message
        )
        return _ConfirmedBatchOutcome(
            selected_expense_ids,
            error_message=message,
            error_status=exc.status_code,
        )
    return _ConfirmedBatchOutcome(selected_expense_ids, result=result)


@router.post("/confirmed/batch-update", response_class=HTMLResponse)
def web_confirmed_batch_update(
    request: Request,
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    expected_row_version: list[str] = Form(default=[]),
    expense_snapshot: list[str] = Form(default=[]),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    month: str = Form(default=""),
    tag: str = Form(default=""),
    page: int = Form(default=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error_page_args = {
        "page": page,
        "month": month or None,
        "tag": tag or None,
        "flash_type": "error",
        "batch_category_input": category,
        "batch_tags_input": tags,
    }
    outcome = _execute_confirmed_batch(
        db,
        selected_id=selected_id,
        action=action,
        expense_ids=expense_ids,
        expected_row_version=expected_row_version,
        expense_snapshot=expense_snapshot,
        category=category,
        tags=tags,
    )
    if outcome.error_message:
        return _render_confirmed_page(
            request,
            db,
            options,
            selected_id,
            msg=outcome.error_message,
            status_code=outcome.error_status,
            selected_expense_ids=outcome.selected_expense_ids,
            **error_page_args,
        )
    if outcome.result is None:
        raise AppError("server_error", status_code=500)
    return _confirmed_redirect(
        selected_id,
        month=month,
        tag=tag,
        page=page,
        msg=_confirmed_batch_result_message(outcome.result),
    )


# /web/expenses/{id}/image and /web/expenses/{id}/thumbnail moved to
# app/routes/web_media.py during the v0.4-alpha3 route split. They used to
# be duplicated here as a transitional shim; FastAPI's "first registered
# wins" rule meant the copy in this file was actually serving traffic and
# any fix applied to web_media.py would silently no-op. Removed.
