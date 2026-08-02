"""Local /web budget dashboard page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import projection_sum_to_int, round_minor_ratio_half_up
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas import BudgetCategoryRequest, BudgetMonthlyResponse, BudgetMonthlyUpdateRequest
from app.services.budget_service import get_monthly_budget, upsert_monthly_budget
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import major_amount_to_minor
from app.services.spending_contract_service import (
    current_accounting_month,
    default_accounting_timezone_name,
)
from app.services.time_service import local_month_bounds_utc

router = APIRouter(prefix="/web/budgets", tags=["web"])


def _parse_amount_yuan(
    raw: str,
    *,
    currency_code: str,
    label: str,
    allow_negative: bool = False,
    required: bool = False,
) -> int:
    text = (raw or "").strip()
    if not text:
        if required:
            raise AppError("invalid_request", f"请填写{label}。", status_code=422)
        return 0
    try:
        result = major_amount_to_minor(
            text,
            currency_code,
            # Parse the canonical signed value first so the form can preserve
            # its specific nonnegative-field error instead of collapsing a
            # valid negative amount into the generic malformed/overflow copy.
            allow_negative=True,
        )
    except AppError as exc:
        raise AppError(
            "invalid_request",
            f"{label}不是合法金额或超出当前版本可支持范围。",
            status_code=422,
        ) from exc
    assert result is not None
    if result < 0 and not allow_negative:
        raise AppError(
            "invalid_request",
            f"{label}不能为负数。",
            status_code=422,
        )
    return result


def _split_categories(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def _budget_timezone_name() -> str:
    return default_accounting_timezone_name()


def _safe_month(value: str, timezone_name: str | None = None) -> str:
    month = (value or "").strip()
    resolved_timezone = timezone_name or _budget_timezone_name()
    if not month or local_month_bounds_utc(month, resolved_timezone) is None:
        return current_accounting_month(resolved_timezone)
    return month


def _parse_category_budgets(
    categories: list[str],
    amounts: list[str],
    *,
    currency_code: str,
) -> list[BudgetCategoryRequest]:
    max_len = max(len(categories), len(amounts))
    rows: list[BudgetCategoryRequest] = []
    for index in range(max_len):
        category = (categories[index] if index < len(categories) else "").strip()
        amount_text = (amounts[index] if index < len(amounts) else "").strip()
        if not category and not amount_text:
            continue
        if not category or not amount_text:
            raise AppError("invalid_request", "分类预算需要同时填写分类和金额。", status_code=422)
        rows.append(
            BudgetCategoryRequest(
                category=category,
                amount_cents=_parse_amount_yuan(
                    amount_text,
                    currency_code=currency_code,
                    label="分类预算金额",
                ),
            )
        )
    return rows


def _category_form_rows(
    budget: BudgetMonthlyResponse,
    *,
    currency_code: str,
) -> list[dict[str, str]]:
    rows = [
        {
            "category": item.category,
            "amount_yuan": _amount_yuan(item.amount_cents, currency_code),
            "spent_yuan": _amount_yuan(item.spent_amount_cents, currency_code),
            "remaining_yuan": _amount_yuan(item.remaining_amount_cents, currency_code),
            "overspent_yuan": _amount_yuan(item.overspent_amount_cents, currency_code),
            "has_overspend": item.overspent_amount_cents > 0,
            "is_blank": False,
        }
        for item in budget.category_budgets
    ]
    blank_count = max(2, 5 - len(rows))
    rows.extend(
        {
            "category": "",
            "amount_yuan": "",
            "spent_yuan": "",
            "remaining_yuan": "",
            "overspent_yuan": "",
            "has_overspend": False,
            "is_blank": True,
        }
        for _ in range(blank_count)
    )
    return rows


def _budget_view(budget: BudgetMonthlyResponse, *, currency_code: str) -> dict:
    total = max(
        projection_sum_to_int(
            budget.total_amount_cents,
            label="web_budget.total",
        ),
        0,
    )
    spent = max(
        projection_sum_to_int(
            budget.spent_amount_cents,
            label="web_budget.spent",
        ),
        0,
    )
    percent = (
        min(
            100,
            round_minor_ratio_half_up(
                spent * 100,
                total,
                label="web_budget.percent",
            ),
        )
        if total
        else 0
    )
    return {
        "ledger_id": budget.ledger_id,
        "month": budget.month,
        "configured": budget.configured,
        "total_yuan": _amount_yuan(budget.total_amount_cents, currency_code),
        "rollover_yuan": _amount_yuan(budget.rollover_amount_cents, currency_code),
        "fixed_yuan": _amount_yuan(budget.fixed_amount_cents, currency_code),
        "non_monthly_yuan": _amount_yuan(budget.non_monthly_amount_cents, currency_code),
        "flex_yuan": _amount_yuan(budget.flex_budget_cents, currency_code),
        "spent_yuan": _amount_yuan(budget.spent_amount_cents, currency_code),
        "excluded_yuan": _amount_yuan(budget.excluded_amount_cents, currency_code),
        "remaining_yuan": _amount_yuan(budget.remaining_amount_cents, currency_code),
        "overspent_yuan": _amount_yuan(budget.overspent_amount_cents, currency_code),
        "excluded_categories_text": ", ".join(budget.excluded_categories),
        "excluded_breakdown": [
            {
                "category": item.category,
                "amount_yuan": _amount_yuan(item.amount_cents, currency_code),
                "count": item.count,
            }
            for item in budget.excluded_breakdown
        ],
        "category_rows": _category_form_rows(
            budget,
            currency_code=currency_code,
        ),
        "spent_percent": percent,
        "is_over_budget": budget.remaining_amount_cents < 0,
    }


def _render_budgets(
    *,
    request: Request,
    db: Session,
    selected_id: str,
    options,
    month: str,
    message: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    timezone_name = _budget_timezone_name()
    budget = get_monthly_budget(
        db,
        tenant_id=selected_id,
        month=month,
        timezone_name=timezone_name,
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        show_month_picker=True,
        selected_month=month,
    )
    ctx["month"] = month
    ctx["budget"] = _budget_view(
        budget,
        currency_code=ctx["home_currency_code"],
    )
    ctx["message"] = message
    ctx["error"] = error
    return templates.TemplateResponse(request=request, name="budgets.html", context=ctx)


@router.get("", response_class=HTMLResponse)
def web_budgets(
    request: Request,
    ledger_id: str | None = None,
    month: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    target_month = _safe_month(month or current_accounting_month(_budget_timezone_name()))
    return _render_budgets(
        request=request,
        db=db,
        selected_id=selected_id,
        options=options,
        month=target_month,
        message=msg,
    )


@router.post("/save", response_class=HTMLResponse)
def web_budgets_save(
    request: Request,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    total_amount_yuan: str = Form(default=""),
    rollover_amount_yuan: str = Form(default=""),
    non_monthly_amount_yuan: str = Form(default=""),
    excluded_categories: str = Form(default=""),
    category_budget_category: list[str] = Form(default=[]),
    category_budget_amount_yuan: list[str] = Form(default=[]),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    timezone_name = _budget_timezone_name()
    target_month = (month or "").strip() or current_accounting_month(timezone_name)
    try:
        presentation_currency = require_runtime_home_currency_code(db)
        payload = BudgetMonthlyUpdateRequest(
            total_amount_cents=_parse_amount_yuan(
                total_amount_yuan,
                currency_code=presentation_currency,
                label="月度总预算",
                required=True,
            ),
            rollover_amount_cents=_parse_amount_yuan(
                rollover_amount_yuan,
                currency_code=presentation_currency,
                label="结转金额",
                allow_negative=True,
            ),
            non_monthly_amount_cents=_parse_amount_yuan(
                non_monthly_amount_yuan,
                currency_code=presentation_currency,
                label="非月度预留",
            ),
            excluded_categories=_split_categories(excluded_categories),
            category_budgets=_parse_category_budgets(
                category_budget_category,
                category_budget_amount_yuan,
                currency_code=presentation_currency,
            ),
        )
        upsert_monthly_budget(
            db,
            tenant_id=selected_id,
            month=target_month,
            payload=payload,
            timezone_name=timezone_name,
        )
    except AppError as exc:
        return _render_budgets(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            month=_safe_month(target_month, timezone_name),
            error=exc.message,
        )
    return _web_redirect("/web/budgets", selected_id, month=target_month, msg="预算已保存。")
