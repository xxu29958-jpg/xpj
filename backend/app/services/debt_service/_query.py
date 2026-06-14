"""ADR-0049 Debt read paths: ledger-scoped lookup + derived-fold response."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt
from app.schemas import DebtListResponse, DebtResponse
from app.services.debt_service._fold import compute_paid, compute_remaining, derive_status


def _debt_by_public_id(db: Session, *, tenant_id: str, public_id: str) -> Debt | None:
    return db.scalar(
        ledger_scoped_select(Debt, tenant_id).where(Debt.public_id == public_id).limit(1)
    )


def get_debt(db: Session, *, tenant_id: str, public_id: str) -> Debt:
    debt = _debt_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    return debt


def debt_response(debt: Debt, *, remaining: int, paid: int) -> DebtResponse:
    return DebtResponse(
        public_id=debt.public_id,
        ledger_id=debt.tenant_id,
        direction=debt.direction,
        counterparty_type=debt.counterparty_type,
        counterparty_account_id=debt.counterparty_account_id,
        counterparty_label=debt.counterparty_label,
        principal_amount_cents=int(debt.principal_amount_cents),
        remaining_amount_cents=remaining,
        paid_amount_cents=paid,
        status=derive_status(debt, remaining),
        source_type=debt.source_type,
        source_id=debt.source_id,
        home_currency_code=debt.home_currency_code,
        original_currency_code=debt.original_currency_code,
        original_amount_minor=debt.original_amount_minor,
        exchange_rate_to_cny=debt.exchange_rate_to_cny,
        exchange_rate_date=debt.exchange_rate_date,
        exchange_rate_source=debt.exchange_rate_source,
        created_at=debt.created_at,
        updated_at=debt.updated_at,
        row_version=debt.row_version,
    )


def _debt_response_with_fold(db: Session, debt: Debt) -> DebtResponse:
    remaining = compute_remaining(db, debt)
    paid = compute_paid(db, debt)
    return debt_response(debt, remaining=remaining, paid=paid)


def get_debt_response(db: Session, *, tenant_id: str, public_id: str) -> DebtResponse:
    debt = get_debt(db, tenant_id=tenant_id, public_id=public_id)
    return _debt_response_with_fold(db, debt)


def list_debts(db: Session, *, tenant_id: str) -> DebtListResponse:
    statement = ledger_scoped_select(Debt, tenant_id).order_by(
        Debt.status.asc(),
        Debt.created_at.asc(),
        Debt.id.asc(),
    )
    debts = list(db.scalars(statement))
    return DebtListResponse(items=[_debt_response_with_fold(db, debt) for debt in debts])
