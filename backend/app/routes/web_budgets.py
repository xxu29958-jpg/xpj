"""Local /web budget dashboard page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import projection_sum_to_int
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
from app.services.category_service import list_ledger_category_options
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
    removed_indices: set[int] | None = None,
) -> list[BudgetCategoryRequest]:
    max_len = max(len(categories), len(amounts))
    removed = removed_indices or set()
    rows: list[BudgetCategoryRequest] = []
    for index in range(max_len):
        if index in removed:
            continue
        category = (categories[index] if index < len(categories) else "").strip()
        amount_text = (amounts[index] if index < len(amounts) else "").strip()
        if not category and not amount_text:
            continue
        if not category or not amount_text:
            raise AppError("invalid_request", "分类预算需要同时填写分类和金额。", status_code=422)
        try:
            row = BudgetCategoryRequest(
                category=category,
                amount_cents=_parse_amount_yuan(
                    amount_text,
                    currency_code=currency_code,
                    label="分类预算金额",
                ),
            )
        except ValidationError as exc:
            raise AppError(
                "invalid_request",
                "分类名称过长，请缩短后再保存。",
                status_code=422,
            ) from exc
        rows.append(row)
    return rows


def _category_form_rows(
    budget: BudgetMonthlyResponse,
    *,
    currency_code: str,
    draft_categories: list[str] | None = None,
    draft_amounts: list[str] | None = None,
    removed_indices: set[int] | None = None,
) -> list[dict]:
    removed = removed_indices or set()
    saved = list(budget.category_budgets)
    if draft_categories is None and draft_amounts is None:
        pairs = [(item.category, _amount_yuan(item.amount_cents, currency_code)) for item in saved]
    else:
        categories = draft_categories or []
        amounts = draft_amounts or []
        pairs = [
            (
                categories[index] if index < len(categories) else "",
                amounts[index] if index < len(amounts) else "",
            )
            for index in range(max(len(categories), len(amounts)))
        ]
        while len(pairs) > len(saved) and not any(value.strip() for value in pairs[-1]):
            pairs.pop()

    rows: list[dict] = []
    for index, (category, amount_yuan) in enumerate(pairs):
        saved_item = saved[index] if index < len(saved) else None
        rows.append(
            {
                "index": index,
                "category": category,
                "saved_category": saved_item.category if saved_item is not None else "",
                "amount_yuan": amount_yuan,
                "spent_yuan": (
                    _amount_yuan(saved_item.spent_amount_cents, currency_code) if saved_item is not None else ""
                ),
                "remaining_yuan": (
                    _amount_yuan(saved_item.remaining_amount_cents, currency_code) if saved_item is not None else ""
                ),
                "overspent_yuan": (
                    _amount_yuan(saved_item.overspent_amount_cents, currency_code) if saved_item is not None else ""
                ),
                "has_overspend": bool(saved_item is not None and saved_item.overspent_amount_cents > 0),
                "is_configured": saved_item is not None,
                "remove_requested": index in removed,
            }
        )

    first_blank_index = len(rows)
    rows.extend(
        {
            "index": first_blank_index + offset,
            "category": "",
            "saved_category": "",
            "amount_yuan": "",
            "spent_yuan": "",
            "remaining_yuan": "",
            "overspent_yuan": "",
            "has_overspend": False,
            "is_configured": False,
            "remove_requested": False,
        }
        for offset in range(2)
    )
    return rows


def _budget_view(budget: BudgetMonthlyResponse, *, currency_code: str) -> dict:
    spent = max(
        projection_sum_to_int(
            budget.spent_amount_cents,
            label="web_budget.spent",
        ),
        0,
    )
    available = projection_sum_to_int(
        budget.total_amount_cents + budget.rollover_amount_cents,
        label="web_budget.available",
    )
    progress_max = max(available, 0)
    return {
        "ledger_id": budget.ledger_id,
        "month": budget.month,
        "configured": budget.configured,
        "total_yuan": _amount_yuan(budget.total_amount_cents, currency_code),
        "rollover_yuan": _amount_yuan(budget.rollover_amount_cents, currency_code),
        "fixed_yuan": _amount_yuan(budget.fixed_amount_cents, currency_code),
        "non_monthly_yuan": _amount_yuan(budget.non_monthly_amount_cents, currency_code),
        "spent_yuan": _amount_yuan(budget.spent_amount_cents, currency_code),
        "remaining_yuan": _amount_yuan(budget.remaining_amount_cents, currency_code),
        "overspent_yuan": _amount_yuan(budget.overspent_amount_cents, currency_code),
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
        "form_total_yuan": (_amount_yuan(budget.total_amount_cents, currency_code) if budget.configured else ""),
        "form_rollover_yuan": (_amount_yuan(budget.rollover_amount_cents, currency_code) if budget.configured else ""),
        "form_non_monthly_yuan": (
            _amount_yuan(budget.non_monthly_amount_cents, currency_code) if budget.configured else ""
        ),
        "progress_value_cents": min(spent, progress_max),
        "progress_max_cents": progress_max,
        "has_progress_basis": progress_max > 0,
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
    status_code: int = 200,
    draft: dict | None = None,
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
    budget_view = _budget_view(
        budget,
        currency_code=ctx["home_currency_code"],
    )
    if draft is not None:
        budget_view.update(
            form_total_yuan=draft["total_amount_yuan"],
            form_rollover_yuan=draft["rollover_amount_yuan"],
            form_non_monthly_yuan=draft["non_monthly_amount_yuan"],
        )
        budget_view["category_rows"] = _category_form_rows(
            budget,
            currency_code=ctx["home_currency_code"],
            draft_categories=draft["category_budget_category"],
            draft_amounts=draft["category_budget_amount_yuan"],
            removed_indices=draft["category_budget_remove"],
        )
    selected_exclusions = list(draft["excluded_category"]) if draft is not None else list(budget.excluded_categories)
    category_options = list_ledger_category_options(db, tenant_id=selected_id)
    category_options.extend(category for category in selected_exclusions if category not in category_options)
    ctx["budget"] = budget_view
    ctx["excluded_category_options"] = [
        {"name": category, "selected": category in selected_exclusions} for category in category_options
    ]
    ctx["excluded_categories_other"] = draft["excluded_categories"] if draft is not None else ""
    ctx["message"] = message
    ctx["error"] = error
    return templates.TemplateResponse(
        request=request,
        name="budgets.html",
        context=ctx,
        status_code=status_code,
    )


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
    excluded_category: list[str] = Form(default=[]),
    excluded_categories: str = Form(default=""),
    category_budget_category: list[str] = Form(default=[]),
    category_budget_amount_yuan: list[str] = Form(default=[]),
    category_budget_remove: list[int] = Form(default=[]),
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
            excluded_categories=excluded_category + _split_categories(excluded_categories),
            category_budgets=_parse_category_budgets(
                category_budget_category,
                category_budget_amount_yuan,
                currency_code=presentation_currency,
                removed_indices=set(category_budget_remove),
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
            status_code=422,
            draft={
                "total_amount_yuan": total_amount_yuan,
                "rollover_amount_yuan": rollover_amount_yuan,
                "non_monthly_amount_yuan": non_monthly_amount_yuan,
                "excluded_category": excluded_category,
                "excluded_categories": excluded_categories,
                "category_budget_category": category_budget_category,
                "category_budget_amount_yuan": category_budget_amount_yuan,
                "category_budget_remove": set(category_budget_remove),
            },
        )
    return _web_redirect("/web/budgets", selected_id, month=target_month, msg="预算已保存。")
