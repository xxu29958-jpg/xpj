"""Debt goals consume actual credit obligations and schedules, never netting as settlement."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CreditFacility, Debt, FinancialAccount
from app.schemas import DebtListResponse, GoalResponse
from app.services.credit_balance_projection import credit_home_balance, credit_projection_available, credit_visible
from app.services.credit_fee_query import fee_views
from app.services.installment_query import active_agreements, draw_balances, installment_view
from app.services.ledger_calendar_service import current_ledger_date


@dataclass(frozen=True)
class CreditGoalReading:
    status: str
    remaining_home_minor: int | None
    note: str
    account_public_id: str | None = None
    payoff_date: date | None = None


def list_goal_debts(db: Session, *, tenant_id: str, viewer_account_id: int | None = None) -> DebtListResponse:
    from app.services.debt_service import list_debts
    page = list_debts(db, tenant_id=tenant_id, viewer_account_id=viewer_account_id)
    credit_ids = [item.public_id for item in page.items if item.source_type == "credit_facility"]
    readings = {debt.public_id: read_credit_goal(db, debt, tenant_id)
        for debt in db.scalars(select(Debt).where(Debt.public_id.in_(credit_ids)))}
    page.items = [item.model_copy(update={"status": readings[item.public_id].status}) if item.public_id in readings else item
        for item in page.items if item.public_id not in readings or readings[item.public_id].status != "unavailable"]
    return page


def redact_credit_goal_receipt(db: Session, tenant_id: str, response: GoalResponse) -> GoalResponse:
    """Retain the accepted goal/version while applying today's shared-account access."""
    evaluation = response.debt_repayment
    if evaluation is None:
        return response
    identifiers = [link.debt_public_id for link in evaluation.linked_debts]
    visible = set(db.scalars(select(Debt.public_id).where(Debt.tenant_id == tenant_id,
        Debt.public_id.in_(identifiers), credit_visible(tenant_id, None))))
    if all(identifier in visible for identifier in identifiers):
        return response
    links = [link if link.debt_public_id in visible else link.model_copy(update={
        "status": "unavailable", "counterparty_label": None, "principal_amount_cents": None,
        "remaining_amount_cents": None, "source_id": None,
        "completion_note": "账户当前未向此账本共享；请调整关联欠款，或由账户所有者重新共享。",
    }) for link in evaluation.linked_debts]
    return response.model_copy(update={"debt_repayment": evaluation.model_copy(update={
        "linked_debts": links, "needs_review": True, "tracking_days": None,
        "projected_payoff_date": None, "three_state": None, "days_since_last_activity": None,
    })})


def read_credit_goal(db: Session, debt: Debt, ledger_id: str) -> CreditGoalReading:
    account = db.scalar(select(FinancialAccount).join(CreditFacility, CreditFacility.account_id == FinancialAccount.id)
        .where(CreditFacility.debt_id == debt.id))
    # Goals belong to the shared ledger, including when their viewer owns the account.
    if account is None or account.tenant_id != ledger_id or account.visibility != "ledger":
        return CreditGoalReading("unavailable", None, "账户当前未向此账本共享；请调整关联欠款，或由账户所有者重新共享。")
    if not account.balance_known or db.scalar(select(Debt.id).where(Debt.id == debt.id, credit_projection_available())) is None:
        return CreditGoalReading("unavailable", None, "账户余额或汇率待核对，请到资金账户处理。", account.public_id)
    remaining, _ = credit_home_balance(db, debt)
    balances = draw_balances(db, account.id)
    agreements = [installment_view(db, item, active=True, balances=balances) for item in active_agreements(db, account.id)]
    fees = fee_views(db, account.id)
    note = _completion_note(balances, agreements, fees)
    payoff = _scheduled_payoff(db, account, balances, agreements, fees) if note else None
    return CreditGoalReading("open" if note else "cleared", remaining,
        note or "已记录欠款和分期费用均已处理。", account.public_id, payoff)


def _completion_note(balances, agreements, fees) -> str:
    if any(row.remaining_minor > 0 for row in fees):
        return "仍有已发生费用未清偿，请到资金账户处理。"
    if any(item.needs_review for item in agreements):
        return "实际本金或费用与原计划不符，请按实际合约核对剩余分期安排。"
    if any(period.planned_fee_minor > period.paid_fee_minor for item in agreements for period in item.periods):
        return "还有分期费用安排，尚未全部完成；减免或终止请按实际合约更新。"
    if any(amount > 0 for amount in balances.values()):
        return "仍有欠款未清偿；账户有结余时，请先确认抵扣用途。"
    return ""


def _scheduled_payoff(db, account, balances, agreements, fees) -> date | None:
    if not agreements or any(item.needs_review for item in agreements):
        return None
    # An uncovered purchase or fee has no contract-backed payoff date.
    if sum(balances.values()) != sum(item.remaining_principal_minor for item in agreements):
        return None
    period_ids = {period.public_id for item in agreements for period in item.periods}
    if any(row.remaining_minor > 0 and row.period_public_id not in period_ids for row in fees):
        return None
    dates = _unpaid_due_dates(agreements)
    if not dates or min(dates) < current_ledger_date(db, ledger_id=account.tenant_id):
        return None
    return max(dates)


def _unpaid_due_dates(agreements) -> list[date]:
    return [period.due_on for item in agreements for period in item.periods
        if period.principal_minor > period.paid_principal_minor or period.planned_fee_minor > period.paid_fee_minor]
