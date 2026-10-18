"""Actual schedules and fulfilment, projected from retained source and payment facts."""
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AccountMovement,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    InstallmentAgreement,
    InstallmentDraw,
    InstallmentPayment,
    InstallmentPeriod,
    RepaymentVoid,
)
from app.money_contract import round_minor_ratio_half_up
from app.schemas.installment import CreditDrawView, InstallmentPeriodView, InstallmentsView, InstallmentView
from app.services.credit_allocation_service import active_credit_movements, allocation_totals
from app.services.expense_offset_summary import expense_financial_summary


def draw_balances(db, account_id):
    draws = [row for row in active_credit_movements(db, account_id) if row.amount_minor < 0]
    used, _, _ = allocation_totals(db, [row.id for row in draws])
    return {row.id: -row.amount_minor - int(used.get(row.id, 0)) for row in draws}


def paid_by_period(db: Session, period_ids: list[int]) -> dict[int, tuple[int, int]]:
    payments = list(db.scalars(select(InstallmentPayment).where(InstallmentPayment.period_id.in_(period_ids))))
    voided = set(db.scalars(select(RepaymentVoid.repayment_id).where(
        RepaymentVoid.repayment_id.in_([row.repayment_id for row in payments]))))
    retained_fees = _retained_fee_payments(db, payments)
    totals = dict.fromkeys(period_ids, (0, 0))
    for payment in payments:
        principal, fees = totals[payment.period_id]
        totals[payment.period_id] = (principal + (payment.principal_minor if payment.repayment_id not in voided else 0),
            fees + retained_fees.get(payment.id, 0))
    return totals


def _retained_fee_payments(db: Session, payments: list[InstallmentPayment]) -> dict[int, int]:
    funded = dict(db.execute(select(InstallmentPayment.id, Expense)
        .join(Expense, Expense.id == InstallmentPayment.fee_expense_id)
        .join(ExpenseFunding, ExpenseFunding.expense_id == Expense.id)
        .join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id).where(
            InstallmentPayment.id.in_([row.id for row in payments]), Expense.tenant_id == ExpenseFunding.tenant_id,
            AccountMovement.repayment_id == InstallmentPayment.repayment_id)).all())
    expense_ids = {expense.id for expense in funded.values()}
    offsets: dict[int, list[ExpenseOffsetFact]] = defaultdict(list)
    for offset in db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id.in_(expense_ids),
            ExpenseOffsetFact.status == "active")):
        offsets[offset.expense_id].append(offset)
    summaries = {expense.id: expense_financial_summary(expense, offsets[expense.id]) for expense in funded.values()}
    # The prefix includes the same fee's allocations to other periods, so rounding is conserved.
    before = dict(db.execute(select(InstallmentPayment.id, func.coalesce(func.sum(InstallmentPayment.fee_minor).over(
        partition_by=InstallmentPayment.fee_expense_id, order_by=InstallmentPayment.id, rows=(None, -1)), 0))
        .where(InstallmentPayment.fee_expense_id.in_(expense_ids))).all())
    return {payment.id: _retained_fee_slice(payment, summaries[funded[payment.id].id], int(before[payment.id]))
        for payment in payments if payment.fee_expense_id is not None}


def _retained_fee_slice(payment: InstallmentPayment, summary, before: int) -> int:
    if not summary.remaining_refundable_original_minor:
        return 0
    def retained(value: int) -> int:
        return round_minor_ratio_half_up(value * summary.remaining_refundable_original_minor,
            summary.gross_original_minor, label="installment.retained_fee")
    return retained(before + payment.fee_minor) - retained(before)


def active_agreements(db, account_id):
    replaced = select(InstallmentAgreement.supersedes_id).where(InstallmentAgreement.supersedes_id.is_not(None))
    return list(db.scalars(select(InstallmentAgreement).where(InstallmentAgreement.account_id == account_id,
        InstallmentAgreement.id.not_in(replaced))))


def installment_view(db, agreement, *, active, balances=None):
    periods = []
    recorded = list(db.scalars(select(InstallmentPeriod).where(InstallmentPeriod.agreement_id == agreement.id).order_by(InstallmentPeriod.position)))
    paid = paid_by_period(db, [period.id for period in recorded])
    for period in recorded:
        principal, fees = paid[period.id]
        periods.append(InstallmentPeriodView(public_id=period.public_id, position=period.position, due_on=period.due_on,
            principal_minor=period.principal_minor, planned_fee_minor=period.planned_fee_minor,
            paid_principal_minor=principal, paid_fee_minor=fees))
    draws = list(db.scalars(select(AccountMovement).join(InstallmentDraw, InstallmentDraw.movement_id == AccountMovement.id)
        .where(InstallmentDraw.agreement_id == agreement.id)))
    balances = draw_balances(db, agreement.account_id) if balances is None else balances
    remaining = sum(balances.get(draw.id, 0) for draw in draws)
    scheduled = sum(period.principal_minor - period.paid_principal_minor for period in periods)
    return InstallmentView(public_id=agreement.public_id, series_id=agreement.series_id, revision=agreement.revision,
        name=agreement.name, source=agreement.source, agreed_on=agreement.agreed_on, active=active,
        needs_review=active and remaining != scheduled, remaining_principal_minor=remaining, periods=periods,
        draw_public_ids=[draw.public_id for draw in draws])


def installments_view(db, account):
    balances = draw_balances(db, account.id)
    active = {row.id: row for row in active_agreements(db, account.id)}
    assigned = dict(db.execute(select(InstallmentDraw.movement_id, InstallmentAgreement.public_id)
        .join(InstallmentAgreement, InstallmentAgreement.id == InstallmentDraw.agreement_id)
        .where(InstallmentAgreement.id.in_(active))).all())
    draws = [CreditDrawView(public_id=row.public_id, note=row.note, occurred_on=row.occurred_on,
        original_minor=-row.amount_minor, remaining_minor=balances.get(row.id, 0), agreement_public_id=assigned.get(row.id))
        for row in db.scalars(select(AccountMovement).where(AccountMovement.account_id == account.id,
            AccountMovement.amount_minor < 0, AccountMovement.reversal_of_id.is_(None)).order_by(AccountMovement.id))]
    agreements = [installment_view(db, row, active=row.id in active, balances=balances) for row in db.scalars(
        select(InstallmentAgreement).where(InstallmentAgreement.account_id == account.id).order_by(InstallmentAgreement.id.desc()))]
    return InstallmentsView(account_public_id=account.public_id, account_row_version=account.row_version,
        currency_code=account.currency_code, agreements=agreements, draws=draws)
