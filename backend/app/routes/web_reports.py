"""/web/reports page backed by the v0.9 reports service."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routes._web_expense_return_context import ExpenseReturnContext, flow_href, return_context_params
from app.routes._web_report_money_views import (
    category_comparison_view as _category_comparison_view,
)
from app.routes._web_report_money_views import (
    money as _money,
)
from app.routes._web_report_money_views import (
    percent as _percent,
)
from app.routes._web_report_money_views import (
    projected_amount as _projected_amount,
)
from app.routes._web_report_money_views import projection_gaps_view
from app.routes._web_report_money_views import (
    six_month_average_amount_yuan as _six_month_average_amount_yuan,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import currency_input_metadata, normalize_currency_code
from app.services.monthly_report_service import (
    BudgetExplanation,
    MonthlyReport,
    compose_budget_explanation,
    compose_monthly_report,
)
from app.services.reports_service import (
    export_reports_overview_csv,
    reports_overview,
    six_month_summary,
    top_expenses_for_month,
)
from app.services.spending_contract_service import accounting_datetime_label
from app.services.time_service import current_month

router = APIRouter(prefix="/web/reports", tags=["web"])

_GRANULARITIES = {"day", "week", "month"}
_RANKING_METRICS = {"amount", "count"}


def _clean_granularity(value: str | None) -> str:
    clean = (value or "day").strip().lower()
    return clean if clean in _GRANULARITIES else "day"


def _clean_ranking_metric(value: str | None) -> str:
    clean = (value or "amount").strip().lower()
    return clean if clean in _RANKING_METRICS else "amount"


def _amount_rows_view(rows: list[dict], *, currency_code: str) -> list[dict]:
    amounts = [_money(row["amount_cents"], "row_amount") for row in rows]
    maximum = max((amount for amount in amounts if amount is not None), default=0)
    return [{**row, "amount_cents": amount, "amount_yuan": _projected_amount(amount, currency_code),
        "count": int(row["count"]), "percent": _percent(amount, maximum)} for row, amount in zip(rows, amounts, strict=True)]


def _view_model(payload: dict) -> dict:
    home = payload["home_currency_code"]
    view = {**payload, "merchant_category": payload["merchant_category"] or "",
        "missing_rates": projection_gaps_view(payload["missing_rates"])}
    for field in ("total_amount", "previous_total_amount", "year_over_year_total_amount", "year_over_year_delta_amount"):
        amount = _money(payload[f"{field}_cents"], field)
        view[f"{field}_cents"] = amount
        view[f"{field}_yuan"] = _projected_amount(amount, home)
    view.update(trend=_amount_rows_view(payload["trend"], currency_code=home),
        merchant_ranking=_amount_rows_view(payload["merchant_ranking"], currency_code=home),
        category_comparison=_category_comparison_view(payload["category_comparison"], currency_code=home))
    view["merchant_amount_unavailable"] = (
        any(row["category"] == view["merchant_category"] and row["amount_cents"] is None
            for row in payload["category_comparison"])
        if view["merchant_category"] else payload["total_amount_cents"] is None)
    return view


def _monthly_report_view_model(report: MonthlyReport) -> dict:
    home = report.home_currency_code
    return {
        "year_month": report.year_month,
        "home_currency_code": home,
        "missing_rates": report.missing_rates,
        "total_amount_yuan": _projected_amount(report.total_cents, home),
        "expense_count": report.expense_count,
        "delta_vs_previous_yuan": _projected_amount(report.delta_vs_previous_cents, home),
        "delta_pct": report.delta_pct,
        "top_categories": [
            {
                "category": row.category,
                "amount_cents": row.amount_cents,
                "amount_yuan": _projected_amount(row.amount_cents, home),
                "count": row.count,
            }
            for row in report.top_categories
        ],
    }


def _budget_explanation_view_model(item: BudgetExplanation) -> dict:
    home = item.home_currency_code
    return {
        "category": item.category,
        "year_month": item.year_month,
        "home_currency_code": home,
        "missing_rates": item.missing_rates,
        "actual_yuan": _projected_amount(item.actual_cents, home),
        "p50_yuan": _projected_amount(item.p50_cents, home),
        "p75_yuan": _projected_amount(item.p75_cents, home),
        "delta_vs_p75_yuan": _projected_amount(item.delta_vs_p75_cents, home),
        "verdict": item.verdict,
        "verdict_label": _budget_verdict_label(item.verdict),
    }


def _budget_verdict_label(value: str) -> str:
    labels = {
        "under": "低于常规",
        "on_track": "节奏正常",
        "over_p75": "高于 P75",
        "no_history": "历史不足",
        "projection_unavailable": "待补信息",
    }
    return labels.get(value, value)


def _top_expenses_view(
    db: Session, *, tenant_id: str, month: str, timezone_name: str, presentation_currency_code: str,
    return_context: ExpenseReturnContext,
) -> dict:
    projection = top_expenses_for_month(db, tenant_id=tenant_id, month=month,
        timezone_name=timezone_name, home_currency_code=presentation_currency_code)
    rows = []
    for item in projection.items:
        expense = item.expense
        rows.append({
            "merchant": expense.merchant or "未填写商家",
            "edit_href": flow_href(f"/web/expenses/{expense.id}/edit", ledger_id=tenant_id,
                **return_context.as_kwargs()),
            "amount_yuan": _projected_amount(item.amount_cents, projection.home_currency_code),
            "category": expense.category or "未分类",
            "expense_time": accounting_datetime_label(expense.expense_time, timezone_name, pattern="%Y-%m-%d"),
        })
    return {"top_expenses": rows, "top_expenses_missing_rates": projection.missing_rates}


def _monthly_report_sections(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str,
    currency_code: str,
) -> tuple[dict, list[dict]]:
    """Read both monthly projections in the captured display currency."""
    monthly_report = compose_monthly_report(
        db,
        tenant_id=tenant_id,
        year_month=month,
        timezone_name=timezone_name,
        home_currency_code=currency_code,
    )
    explanations = [
        compose_budget_explanation(
            db,
            tenant_id=tenant_id,
            category=row.category,
            year_month=month,
            timezone_name=timezone_name,
            home_currency_code=currency_code,
        )
        for row in monthly_report.top_categories[:5]
    ]
    return (
        _monthly_report_view_model(monthly_report),
        [_budget_explanation_view_model(item) for item in explanations],
    )


def _six_month_history_view(rows: list[dict], *, currency_code: str) -> dict:
    """Keep the history chart, accessible table, and average on the same series."""
    amounts_known = all(row["amount_cents"] is not None and row["budget_cents"] is not None for row in rows)
    return {
        "six_month_trend": [{**row, "missing_rates": projection_gaps_view(row["missing_rates"]),
            "reference_rates": projection_gaps_view(row["reference_rates"])} for row in rows],
        "six_month_average_amount_yuan": _six_month_average_amount_yuan(rows, currency_code=currency_code),
        "overspent_months": sum(row["amount_cents"] > row["budget_cents"] > 0 for row in rows) if amounts_known else None,
    }


def _report_projection_context(payload, history, top, monthly, explanations) -> dict:
    home = payload["home_currency_code"]
    currency = currency_input_metadata(home)
    gaps = [*payload["missing_rates"], *top["top_expenses_missing_rates"]]
    for projection in [*history, *explanations, *([monthly] if monthly else [])]:
        gaps.extend(projection["missing_rates"])
    return {"report": _view_model(payload), "monthly_report": monthly, "budget_explanations": explanations,
        "report_missing_rates": projection_gaps_view(dict.fromkeys(gaps)), **top,
        "home_currency_code": home, "home_currency_symbol": currency["currency_symbol"],
        "home_currency_minor_digits": currency["minor_unit_digits"],
        **_six_month_history_view(history, currency_code=home)}


@router.get("", response_class=HTMLResponse)
def web_reports(
    request: Request,
    month: str | None = None,
    granularity: str | None = None,
    ranking_metric: str | None = None,
    merchant_category: str | None = Query(default=None, max_length=64),
    home_currency_code: str | None = None,
    ledger_id: str | None = None,
    msg: str | None = None,
    flash_type: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    selected_granularity = _clean_granularity(granularity)
    selected_metric = _clean_ranking_metric(ranking_metric)
    payload = reports_overview(
        db,
        month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        granularity=selected_granularity,
        ranking_metric=selected_metric,
        merchant_category=merchant_category,
        home_currency_code=home,
    )
    monthly_report_vm, budget_explanations = _monthly_report_sections(
        db,
        tenant_id=selected_id,
        month=target_month,
        timezone_name=timezone_name,
        currency_code=home,
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="报表",
        show_month_picker=True,
        selected_month=target_month,
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    six_month_trend = six_month_summary(
        db,
        anchor_month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        currency_code=home,
    )
    origin = ExpenseReturnContext(return_to="reports", return_month=target_month,
        return_home_currency_code=home, return_granularity=selected_granularity,
        return_ranking_metric=selected_metric, return_merchant_category=merchant_category or "")
    report_query = {"ledger_id": selected_id, **return_context_params(**origin.as_kwargs())}
    top = _top_expenses_view(db, tenant_id=selected_id, month=target_month,
        timezone_name=timezone_name, presentation_currency_code=home, return_context=origin)
    ctx.update(
        {
            "flash_message": msg or "",
            "flash_type": flash_type if flash_type in ("success", "error") else "",
            **_report_projection_context(payload, six_month_trend, top, monthly_report_vm, budget_explanations),
            "report_export_query": urlencode(report_query),
            "month": target_month,
            "month_picker_query": report_query,
            "granularity_options": [("day", "日"), ("week", "周"), ("month", "月")],
            "ranking_metric_options": [("amount", "金额"), ("count", "笔数")],
        }
    )
    return templates.TemplateResponse(request=request, name="reports.html", context=ctx)


@router.get("/export.csv")
def web_reports_csv(
    request: Request,
    month: str | None = None,
    granularity: str | None = None,
    ranking_metric: str | None = None,
    merchant_category: str | None = Query(default=None, max_length=64),
    home_currency_code: str | None = None,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    timezone_name = get_settings().ocr_default_timezone
    target_month = (month or "").strip() or current_month(timezone_name)
    selected_granularity = _clean_granularity(granularity)
    selected_metric = _clean_ranking_metric(ranking_metric)
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    content = "\ufeff" + export_reports_overview_csv(
        db,
        month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        granularity=selected_granularity,
        ranking_metric=selected_metric,
        merchant_category=merchant_category,
        home_currency_code=home,
    )
    filename = f"ticketbox-web-reports-{target_month}-{selected_granularity}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
