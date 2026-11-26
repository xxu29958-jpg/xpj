"""Shared projection of a confirmed expense and its active offset facts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.models import Expense, ExpenseOffsetFact
from app.schemas import ExpenseFinancialSummary
from app.services.expense_offset_money import gross_original_minor


def expense_financial_summary(
    expense: Expense,
    offsets: list[ExpenseOffsetFact],
) -> ExpenseFinancialSummary:
    gross_original = gross_original_minor(expense)
    gross_home = int(expense.amount_cents or 0)
    reversal = next((offset for offset in offsets if offset.kind == "reversal"), None)
    refunds = [offset for offset in offsets if offset.kind != "reversal"]
    currency_mismatch = any(
        offset.original_currency_code != expense.original_currency_code for offset in refunds
    )
    refunded_original = (
        0 if currency_mismatch else sum(offset.original_amount_minor for offset in refunds)
    )
    remaining_original = 0 if currency_mismatch else max(gross_original - refunded_original, 0)

    if reversal is not None:
        remaining_original = 0
        net_home = 0
        status = "reversed"
    else:
        net_home = gross_home - sum(offset.amount_cents for offset in refunds)
        if not refunds:
            status = "confirmed"
        elif currency_mismatch:
            status = "partially_refunded"
        elif remaining_original == 0:
            status = "fully_refunded"
        else:
            status = "partially_refunded"

    baseline_remaining_home = 0
    if gross_original and reversal is None:
        baseline_remaining_home = int(
            (Decimal(gross_home) * Decimal(remaining_original) / Decimal(gross_original)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return ExpenseFinancialSummary(
        gross_original_minor=gross_original,
        gross_home_amount_cents=gross_home,
        active_refunded_original_minor=refunded_original,
        remaining_refundable_original_minor=remaining_original,
        lineage_home_net_cents=net_home,
        fx_difference_cents=0 if currency_mismatch else net_home - baseline_remaining_home,
        status=status,
    )


__all__ = ["expense_financial_summary"]
