"""Validate and apply the Web expense edit command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_form import (
    parse_expense_time_local,
    parse_original_amount_minor,
    web_form_error_status,
)
from app.routes._web_session_common import parse_form_row_version_token
from app.schemas import ExpenseUpdateRequest
from app.services.expense_service import get_expense, update_expense
from app.services.tag_service import normalize_tags
from app.services.time_service import ensure_utc


@dataclass(frozen=True)
class WebExpenseSaveOutcome:
    """Result consumed by the HTML or drawer response adapter."""

    error: str | None = None
    error_status: int = 422
    form_values: dict[str, str] | None = None
    field_errors: dict[str, str] | None = None
    row_version: int | None = None


@dataclass(frozen=True)
class WebExpenseConfirmOutcome:
    """Atomic save-and-confirm result consumed by the HTML response adapter."""

    error: str | None = None
    error_status: int = 422
    form_values: dict[str, str] | None = None
    field_errors: dict[str, str] | None = None


class _ExpenseCurrencySnapshot(Protocol):
    original_currency_code: str | None
    original_amount_minor: int | None
    home_currency_code: str | None
    merchant: str | None
    category: str | None
    note: str | None
    tags: str | None
    expense_time: object | None


class _UpdatedExpense(Protocol):
    row_version: int


class _ExpenseUpdateCommand(Protocol):
    def __call__(
        self,
        db: Session,
        expense_id: int,
        tenant_id: str,
        payload: ExpenseUpdateRequest,
        *,
        commit: bool = True,
    ) -> _UpdatedExpense: ...


def _submitted_form_values(
    *,
    amount_yuan: str | None,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time: str | None,
) -> dict[str, str]:
    values = {
        "amount_yuan": amount_yuan,
        "merchant": merchant,
        "category": category,
        "note": note,
        "tags": tags,
        "expense_time": expense_time,
    }
    return {key: value for key, value in values.items() if value is not None}


def _schema_error(
    exc: ValidationError,
    *,
    form_values: dict[str, str],
) -> tuple[str, dict[str, str]]:
    first = exc.errors(include_url=False)[0]
    field = str(first.get("loc", ("form",))[-1])
    if field == "merchant":
        message = "商家最多 255 个字符。"
    elif field == "category":
        message = "分类最多 64 个字符。"
    elif field == "tags":
        message = (
            "标签最多 500 个字符。"
            if len(form_values.get("tags", "")) > 500
            else "单个标签最多 64 个字符。"
        )
    elif field == "expected_row_version":
        message = "页面已过期，请刷新后重新保存。"
    else:
        message = "提交参数不正确，请检查后重试。"
    return message, {field: message}


def _failure(
    message: str,
    *,
    form_values: dict[str, str] | None,
    field_errors: dict[str, str] | None = None,
    status_code: int = 422,
) -> WebExpenseSaveOutcome:
    return WebExpenseSaveOutcome(
        error=message,
        error_status=status_code,
        form_values=form_values,
        field_errors=field_errors or {},
    )


def _changed_update_fields(
    expense: _ExpenseCurrencySnapshot,
    *,
    frozen_currency: str,
    original_amount_minor: int | None,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time_value,
) -> dict[str, object]:
    updates: dict[str, object] = {}
    if merchant is not None:
        merchant_value = merchant.strip() or None
        if merchant_value != (expense.merchant or None):
            updates["merchant"] = merchant_value
    if category is not None:
        category_value = category.strip() or None
        if category_value and category_value != expense.category:
            updates["category"] = category_value
    if note is not None:
        note_value = note.strip() or None
        if (note_value or "") != (expense.note or ""):
            updates["note"] = note_value
    if tags is not None and normalize_tags(tags) != normalize_tags(expense.tags):
        updates["tags"] = tags
    if (
        expense_time_value is not None
        and ensure_utc(expense_time_value) != ensure_utc(expense.expense_time)
    ):
        updates["expense_time"] = expense_time_value
    if (
        original_amount_minor is not None
        and original_amount_minor != expense.original_amount_minor
    ):
        updates["original_currency_code"] = frozen_currency
        updates["original_amount_minor"] = original_amount_minor
    return updates


def _validated_update_request(
    expense: _ExpenseCurrencySnapshot,
    *,
    expected_row_version: str,
    amount_yuan: str | None,
    original_currency: str,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time: str | None,
    form_values: dict[str, str],
) -> tuple[ExpenseUpdateRequest | None, WebExpenseSaveOutcome | None]:
    frozen_currency = (
        expense.original_currency_code or expense.home_currency_code
    ).strip().upper()
    submitted_currency = (original_currency or "").strip().upper()
    if submitted_currency and submitted_currency != frozen_currency:
        message = "账单币种已冻结，不能在编辑金额时更改。"
        return None, _failure(
            message,
            form_values=form_values,
            field_errors={"amount_yuan": message},
        )

    original_amount_minor = None
    amount_error = None
    if amount_yuan is not None:
        original_amount_minor, amount_error = parse_original_amount_minor(
            amount_yuan,
            currency_code=frozen_currency,
        )
    if amount_error is not None:
        return None, _failure(
            amount_error,
            form_values=form_values,
            field_errors={"amount_yuan": amount_error},
        )

    expense_time_value, time_error = parse_expense_time_local(expense_time)
    if time_error is not None:
        return None, _failure(
            time_error,
            form_values=form_values,
            field_errors={"expense_time": time_error},
        )

    parsed_row_version = parse_form_row_version_token(expected_row_version)
    if parsed_row_version is None:
        message = "页面已过期，请刷新后重新保存。"
        return None, _failure(
            message,
            form_values=form_values,
            field_errors={"expected_row_version": message},
        )
    payload_args: dict[str, object] = {"expected_row_version": parsed_row_version}
    payload_args.update(
        _changed_update_fields(
            expense,
            frozen_currency=frozen_currency,
            original_amount_minor=original_amount_minor,
            merchant=merchant,
            category=category,
            note=note,
            tags=tags,
            expense_time_value=expense_time_value,
        )
    )
    try:
        payload = ExpenseUpdateRequest(**payload_args)
    except ValidationError as exc:
        message, field_errors = _schema_error(exc, form_values=form_values)
        return None, _failure(
            message,
            form_values=form_values,
            field_errors=field_errors,
        )
    return payload, None


def apply_web_expense_form(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    expected_row_version: str,
    amount_yuan: str | None,
    original_currency: str,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time: str | None,
    commit: bool = True,
    update_command: _ExpenseUpdateCommand = update_expense,
) -> WebExpenseSaveOutcome:
    """Validate browser input against the persisted currency snapshot, then save."""

    form_values = _submitted_form_values(
        amount_yuan=amount_yuan,
        merchant=merchant,
        category=category,
        note=note,
        tags=tags,
        expense_time=expense_time,
    )
    try:
        expense = get_expense(db, expense_id, selected_ledger_id)
    except AppError as exc:
        db.rollback()
        return _failure(
            exc.message,
            form_values=form_values,
            status_code=web_form_error_status(exc),
        )
    payload, validation_error = _validated_update_request(
        expense,
        expected_row_version=expected_row_version,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        merchant=merchant,
        category=category,
        note=note,
        tags=tags,
        expense_time=expense_time,
        form_values=form_values,
    )
    if validation_error is not None or payload is None:
        return validation_error or _failure(
            "提交参数不正确，请检查后重试。",
            form_values=form_values,
        )

    try:
        updated = update_command(
            db,
            expense_id,
            selected_ledger_id,
            payload,
            commit=commit,
        )
    except AppError as exc:
        db.rollback()
        conflict = exc.error == "state_conflict"
        message = (
            "账单已在其它端被修改，请刷新后重试。" if conflict else exc.message
        )
        return _failure(
            message,
            form_values=None if conflict else form_values,
            status_code=web_form_error_status(exc),
        )
    return WebExpenseSaveOutcome(
        form_values=form_values,
        field_errors={},
        row_version=updated.row_version,
    )
