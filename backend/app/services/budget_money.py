"""Checked money calculations shared by the budget service."""

from app.models import Budget
from app.money_contract import MoneySign, ensure_money_minor, projection_sum_to_int
from app.schemas import BudgetMonthlyUpdateRequest


def budget_amount_breakdown(
    budget: Budget | None,
    *,
    fixed_amount_cents: int | None,
    spent_amount_cents: int | None,
) -> tuple[int, int, int, int | None, int | None, int | None]:
    total = projection_sum_to_int(
        budget.total_amount_cents if budget else 0,
        label="budget.total",
    )
    rollover = projection_sum_to_int(
        budget.rollover_amount_cents if budget else 0,
        label="budget.rollover",
    )
    non_monthly = projection_sum_to_int(
        budget.non_monthly_amount_cents if budget else 0,
        label="budget.non_monthly",
    )
    available = projection_sum_to_int(total + rollover, label="budget.available")
    flex_delta = None if fixed_amount_cents is None else projection_sum_to_int(
        available - fixed_amount_cents - non_monthly,
        label="budget.flex",
    )
    flex = None if flex_delta is None else max(flex_delta, 0)
    remaining = None if spent_amount_cents is None else (
        projection_sum_to_int(
            available - spent_amount_cents,
            label="budget.remaining",
        )
        if budget is not None
        else 0
    )
    overspent = None if remaining is None else max(-remaining, 0)
    return total, rollover, non_monthly, flex, remaining, overspent


def validated_monthly_budget_amounts(
    payload: BudgetMonthlyUpdateRequest,
) -> tuple[int, int, int]:
    total = ensure_money_minor(
        payload.total_amount_cents,
        sign=MoneySign.NONNEGATIVE,
        label="budget.total_amount_cents",
    )
    non_monthly = ensure_money_minor(
        payload.non_monthly_amount_cents,
        sign=MoneySign.NONNEGATIVE,
        label="budget.non_monthly_amount_cents",
    )
    rollover = ensure_money_minor(
        payload.rollover_amount_cents,
        sign=MoneySign.SIGNED,
        label="budget.rollover_amount_cents",
    )
    return total, non_monthly, rollover


__all__ = ["budget_amount_breakdown", "validated_monthly_budget_amounts"]
