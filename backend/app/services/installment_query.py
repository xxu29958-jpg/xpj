"""Actual schedules and fulfilment, projected from retained source and payment facts."""
from sqlalchemy import func, select

from app.models import (
    AccountMovement,
    CreditSettlementAllocation,
    Expense,
    ExpenseOffsetFact,
    InstallmentAgreement,
    InstallmentDraw,
    InstallmentPayment,
    InstallmentPeriod,
    RepaymentVoid,
)
from app.schemas.installment import CreditDrawView, InstallmentPeriodView, InstallmentsView, InstallmentView
from app.services.credit_allocation_service import active_allocation_condition, active_credit_movements


def draw_balances(db, account_id):
    draws = [row for row in active_credit_movements(db, account_id) if row.amount_minor < 0]
    used = dict(db.execute(select(CreditSettlementAllocation.draw_movement_id,
        func.sum(CreditSettlementAllocation.amount_minor)).where(active_allocation_condition(),
        CreditSettlementAllocation.draw_movement_id.in_([row.id for row in draws]))
        .group_by(CreditSettlementAllocation.draw_movement_id)).all())
    return {row.id: -row.amount_minor - int(used.get(row.id, 0)) for row in draws}


def period_paid(db, period):
    from app.money_contract import round_minor_ratio_half_up
    from app.services.expense_offset_summary import expense_financial_summary
    payments = list(db.scalars(select(InstallmentPayment).where(InstallmentPayment.period_id == period.id)))
    voided = set(db.scalars(select(RepaymentVoid.repayment_id).where(
        RepaymentVoid.repayment_id.in_([row.repayment_id for row in payments]))))
    principal = sum(row.principal_minor for row in payments if row.repayment_id not in voided)
    fees = 0
    for payment in payments:
        if not payment.fee_expense_id:
            continue
        expense = db.get(Expense, payment.fee_expense_id)
        offsets = list(db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense.id,
            ExpenseOffsetFact.status == "active")))
        summary = expense_financial_summary(expense, offsets)
        if not summary.remaining_refundable_original_minor:
            continue
        # Allocate rounding once in recorded order, including payments in other periods.
        before = int(db.scalar(select(func.coalesce(func.sum(InstallmentPayment.fee_minor), 0)).where(
            InstallmentPayment.fee_expense_id == expense.id, InstallmentPayment.id < payment.id)))
        def retained(value, summary=summary):
            return round_minor_ratio_half_up(value * summary.remaining_refundable_original_minor,
                summary.gross_original_minor, label="installment.retained_fee")
        fees += retained(before + payment.fee_minor) - retained(before)
    return principal, fees


def active_agreements(db, account_id):
    replaced = select(InstallmentAgreement.supersedes_id).where(InstallmentAgreement.supersedes_id.is_not(None))
    return list(db.scalars(select(InstallmentAgreement).where(InstallmentAgreement.account_id == account_id,
        InstallmentAgreement.id.not_in(replaced))))


def installment_view(db, agreement, *, active, balances=None):
    periods = []
    for period in db.scalars(select(InstallmentPeriod).where(InstallmentPeriod.agreement_id == agreement.id).order_by(InstallmentPeriod.position)):
        principal, fees = period_paid(db, period)
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
