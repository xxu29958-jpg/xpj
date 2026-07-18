"""Backend-owned Desktop inbox mutation workflow.

The Manager only forwards an authenticated local intent. Business lookup,
optimistic concurrency, idempotency, and the final transaction all remain in
this service layer.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense
from app.schemas._desktop_product import (
    DesktopInboxCommandRequest,
    DesktopInboxCommandResponse,
)
from app.schemas._expense import ExpenseUpdateRequest
from app.services.cleanup_service import cleanup_after_confirm
from app.services.exchange_rate_service import calculate_cny_cents
from app.services.expense_service import confirm_expense, reject_expense, update_expense
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.permission_service import require_write_expense
from app.services.session_credential_lock import (
    lock_and_revalidate_desktop_session_principal,
)
from app.tenants import AuthContext

_EDITABLE_FIELDS = frozenset({"original_amount_minor", "merchant", "category"})
_MESSAGES = {
    "save": "收件内容已保存。",
    "confirm": "收件已确认并进入流水。",
    "ignore": "收件已忽略。",
}


def _find_expense(db: Session, *, ledger_id: str, public_id: str) -> Expense:
    expense = db.scalar(
        select(Expense)
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.public_id == public_id)
        .limit(1)
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense


def _response(
    expense: Expense,
    *,
    action: str,
) -> DesktopInboxCommandResponse:
    return DesktopInboxCommandResponse(
        action=action,
        message=_MESSAGES[action],
        expense_status=expense.status,
        row_version=expense.row_version,
    )


def _claim_command(
    db: Session,
    *,
    auth: AuthContext,
    public_id: str,
    payload: DesktopInboxCommandRequest,
    idempotency_key: str | None,
) -> ApiIdempotencyKey | None:
    request_body = payload.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"expected_row_version"},
    )
    request_body["_principal"] = {
        "account_id": auth.account_id,
        "device_id": auth.device_id,
        "scope": auth.scope,
    }
    return claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.ledger_id,
        operation="desktop_inbox_command",
        target_id=public_id,
        body=request_body,
        expected_row_version=payload.expected_row_version,
    )


def _apply_edit(
    db: Session,
    *,
    expense: Expense,
    ledger_id: str,
    payload: DesktopInboxCommandRequest,
) -> Expense:
    editable = _EDITABLE_FIELDS & payload.model_fields_set
    if not editable:
        return expense
    money_was_edited = "original_amount_minor" in editable
    update_data = {
        key: getattr(payload, key)
        for key in editable
        if key != "original_amount_minor"
    }
    if money_was_edited:
        _require_frozen_currency_snapshot(expense=expense, payload=payload)
        original_amount_minor = payload.original_amount_minor
        update_data.update(
            amount_cents=calculate_cny_cents(
                original_currency_code=expense.original_currency_code,
                original_amount_minor=original_amount_minor,
                exchange_rate_to_cny=expense.exchange_rate_to_cny,
            ),
            original_currency_code=expense.original_currency_code,
            original_amount_minor=original_amount_minor,
        )
    return update_expense(
        db,
        expense.id,
        ledger_id,
        ExpenseUpdateRequest(
            expected_row_version=payload.expected_row_version,
            **update_data,
        ),
        commit=False,
        preserve_currency_snapshot=money_was_edited,
    )


def _require_frozen_currency_snapshot(
    *,
    expense: Expense,
    payload: DesktopInboxCommandRequest,
) -> None:
    matches = (
        payload.original_currency_code == expense.original_currency_code
        and payload.home_currency_code == expense.home_currency_code
        and payload.home_amount_minor == expense.amount_cents
        and payload.exchange_rate_to_home == expense.exchange_rate_to_cny
        and payload.exchange_rate_date == expense.exchange_rate_date
        and payload.exchange_rate_source == expense.exchange_rate_source
        and payload.fx_status == expense.fx_status
    )
    if not matches:
        raise AppError("state_conflict", status_code=409)


def _apply_action(
    db: Session,
    *,
    expense: Expense,
    ledger_id: str,
    action: str,
    expected_row_version: int,
) -> Expense:
    if action == "confirm":
        return confirm_expense(
            db,
            expense.id,
            ledger_id,
            expected_row_version=expected_row_version,
            commit=False,
        )
    if action == "ignore":
        return reject_expense(
            db,
            expense.id,
            ledger_id,
            expected_row_version=expected_row_version,
            commit=False,
        )
    return expense


def _commit_command(
    db: Session,
    *,
    claim: ApiIdempotencyKey,
    expense: Expense,
    action: str,
) -> None:
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense",
        resource_id=str(expense.id),
    )
    db.commit()
    db.refresh(expense)
    if action == "confirm" and cleanup_after_confirm(expense):
        db.commit()
        db.refresh(expense)


def execute_desktop_inbox_command(
    db: Session,
    *,
    auth: AuthContext,
    public_id: str,
    payload: DesktopInboxCommandRequest,
    idempotency_key: str | None,
) -> DesktopInboxCommandResponse:
    """Apply one Inbox intent with claim-before-OCC ordering.

    The business mutation and idempotency success marker share one commit.
    Confirmed-image cleanup remains the existing post-confirm maintenance
    commit used by the canonical expense route.
    """

    auth = lock_and_revalidate_desktop_session_principal(db, auth)
    require_write_expense(auth)
    expense = _find_expense(
        db,
        ledger_id=auth.ledger_id,
        public_id=public_id,
    )
    claim = _claim_command(
        db,
        auth=auth,
        public_id=public_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _response(
            _find_expense(db, ledger_id=auth.ledger_id, public_id=public_id),
            action=payload.action,
        )
    has_edit = bool(_EDITABLE_FIELDS & payload.model_fields_set)
    expense = _apply_edit(
        db,
        expense=expense,
        ledger_id=auth.ledger_id,
        payload=payload,
    )
    expense = _apply_action(
        db,
        expense=expense,
        ledger_id=auth.ledger_id,
        action=payload.action,
        expected_row_version=(
            expense.row_version if has_edit else payload.expected_row_version
        ),
    )
    _commit_command(
        db,
        claim=claim,
        expense=expense,
        action=payload.action,
    )
    return _response(expense, action=payload.action)
