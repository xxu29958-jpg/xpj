"""Prepare and execute the Web pending-expense confirm command."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_SOURCE_MANUAL, FX_STATUS_READY
from app.routes._web_expense_edit_command import prepare_web_expense_form
from app.routes._web_expense_edit_form import WebExpenseEditForm
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_session_common import parse_form_row_version_token
from app.schemas import ExpenseUpdateRequest
from app.services.expense_review_command_service import confirm_expense_submission
from app.services.expense_service import get_expense

_ROTATE_IDEMPOTENCY_ERRORS = frozenset(
    {"idempotency_key_required", "idempotency_key_reused"}
)
_MANUAL_FX_PREVIEW_FIELDS = frozenset(
    {"original_currency_code", "original_amount_minor", "expense_time"}
)
_MANUAL_FX_PREVIEW_MESSAGE = (
    "手工汇率、原币金额或消费时间有变化。请先保存草稿，"
    "核对折算后的本位币金额，再确认入账。"
)


@dataclass(frozen=True)
class WebExpenseConfirmPreparation:
    expected_row_version: int | None = None
    update_payload: ExpenseUpdateRequest | None = None
    form_values: dict[str, str] | None = None
    field_errors: dict[str, str] | None = None
    error: str | None = None
    error_status: int = 422


@dataclass(frozen=True)
class WebExpenseConfirmOutcome:
    error: str | None = None
    error_status: int = 422
    form_values: dict[str, str] | None = None
    field_errors: dict[str, str] | None = None
    conflict: bool = False


def _manual_fx_submission_needs_preview(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    update_payload: ExpenseUpdateRequest,
    form_values: dict[str, str] | None,
) -> bool:
    raw_rate = (form_values or {}).get("manual_exchange_rate", "").strip()
    if not raw_rate:
        return False
    expense = get_expense(db, expense_id, selected_ledger_id)
    if (
        expense.fx_status != FX_STATUS_READY
        or expense.exchange_rate_source != FX_SOURCE_MANUAL
        or update_payload.manual_exchange_rate != expense.exchange_rate_to_cny
    ):
        return True
    return bool(update_payload.model_fields_set & _MANUAL_FX_PREVIEW_FIELDS)


def prepare_web_expense_confirmation(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    form: WebExpenseEditForm,
) -> WebExpenseConfirmPreparation:
    """Prepare one confirm, stopping an unreviewed manual-FX snapshot."""

    if not form.save_before_confirm:
        parsed = parse_form_row_version_token(form.expected_row_version)
        if parsed is None:
            return WebExpenseConfirmPreparation(
                error="页面已过期，请刷新后重新确认。"
            )
        return WebExpenseConfirmPreparation(expected_row_version=parsed)

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
        return WebExpenseConfirmPreparation(
            error=prepared.error or "提交参数不正确，请检查后重试。",
            error_status=prepared.error_status,
            form_values=prepared.form_values,
            field_errors=prepared.field_errors,
        )
    if _manual_fx_submission_needs_preview(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_ledger_id,
        update_payload=payload,
        form_values=prepared.form_values,
    ):
        return WebExpenseConfirmPreparation(
            error=_MANUAL_FX_PREVIEW_MESSAGE,
            form_values=prepared.form_values,
            field_errors=prepared.field_errors,
        )
    return WebExpenseConfirmPreparation(
        expected_row_version=payload.expected_row_version,
        update_payload=payload,
        form_values=prepared.form_values,
        field_errors=prepared.field_errors,
    )


def _confirmation_intent_body(
    form_values: dict[str, str] | None,
) -> dict[str, object]:
    if form_values is None:
        return {}
    metadata = {"expected_row_version", "idempotency_key"}
    return {
        "save_before_confirm": True,
        **{key: value for key, value in form_values.items() if key not in metadata},
    }


def confirm_web_expense(
    db: Session,
    *,
    expense_id: int,
    selected_ledger_id: str,
    form: WebExpenseEditForm,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
) -> WebExpenseConfirmOutcome:
    prepared = prepare_web_expense_confirmation(
        db,
        expense_id=expense_id,
        selected_ledger_id=selected_ledger_id,
        form=form,
    )
    if prepared.error is not None or prepared.expected_row_version is None:
        return WebExpenseConfirmOutcome(
            error=prepared.error or "页面已过期，请刷新后重新确认。",
            error_status=prepared.error_status,
            form_values=prepared.form_values,
            field_errors=prepared.field_errors,
        )
    try:
        confirm_expense_submission(
            db,
            expense_id=expense_id,
            tenant_id=selected_ledger_id,
            expected_row_version=prepared.expected_row_version,
            request_expected_row_version=prepared.expected_row_version,
            idempotency_key=form.idempotency_key or None,
            intent_body=_confirmation_intent_body(prepared.form_values),
            update_payload=prepared.update_payload,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )
    except AppError as exc:
        form_values = prepared.form_values
        if form_values and exc.error in _ROTATE_IDEMPOTENCY_ERRORS:
            form_values = {**form_values, "idempotency_key": ""}
        return WebExpenseConfirmOutcome(
            error=(
                "账单已在其它端被修改，请刷新后重新确认。"
                if exc.error == "state_conflict"
                else exc.message
            ),
            error_status=web_form_error_status(exc),
            form_values=form_values,
            field_errors=prepared.field_errors,
            conflict=exc.error == "state_conflict",
        )
    return WebExpenseConfirmOutcome()
