"""Web account center — root redirect, confirmed, stats, expense edit.

v0.4-alpha3 slice 2: this module is the slim host for the /web pages that
remain in ``web_app.py``. Pending / bulk live in ``web_pending.py``, rules
live in ``web_rules.py``, helpers and the loopback gate live in
``web_common.py``.

218-D S4: ``/web`` no longer renders the legacy dashboard — it 303s into the
inbox domain home ``/web/pending`` (矿 IA 收件首域). dashboard.html and the
``/web/dashboard/*`` endpoints stay untouched; their removal is a separate
cleanup slice.

It re-exports ``_require_local`` and ``templates`` because existing tests
import them from this module.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import projection_sum_to_int
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
    parse_form_row_version_token,
    templates,
)
from app.schemas import ConfirmedExpenseBatchUpdateRequest
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import average_minor_amount
from app.services.expense_service import (
    batch_update_confirmed_expenses,
    list_confirmed,
)
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])


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
    month_stats: dict,
) -> dict:
    """Build the confirmed-ledger summary without bloating the route handler."""

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
        ),
    }


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
    page_size = 50
    expenses, total = list_confirmed(
        db,
        tenant_id=selected_id,
        page=page,
        page_size=page_size,
        month=month,
        tag=tag,
    )
    home = require_runtime_home_currency_code(db)
    items = [
        _expense_view(e, presentation_currency_code=home)
        for e in expenses
    ]
    total_pages = max(1, (total + page_size - 1) // page_size)
    pager_params = {"ledger_id": selected_id}
    if month:
        pager_params["month"] = month
    if tag:
        pager_params["tag"] = tag
    effective_month = month or current_month("Asia/Shanghai")
    month_stats = monthly_stats(
        db, effective_month, selected_id, timezone_name="Asia/Shanghai"
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
    ctx["expenses"] = items
    ctx["page"] = page
    ctx["total_pages"] = total_pages
    ctx["total"] = total
    ctx["month"] = month or ""
    ctx["tag"] = tag or ""
    ctx["pager_query"] = urlencode(pager_params)
    ctx.update(
        _confirmed_month_context(
            db,
            selected_id=selected_id,
            effective_month=effective_month,
            currency_code=home,
            month_stats=month_stats,
        )
    )
    ctx["flash_message"] = msg or ""
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)


@router.post("/confirmed/batch-update", response_class=HTMLResponse)
def web_confirmed_batch_update(
    request: Request,
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    expected_row_version: list[str] = Form(default=[]),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    month: str = Form(default=""),
    tag: str = Form(default=""),
    page: int = Form(default=1),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)

    if not expense_ids:
        return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请先勾选账单。")

    if len(expected_row_version) != len(expense_ids):
        return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="页面已过期，请刷新后重新批处理。")
    expected_row_version_by_id = {}
    for expense_id, raw_token in zip(expense_ids, expected_row_version, strict=True):
        parsed_token = parse_form_row_version_token(raw_token)
        if parsed_token is None:
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="页面已过期，请刷新后重新批处理。")
        expected_row_version_by_id[expense_id] = parsed_token

    action_clean = (action or "").strip()
    if action_clean == "set_category":
        category_clean = category.strip()
        if not category_clean:
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请填写分类。")
        payload = ConfirmedExpenseBatchUpdateRequest(
            expense_ids=expense_ids,
            expected_row_version_by_id=expected_row_version_by_id,
            category=category_clean,
        )
    elif action_clean == "set_tags":
        tags_clean = tags.strip()
        if not tags_clean:
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="请填写标签。")
        payload = ConfirmedExpenseBatchUpdateRequest(
            expense_ids=expense_ids,
            expected_row_version_by_id=expected_row_version_by_id,
            tags=tags_clean,
        )
    else:
        raise AppError("invalid_request", status_code=422)

    try:
        result = batch_update_confirmed_expenses(db, tenant_id=selected_id, payload=payload)
    except AppError as exc:
        if exc.error == "state_conflict":
            return _confirmed_redirect(selected_id, month=month, tag=tag, page=page, msg="账单已在其它端被修改，请刷新后重试。")
        raise
    parts: list[str] = []
    if result.updated_count:
        parts.append(f"已更新 {result.updated_count} 条")
    if result.skipped_not_found:
        parts.append(f"跳过 {result.skipped_not_found} 条：不属于当前账本")
    if result.skipped_not_confirmed:
        parts.append(f"跳过 {result.skipped_not_confirmed} 条：不是已入账")
    if not parts:
        parts.append("没有可更新的账单")
    return _confirmed_redirect(
        selected_id,
        month=month,
        tag=tag,
        page=page,
        msg="；".join(parts) + "。",
    )


# /web/expenses/{id}/image and /web/expenses/{id}/thumbnail moved to
# app/routes/web_media.py during the v0.4-alpha3 route split. They used to
# be duplicated here as a transitional shim; FastAPI's "first registered
# wins" rule meant the copy in this file was actually serving traffic and
# any fix applied to web_media.py would silently no-op. Removed.
