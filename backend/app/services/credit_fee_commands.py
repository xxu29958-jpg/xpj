"""One incurred fee creates one Expense and one payable within the funds transaction."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CreditFeeObligation, FinancialAccount, InstallmentAgreement, InstallmentPeriod
from app.schemas import ExpenseManualCreateRequest
from app.schemas._accounting_time import AccountingTimeInput
from app.schemas.credit_fee import CreditFeeCreate
from app.schemas.funds import FinancialAccountView, FundingPart
from app.services.credit_fee_query import fee_period_totals
from app.services.debt_service._repayment_time import resolve_repayment_time
from app.services.expense_service._create import create_manual_expense
from app.services.funds_commands import claim_funds, finish_funds, replay_funds, require_account_version
from app.services.funds_fact_service import validate_movement_date
from app.services.funds_query import get_account
from app.services.installment_query import active_agreements, paid_by_period
from app.services.ledger_calendar_service import current_calendar
from app.tenants import AuthContext


def incur_credit_fee(db: Session, *, auth: AuthContext, public_id: str, payload: CreditFeeCreate,
                     key: str) -> FinancialAccountView:
    claim = claim_funds(db, auth, payload, key, "incur_credit_fee", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_account_version(account, payload.expected_row_version)
    if account.kind != "credit":
        raise AppError("invalid_request", "请选择产生这笔利息或手续费的信用账户。", status_code=422)
    validate_movement_date(db, account, payload.occurred_on)
    resolve_repayment_time(db, ledger_id=account.tenant_id, paid_at=None,
        time_input=AccountingTimeInput(precision="date_only", user_local_date=payload.occurred_on,
            calendar_revision=payload.calendar_revision))
    period_id = _review_fee_period(db, account, payload)
    saved = create_manual_expense(db, ExpenseManualCreateRequest(client_ref=f"credit-fee:{key}",
        original_currency_code=account.currency_code, original_amount_minor=payload.amount_minor,
        merchant=account.name, category="其他", note=payload.note,
        time_input=AccountingTimeInput(precision="date_only", user_local_date=payload.occurred_on,
            calendar_revision=current_calendar(db, ledger_id=auth.tenant_id).revision), funding=[FundingPart(
                component_id="fee", account_public_id=account.public_id, account_row_version=account.row_version,
                expense_amount_minor=payload.amount_minor, account_amount_minor=payload.amount_minor)]), auth, commit=False,
        credit_fee=CreditFeeObligation(account_id=account.id, period_id=period_id))
    source = db.get(CreditFeeObligation, saved.id)
    if source is None or (source.account_id, source.period_id) != (account.id, period_id):
        raise AppError("state_conflict", "原提交已对应其他消费，请核对来源后重新记录费用。", status_code=409)
    return finish_funds(db, auth, claim, account)


def _review_fee_period(db: Session, account: FinancialAccount, payload: CreditFeeCreate) -> int | None:
    if payload.period_public_id is None:
        return None
    active_ids = [row.id for row in active_agreements(db, account.id)]
    period = db.scalar(select(InstallmentPeriod).join(InstallmentAgreement).where(
        InstallmentAgreement.account_id == account.id, InstallmentAgreement.id.in_(active_ids),
        InstallmentPeriod.public_id == payload.period_public_id))
    if period is None:
        raise AppError("state_conflict", "这期期次已经变更，请保留费用依据并核对最新合约。", status_code=409)
    incurred, settled = fee_period_totals(db, [period.id])[period.id]
    paid = paid_by_period(db, [period.id])[period.id][1]
    if payload.amount_minor > period.planned_fee_minor - paid - incurred + settled:
        raise AppError("installment_amount_mismatch", "本期费用已记录或超出剩余计划；请查看原费用或按实际材料更新合约。", status_code=422)
    return period.id
