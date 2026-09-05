"""Typed binding for the expense edit form shared by save and confirm."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Form

from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    expense_return_form_context,
)


@dataclass(frozen=True)
class WebExpenseEditForm:
    ledger_id: str
    expected_row_version: str
    idempotency_key: str
    save_before_confirm: bool
    amount_yuan: str | None
    original_currency: str
    manual_exchange_rate: str
    merchant: str | None
    category: str
    note: str
    tags: str
    expense_time: str | None
    fragment: int
    return_context: ExpenseReturnContext


def web_expense_edit_form(
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    save_before_confirm: int = Form(default=0),
    amount_yuan: str | None = Form(default=None),
    original_currency: str = Form(default=""),
    manual_exchange_rate: str = Form(default=""),
    merchant: str | None = Form(default=None),
    category: str = Form(default=""),
    note: str = Form(default=""),
    tags: str = Form(default=""),
    expense_time: str | None = Form(default=None),
    fragment: int = Form(default=0),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
) -> WebExpenseEditForm:
    """Bind one raw browser intent without giving the HTTP handler ownership."""

    return WebExpenseEditForm(
        ledger_id=ledger_id,
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
        save_before_confirm=save_before_confirm == 1,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        manual_exchange_rate=manual_exchange_rate,
        merchant=merchant,
        category=category,
        note=note,
        tags=tags,
        expense_time=expense_time,
        fragment=fragment,
        return_context=return_context,
    )
