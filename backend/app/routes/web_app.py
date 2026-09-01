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

from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.money_contract import projection_sum_to_int
from app.routes._web_expense_return_context import edit_context_params
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _confirmed_by_day,
    _confirmed_source_breakdown,
    _expense_view,
    _lineage_chip,
    _list_ledger_options,
    _offset_stream_view,
    _require_local,  # re-exported for tests
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import average_minor_amount
from app.services.expense_service import list_confirmed
from app.services.spending_contract_service import (
    accounting_timezone_key,
    current_accounting_month,
)
from app.services.stats_service import monthly_stats

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


def _confirmed_items(entries, home_currency_code: str) -> list[dict]:
    """typed stream → 行视图模型。offset 与 expense 是两种行形态, 不互套
    Expense 视图; 每行只携带 server 给的 stream_date/stream_amount_cents,
    符号与归属不重算。"""
    items: list[dict] = []
    for entry in entries:
        if entry.entry_kind == "offset":
            items.append(_offset_stream_view(entry, home_currency_code=home_currency_code))
            continue
        view = _expense_view(entry.root, presentation_currency_code=home_currency_code)
        view.update(
            entry_kind="expense",
            stream_date=entry.stream_date.isoformat(),
            stream_amount_cents=entry.stream_amount_cents,
            **_lineage_chip(entry.lineage_status),
        )
        items.append(view)
    return items


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


def _confirmed_page_rows(
    db: Session,
    *,
    selected_id: str,
    page: int,
    month: str | None,
    tag: str | None,
) -> tuple[str, str, list[dict], int, int, str]:
    timezone_name = accounting_timezone_key()
    effective_month = month or current_accounting_month(timezone_name)
    entries, total = list_confirmed(
        db,
        tenant_id=selected_id,
        page=page,
        page_size=_CONFIRMED_PAGE_SIZE,
        month=effective_month,
        tag=tag,
        timezone_name=timezone_name,
    )
    home = require_runtime_home_currency_code(db)
    total_pages = max(1, (total + _CONFIRMED_PAGE_SIZE - 1) // _CONFIRMED_PAGE_SIZE)
    pager_params = {"ledger_id": selected_id, "month": effective_month}
    if tag:
        pager_params["tag"] = tag
    return (
        effective_month,
        home,
        _confirmed_items(entries, home),
        total,
        total_pages,
        urlencode(pager_params),
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
    batch_reason_input: str = "",
    batch_idempotency_key: str = "",
) -> HTMLResponse:
    effective_month, home, items, total, total_pages, pager_query = _confirmed_page_rows(
        db, selected_id=selected_id, page=page, month=month, tag=tag
    )
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
        pager_query=pager_query,
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
        batch_reason_input=batch_reason_input,
        batch_idempotency_key=batch_idempotency_key or str(uuid4()),
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


# /web/expenses/{id}/image and /web/expenses/{id}/thumbnail moved to
# app/routes/web_media.py during the v0.4-alpha3 route split. They used to
# be duplicated here as a transitional shim; FastAPI's "first registered
# wins" rule meant the copy in this file was actually serving traffic and
# any fix applied to web_media.py would silently no-op. Removed.
