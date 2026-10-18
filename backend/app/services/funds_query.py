"""Account visibility and balances shared by real funds consumers."""
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AccountBalanceObservation,
    AccountMovement,
    CreditFacility,
    Debt,
    ExpenseFunding,
    FinancialAccount,
    Ledger,
    Repayment,
    RepaymentVoid,
)
from app.money_contract import projection_sum_to_int
from app.schemas.funds import BalanceObservationView, CreditTerms, FinancialAccountView, FundsOverview, MovementView
from app.services.credit_allocation_service import unallocated_credit_minor
from app.services.credit_application_query import credit_applications_view
from app.services.credit_fee_query import fee_views
from app.services.funds_money import valuation
from app.services.ledger_calendar_service import current_calendar, current_ledger_date


def account_scope(ledger_id, actor_account_id):
    return or_(FinancialAccount.owner_account_id == actor_account_id,
        and_(FinancialAccount.tenant_id == ledger_id, FinancialAccount.visibility == "ledger"))


def account_query(ledger_id, actor_account_id):
    return select(FinancialAccount).join(Ledger, Ledger.ledger_id == FinancialAccount.tenant_id).where(
        Ledger.archived_at.is_(None), account_scope(ledger_id, actor_account_id))


def get_account(db, *, ledger_id, actor_account_id, public_id, lock=False):
    query = account_query(ledger_id, actor_account_id).where(FinancialAccount.public_id == public_id)
    row = db.scalar(query.with_for_update(of=FinancialAccount).execution_options(populate_existing=True) if lock else query)
    if row is None:
        raise AppError("fund_account_not_found", "这个资金账户不存在或你没有访问权限。", status_code=404)
    return row


def account_balance(db, account, *, cutoff=None):
    query = select(func.coalesce(func.sum(AccountMovement.amount_minor), 0)).where(AccountMovement.account_id == account.id)
    if cutoff is not None:
        query = query.where(AccountMovement.occurred_on <= cutoff)
    return projection_sum_to_int(db.scalar(query), label="funds.recorded_balance")


def account_view(db: Session, row: FinancialAccount, *, actor_account_id: int,
        with_movements: bool = False) -> FinancialAccountView:
    balance = account_balance(db, row)
    debt = db.scalar(select(Debt).join(CreditFacility, CreditFacility.debt_id == Debt.id)
        .where(CreditFacility.account_id == row.id))
    observation = db.scalar(select(AccountBalanceObservation).where(AccountBalanceObservation.account_id == row.id)
        .order_by(AccountBalanceObservation.occurred_on.desc(), AccountBalanceObservation.id.desc()).limit(1))
    movements = []
    if with_movements:
        records = db.execute(select(AccountMovement, ExpenseFunding.expense_id, Repayment.public_id, RepaymentVoid.id)
            .outerjoin(ExpenseFunding, ExpenseFunding.id == AccountMovement.funding_id)
            .outerjoin(Repayment, Repayment.id == AccountMovement.repayment_id)
            .outerjoin(RepaymentVoid, RepaymentVoid.repayment_id == Repayment.id)
            .where(AccountMovement.account_id == row.id).order_by(AccountMovement.occurred_on.desc(), AccountMovement.id.desc()))
        movements = [MovementView(public_id=m.public_id, event_public_id=m.event_public_id, kind=m.kind,
            amount_minor=m.amount_minor, occurred_on=m.occurred_on, note=m.note, expense_id=expense_id,
            repayment_public_id=repayment, can_void_repayment=row.kind == "credit" and m.kind == "repayment"
                and repayment is not None and void_id is None) for m, expense_id, repayment, void_id in records]
    return FinancialAccountView(public_id=row.public_id, name=row.name, ledger_id=row.tenant_id,
        calendar_revision=current_calendar(db, ledger_id=row.tenant_id).revision, kind=row.kind, currency_code=row.currency_code,
        visibility=row.visibility, institution=row.institution, tail=row.tail, row_version=row.row_version,
        archived=row.archived_at is not None, balance_minor=balance if row.balance_known else None,
        recorded_change_minor=balance, opening_date=row.opening_date, opening_source=row.opening_source,
        unallocated_credit_minor=unallocated_credit_minor(db, row.id) if row.kind == "credit" else 0,
        debt_public_id=debt.public_id if debt else None, credit_kind=debt.debt_kind if debt else None,
        observation=BalanceObservationView(observed_minor=observation.observed_minor, recorded_minor=observation.recorded_minor,
            difference_minor=observation.observed_minor - account_balance(db, row, cutoff=observation.occurred_on),
            occurred_on=observation.occurred_on, source=observation.source,
            adjusted=observation.adjustment_movement_id is not None) if observation else None,
        can_edit=row.owner_account_id == actor_account_id, movements=movements,
        fee_obligations=fee_views(db, row.id) if with_movements and row.kind == "credit" else [],
        credit_applications=credit_applications_view(db, row.id) if with_movements and row.kind == "credit" else None,
        credit_terms=CreditTerms(credit_limit_minor=row.credit_limit_minor, available_credit_minor=row.available_credit_minor,
            observed_on=row.credit_observed_on, source=row.credit_source, statement_day=row.statement_day,
            payment_due_day=row.payment_due_day) if row.kind == "credit" else None)


def list_accounts(db, *, ledger_id, actor_account_id):
    return [account_view(db, row, actor_account_id=actor_account_id) for row in db.scalars(
        account_query(ledger_id, actor_account_id).order_by(FinancialAccount.archived_at.asc().nullsfirst(), FinancialAccount.id))]


def funds_overview(db, *, ledger_id, actor_account_id):
    from app.services.currency_binding_service import require_runtime_home_currency_code
    today = current_ledger_date(db, ledger_id=ledger_id)
    assets = liabilities = unknown = missing = included = 0
    for account in db.scalars(account_query(ledger_id, actor_account_id)):
        if not account.balance_known:
            unknown += 1
            continue
        value, _ = valuation(db, ledger_id=account.tenant_id, currency=account.currency_code,
            amount_minor=account_balance(db, account, cutoff=today), occurred_on=today)
        if value is None:
            missing += 1
            continue
        included += 1
        assets += max(0, value)
        liabilities += max(0, -value)
    return FundsOverview(home_currency_code=require_runtime_home_currency_code(db), valuation_date=today,
        assets_minor=assets, liabilities_minor=liabilities, net_worth_minor=assets-liabilities,
        included_accounts=included, unknown_accounts=unknown, missing_rate_accounts=missing)
