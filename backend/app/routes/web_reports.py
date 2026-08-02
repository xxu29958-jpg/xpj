"""/web/reports page backed by the v0.9 reports service."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
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
    six_month_average_amount_yuan as _six_month_average_amount_yuan,
)
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
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
)
from app.services.stats_service import top_expenses_for_month
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


def _trend_view(points: list[dict], *, currency_code: str) -> list[dict]:
    maximum = max(
        [_money(point["amount_cents"], "trend") for point in points]
        or [0]
    )
    return [
        {
            "bucket": point["bucket"],
            "label": point["label"],
            "amount_yuan": _amount_yuan(
                _money(point["amount_cents"], "trend"),
                currency_code,
            ),
            "amount_cents": _money(point["amount_cents"], "trend"),
            "count": int(point["count"]),
            "percent": _percent(
                _money(point["amount_cents"], "trend"),
                maximum,
            ),
        }
        for point in points
    ]


def _merchant_ranking_view(
    rows: list[dict],
    *,
    currency_code: str,
) -> list[dict]:
    maximum = max(
        [_money(row["amount_cents"], "merchant") for row in rows]
        or [0]
    )
    return [
        {
            "merchant": row["merchant"],
            "amount_yuan": _amount_yuan(
                _money(row["amount_cents"], "merchant"),
                currency_code,
            ),
            "amount_cents": _money(row["amount_cents"], "merchant"),
            "count": int(row["count"]),
            "percent": _percent(
                _money(row["amount_cents"], "merchant"),
                maximum,
            ),
        }
        for row in rows
    ]


def _view_model(payload: dict, *, currency_code: str) -> dict:
    return {
        "month": payload["month"],
        "timezone": payload["timezone"],
        "granularity": payload["granularity"],
        "ranking_metric": payload["ranking_metric"],
        "merchant_category": payload["merchant_category"] or "",
        "total_amount_yuan": _amount_yuan(
            _money(payload["total_amount_cents"], "overview_total"),
            currency_code,
        ),
        "count": int(payload["count"]),
        "previous_month": payload["previous_month"],
        "previous_total_amount_yuan": _amount_yuan(
            _money(
                payload["previous_total_amount_cents"],
                "overview_previous_total",
            ),
            currency_code,
        ),
        "previous_count": int(payload["previous_count"]),
        "year_over_year_month": payload["year_over_year_month"],
        "year_over_year_total_amount_yuan": _amount_yuan(
            _money(
                payload["year_over_year_total_amount_cents"],
                "overview_yoy_total",
            ),
            currency_code,
        ),
        "year_over_year_count": int(payload["year_over_year_count"]),
        "year_over_year_delta_amount_yuan": _amount_yuan(
            _money(
                payload["year_over_year_delta_amount_cents"],
                "overview_yoy_delta",
            ),
            currency_code,
        ),
        "year_over_year_delta_amount_cents": _money(
            payload["year_over_year_delta_amount_cents"],
            "overview_yoy_delta",
        ),
        "year_over_year_delta_count": int(payload["year_over_year_delta_count"]),
        "trend": _trend_view(payload["trend"], currency_code=currency_code),
        "merchant_ranking": _merchant_ranking_view(
            payload["merchant_ranking"],
            currency_code=currency_code,
        ),
        "category_comparison": _category_comparison_view(
            payload["category_comparison"],
            currency_code=currency_code,
        ),
    }


def _monthly_report_view_model(
    report: MonthlyReport,
    *,
    currency_code: str,
) -> dict:
    return {
        "year_month": report.year_month,
        "total_amount_yuan": _amount_yuan(report.total_cents, currency_code),
        "expense_count": report.expense_count,
        "delta_vs_previous_yuan": _amount_yuan(
            report.delta_vs_previous_cents,
            currency_code,
        ),
        "delta_pct": report.delta_pct,
        "top_categories": [
            {
                "category": row.category,
                "amount_cents": row.amount_cents,
                "amount_yuan": _amount_yuan(row.amount_cents, currency_code),
                "count": row.count,
            }
            for row in report.top_categories
        ],
    }


def _budget_explanation_view_model(
    item: BudgetExplanation,
    *,
    currency_code: str,
) -> dict:
    return {
        "category": item.category,
        "year_month": item.year_month,
        "actual_yuan": _amount_yuan(item.actual_cents, currency_code),
        "p50_yuan": (
            _amount_yuan(item.p50_cents, currency_code)
            if item.p50_cents is not None
            else None
        ),
        "p75_yuan": (
            _amount_yuan(item.p75_cents, currency_code)
            if item.p75_cents is not None
            else None
        ),
        "delta_vs_p75_yuan": (
            _amount_yuan(item.delta_vs_p75_cents, currency_code)
            if item.delta_vs_p75_cents is not None
            else None
        ),
        "verdict": item.verdict,
        "verdict_label": _budget_verdict_label(item.verdict),
    }


def _budget_verdict_label(value: str) -> str:
    labels = {
        "under": "低于常规",
        "on_track": "节奏正常",
        "over_p75": "高于 P75",
        "no_history": "历史不足",
    }
    return labels.get(value, value)


def _top_expenses_view(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str,
    presentation_currency_code: str,
) -> list[dict[str, str]]:
    """Highest-amount confirmed expenses for the month (former /web/stats panel).

    This was the only content unique to the deleted /web/stats page, so it moves
    here when stats is merged into reports (UI/UX 批 14).
    """
    rows: list[dict[str, str]] = []
    for e in top_expenses_for_month(
        db, tenant_id=tenant_id, month=month, timezone_name=timezone_name
    ):
        rows.append(
            {
                "merchant": e.merchant or "未填写商家",
                # The record's frozen unit wins; presentation authority only
                # covers legacy rows that predate the carrier.
                "amount_yuan": _amount_yuan(
                    e.amount_cents,
                    e.home_currency_code or presentation_currency_code,
                ),
                "category": e.category or "未分类",
                "expense_time": e.expense_time.strftime("%Y-%m-%d") if e.expense_time else "",
            }
        )
    return rows


def _monthly_report_sections(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str,
    currency_code: str,
) -> tuple[dict, list[dict]]:
    """月报摘要 + 预算解释两段的 ctx 视图(从 route 拆出守 80 行债线)。"""
    monthly_report = compose_monthly_report(
        db,
        tenant_id=tenant_id,
        year_month=month,
        timezone_name=timezone_name,
    )
    explanations = [
        compose_budget_explanation(
            db,
            tenant_id=tenant_id,
            category=row.category,
            year_month=month,
            timezone_name=timezone_name,
        )
        for row in monthly_report.top_categories[:5]
    ]
    return (
        _monthly_report_view_model(
            monthly_report,
            currency_code=currency_code,
        ),
        [
            _budget_explanation_view_model(
                item,
                currency_code=currency_code,
            )
            for item in explanations
        ],
    )


def _report_export_query(
    *,
    ledger_id: str,
    month: str,
    granularity: str,
    ranking_metric: str,
    merchant_category: str | None,
) -> str:
    return urlencode(
        {
            "ledger_id": ledger_id,
            "month": month,
            "granularity": granularity,
            "ranking_metric": ranking_metric,
            "merchant_category": (merchant_category or "").strip(),
        }
    )


@router.get("", response_class=HTMLResponse)
def web_reports(
    request: Request,
    month: str | None = None,
    granularity: str | None = None,
    ranking_metric: str | None = None,
    merchant_category: str | None = Query(default=None, max_length=64),
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    home = require_runtime_home_currency_code(db)
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
    ctx.update(
        {
            "report": _view_model(payload, currency_code=home),
            "monthly_report": monthly_report_vm,
            "budget_explanations": budget_explanations,
            "report_export_query": _report_export_query(
                ledger_id=selected_id,
                month=target_month,
                granularity=selected_granularity,
                ranking_metric=selected_metric,
                merchant_category=merchant_category,
            ),
            "month": target_month,
            "granularity_options": [("day", "日"), ("week", "周"), ("month", "月")],
            "ranking_metric_options": [("amount", "金额"), ("count", "笔数")],
            "top_expenses": _top_expenses_view(
                db,
                tenant_id=selected_id,
                month=target_month,
                timezone_name=timezone_name,
                presentation_currency_code=home,
            ),
            "six_month_trend": six_month_trend,
            "six_month_average_amount_yuan": _six_month_average_amount_yuan(
                six_month_trend,
                currency_code=home,
            ),
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
    content = "\ufeff" + export_reports_overview_csv(
        db,
        month=target_month,
        tenant_id=selected_id,
        timezone_name=timezone_name,
        granularity=selected_granularity,
        ranking_metric=selected_metric,
        merchant_category=merchant_category,
    )
    filename = f"ticketbox-web-reports-{target_month}-{selected_granularity}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
