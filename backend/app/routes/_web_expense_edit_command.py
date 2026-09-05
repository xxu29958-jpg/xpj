"""Validate and apply the Web expense edit command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_edit_form import WebExpenseEditForm
from app.routes._web_expense_form import (
    parse_expense_time_local,
    parse_original_amount_minor,
    web_form_error_status,
)
from app.routes._web_session_common import parse_form_row_version_token
from app.schemas import ExpenseUpdateRequest
from app.services.currency_common import normalize_currency_code
from app.services.data_quality_service import is_uncategorized_expense_category
from app.services.expense_edit_command_service import edit_expense_submission
from app.services.expense_service import get_expense
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
    conflict: bool = False


class _ExpenseCurrencySnapshot(Protocol):
    original_currency_code: str | None
    original_amount_minor: int | None
    home_currency_code: str | None
    merchant: str | None
    category: str | None
    note: str | None
    tags: str | None
    expense_time: object | None

_SCHEMA_ERROR_MESSAGES = {
    "merchant": "商家最多 255 个字符。",
    "category": "分类最多 64 个字符。",
    "expected_row_version": "页面已过期，请刷新后重新保存。",
    "manual_exchange_rate": "汇率格式不正确。",
}
_DEFAULT_SCHEMA_ERROR_MESSAGE = "提交参数不正确，请检查后重试。"


def _submitted_form_values(
    *,
    expected_row_version: str,
    idempotency_key: str,
    amount_yuan: str | None,
    original_currency: str,
    manual_exchange_rate: str | None,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time: str | None,
) -> dict[str, str]:
    values: dict[str, str | None] = {
        "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
        "amount_yuan": amount_yuan,
        "original_currency": original_currency,
        "manual_exchange_rate": manual_exchange_rate,
        "merchant": merchant,
        "category": category,
        "note": note,
        "tags": tags,
        "expense_time": expense_time,
    }
    # Browser controls submit blank text as an empty string. FastAPI normalises
    # blanks for optional fields to None, so restore the raw-form shape here:
    # it is both the failed-form value source and the stable idempotency intent.
    return {key: value if value is not None else "" for key, value in values.items()}


def _edit_intent_body(form_values: dict[str, str]) -> dict[str, object]:
    metadata = {"expected_row_version", "idempotency_key"}
    return {key: value for key, value in form_values.items() if key not in metadata}


def _validated_currency_snapshot(
    expense: _ExpenseCurrencySnapshot,
    *,
    original_currency: str,
    form_values: dict[str, str],
    allow_currency_change: bool,
) -> tuple[str | None, WebExpenseSaveOutcome | None]:
    frozen_currency = (expense.original_currency_code or expense.home_currency_code).strip().upper()
    submitted_currency = (original_currency or "").strip().upper() or frozen_currency
    try:
        submitted_currency = normalize_currency_code(submitted_currency)
    except AppError as exc:
        return None, _failure(
            exc.message,
            form_values=form_values,
            field_errors={"original_currency": exc.message},
        )
    if not allow_currency_change and submitted_currency != frozen_currency:
        message = (
            "账单币种已在其它端改变；金额草稿仍按原币种保留，"
            "不能直接重试。请先载入账本现值，再按当前币种重新填写。"
        )
        return None, _failure(
            message,
            form_values=form_values,
            field_errors={"original_currency": message},
            status_code=409,
            conflict=True,
        )
    return submitted_currency, None


def _category_validation_error(
    category: str | None,
    *,
    form_values: dict[str, str],
) -> WebExpenseSaveOutcome | None:
    submitted = (category or "").strip()
    if not submitted or not is_uncategorized_expense_category(submitted):
        return None
    message = "请选择具体分类，不能使用“未分类”。"
    return _failure(
        message,
        form_values=form_values,
        field_errors={"category": message},
    )


def _schema_error(
    exc: ValidationError,
    *,
    form_values: dict[str, str],
) -> tuple[str, dict[str, str]]:
    first = exc.errors(include_url=False)[0]
    field = str(first.get("loc", ("form",))[-1])
    tag_message = (
        "标签最多 500 个字符。"
        if len(form_values.get("tags", "")) > 500
        else "单个标签最多 64 个字符。"
    )
    messages = {**_SCHEMA_ERROR_MESSAGES, "tags": tag_message}
    message = messages.get(field, _DEFAULT_SCHEMA_ERROR_MESSAGE)
    return message, {field: message}


def _failure(
    message: str,
    *,
    form_values: dict[str, str] | None,
    field_errors: dict[str, str] | None = None,
    status_code: int = 422,
    conflict: bool = False,
) -> WebExpenseSaveOutcome:
    return WebExpenseSaveOutcome(
        error=message,
        error_status=status_code,
        form_values=form_values,
        field_errors=field_errors or {},
        conflict=conflict,
    )


def _changed_update_fields(
    expense: _ExpenseCurrencySnapshot,
    *,
    selected_currency: str,
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
    if expense_time_value is not None and ensure_utc(expense_time_value) != ensure_utc(expense.expense_time):
        updates["expense_time"] = expense_time_value
    current_currency = (expense.original_currency_code or expense.home_currency_code).strip().upper()
    if selected_currency != current_currency or (
        original_amount_minor is not None and original_amount_minor != expense.original_amount_minor
    ):
        updates["original_currency_code"] = selected_currency
        updates["original_amount_minor"] = original_amount_minor
    return updates


def _validated_amount_time_and_token(
    expense: _ExpenseCurrencySnapshot,
    *,
    selected_currency: str,
    amount_yuan: str | None,
    expense_time: str | None,
    expected_row_version: str,
    form_values: dict[str, str],
) -> tuple[int | None, datetime | None, int | None, WebExpenseSaveOutcome | None]:
    original_amount_minor = None
    amount_error = None
    if amount_yuan is not None:
        original_amount_minor, amount_error = parse_original_amount_minor(
            amount_yuan, currency_code=selected_currency
        )
    if amount_error is not None:
        return None, None, None, _failure(
            amount_error,
            form_values=form_values,
            field_errors={"amount_yuan": amount_error},
        )
    current_currency = (
        expense.original_currency_code or expense.home_currency_code
    ).strip().upper()
    if selected_currency != current_currency and original_amount_minor is None:
        message = "更改币种时请同时填写原币金额。"
        return None, None, None, _failure(
            message,
            form_values=form_values,
            field_errors={"amount_yuan": message},
        )
    expense_time_value, time_error = parse_expense_time_local(expense_time)
    if time_error is not None:
        return None, None, None, _failure(
            time_error,
            form_values=form_values,
            field_errors={"expense_time": time_error},
        )
    parsed_row_version = parse_form_row_version_token(expected_row_version)
    if parsed_row_version is None:
        message = "页面已过期，请刷新后重新保存。"
        return None, None, None, _failure(
            message,
            form_values=form_values,
            field_errors={"expected_row_version": message},
        )
    return original_amount_minor, expense_time_value, parsed_row_version, None


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
    manual_exchange_rate: str | None,
    form_values: dict[str, str],
    allow_currency_change: bool,
) -> tuple[ExpenseUpdateRequest | None, WebExpenseSaveOutcome | None]:
    selected_currency, currency_error = _validated_currency_snapshot(
        expense,
        original_currency=original_currency,
        form_values=form_values,
        allow_currency_change=allow_currency_change,
    )
    if selected_currency is None:
        return None, currency_error

    category_error = _category_validation_error(category, form_values=form_values)
    if category_error is not None:
        return None, category_error

    original_amount_minor, expense_time_value, parsed_row_version, value_error = (
        _validated_amount_time_and_token(
            expense,
            selected_currency=selected_currency,
            amount_yuan=amount_yuan,
            expense_time=expense_time,
            expected_row_version=expected_row_version,
            form_values=form_values,
        )
    )
    if value_error is not None or parsed_row_version is None:
        return None, value_error
    payload_args: dict[str, object] = {"expected_row_version": parsed_row_version}
    payload_args.update(
        _changed_update_fields(
            expense,
            selected_currency=selected_currency,
            original_amount_minor=original_amount_minor,
            merchant=merchant,
            category=category,
            note=note,
            tags=tags,
            expense_time_value=expense_time_value,
        )
    )
    if manual_exchange_rate is not None and manual_exchange_rate.strip():
        # This is an explicit one-expense snapshot input. Keep it in the same
        # PATCH as amount/date edits so the server derives home amount,
        # provenance and effective rate date atomically.
        payload_args["manual_exchange_rate"] = manual_exchange_rate.strip()
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
    form: WebExpenseEditForm,
) -> WebExpenseSaveOutcome:
    """Validate browser input against the persisted currency snapshot, then save."""

    payload, prepared = prepare_web_expense_form(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_ledger_id,
        expected_row_version=form.expected_row_version,
        idempotency_key=form.idempotency_key,
        amount_yuan=form.amount_yuan,
        original_currency=form.original_currency,
        manual_exchange_rate=form.manual_exchange_rate,
        merchant=form.merchant,
        category=form.category,
        note=form.note,
        tags=form.tags,
        expense_time=form.expense_time,
    )
    if payload is None:
        return prepared

    try:
        updated = edit_expense_submission(
            db,
            expense_id=expense_id,
            tenant_id=selected_ledger_id,
            expected_row_version=payload.expected_row_version,
            request_expected_row_version=payload.expected_row_version,
            idempotency_key=form.idempotency_key or None,
            intent_body=_edit_intent_body(prepared.form_values or {}),
            update_payload=payload,
        )
    except AppError as exc:
        db.rollback()
        conflict = exc.error == "state_conflict"
        message = "账单已在其它端被修改，请刷新后重试。" if conflict else exc.message
        form_values = prepared.form_values
        if form_values and exc.error in {
            "idempotency_key_required",
            "idempotency_key_reused",
        }:
            form_values = {**form_values, "idempotency_key": ""}
        field_errors = None
        if exc.error in {
            "exchange_rate_invalid",
            "exchange_rate_out_of_range",
            "exchange_rate_base_currency",
        }:
            field_errors = {"manual_exchange_rate": exc.message}
        return _failure(
            message,
            form_values=form_values,
            field_errors=field_errors,
            status_code=web_form_error_status(exc),
            conflict=conflict,
        )
    return WebExpenseSaveOutcome(
        form_values=prepared.form_values,
        field_errors={},
        row_version=updated.row_version,
    )


def prepare_web_expense_form(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    expected_row_version: str,
    idempotency_key: str = "",
    amount_yuan: str | None,
    original_currency: str,
    merchant: str | None,
    category: str | None,
    note: str | None,
    tags: str | None,
    expense_time: str | None,
    allow_currency_change: bool = False,
    manual_exchange_rate: str | None = None,
) -> tuple[ExpenseUpdateRequest | None, WebExpenseSaveOutcome]:
    """Parse one browser snapshot without owning its write transaction."""

    form_values = _submitted_form_values(
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        manual_exchange_rate=manual_exchange_rate,
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
        return None, _failure(exc.message, form_values=form_values, status_code=web_form_error_status(exc))
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
        manual_exchange_rate=manual_exchange_rate,
        form_values=form_values,
        allow_currency_change=allow_currency_change,
    )
    if validation_error is not None or payload is None:
        return None, validation_error or _failure("提交参数不正确，请检查后重试。", form_values=form_values)
    return payload, WebExpenseSaveOutcome(form_values=form_values, field_errors={})
