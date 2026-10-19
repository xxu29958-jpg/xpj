"""Apply the user's explicit principal/period allocation within the payment transaction."""
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountMovement, FinancialAccount, InstallmentDraw, InstallmentPayment, InstallmentPeriod
from app.schemas.funds import CreditPayment
from app.schemas.installment import InstallmentPaymentPart
from app.services.installment_query import active_agreements, draw_balances, paid_by_period


def unambiguous_principal(balances, amount):
    if not amount:
        return {}, []
    if len(balances) != 1 or amount > sum(balances.values()):
        raise AppError("installment_allocation_required", "请按账单选择本次清偿的本金；超出欠款的部分明确记为溢缴款，不能自动按最早购买分配。", status_code=422)
    return {next(iter(balances)): amount}, []


def reviewed_settlement(db: Session, account: FinancialAccount, payer: FinancialAccount, payload: CreditPayment
                        ) -> tuple[dict[int, int], list[tuple[InstallmentPeriod, InstallmentPaymentPart]]]:
    active = active_agreements(db, account.id)
    balances = {identifier: value for identifier, value in draw_balances(db, account.id).items() if value > 0}
    explicit = bool(active or payload.period_allocations or payload.draw_allocations or payload.overpayment_minor)
    if not explicit:
        return unambiguous_principal(balances, payload.principal_minor)
    _validate_total(payload)
    sources: dict[int, list[int]] = {row.id: [] for row in active}
    for agreement_id, movement_id in db.execute(select(InstallmentDraw.agreement_id, InstallmentDraw.movement_id)
            .where(InstallmentDraw.agreement_id.in_([row.id for row in active]))):
        sources[agreement_id].append(movement_id)
    assigned = {identifier for group in sources.values() for identifier in group}
    draws = {row.id: row for row in db.scalars(select(AccountMovement).where(AccountMovement.account_id == account.id, AccountMovement.amount_minor < 0))}
    available = {identifier: balances.get(identifier, 0) for identifier in draws}
    chosen: dict[int, int] = {}
    periods = _review_period_allocations(db, payload.period_allocations, sources, balances)
    for period, part in periods:
        _take_from(available, chosen, sources[period.agreement_id], part.principal_minor)
    _allocate_unassigned_draws(payload, draws, assigned, available, chosen)
    validate_paid_fees(account, payer, payload)
    return chosen, periods


def _allocate_unassigned_draws(payload: CreditPayment, draws: dict[int, AccountMovement], assigned: set[int],
        available: dict[int, int], chosen: dict[int, int]) -> None:
    for part in payload.draw_allocations:
        draw = next((row for row in draws.values() if row.public_id == part.draw_public_id), None)
        if draw is None or draw.id in assigned:
            raise AppError("invalid_request", "请从未分期本金选择来源，已分期本金从对应期次清偿。", status_code=422)
        _take_from(available, chosen, [draw.id], part.principal_minor)
    if payload.overpayment_minor and any(value > 0 for value in available.values()):
        raise AppError("installment_amount_mismatch", "还有未分配的欠款本金；请先明确清偿去向，超出全部欠款的部分才是溢缴款。", status_code=422)


def _validate_total(payload: CreditPayment) -> None:
    if sum(part.principal_minor for part in payload.period_allocations + payload.draw_allocations) + payload.overpayment_minor != payload.principal_minor:
        raise AppError("installment_allocation_required", "请把本次本金明确分配到期次、未分期本金或溢缴款，合计须等于清偿本金。", status_code=422)
    if len({p.period_public_id for p in payload.period_allocations}) != len(payload.period_allocations):
        raise AppError("invalid_request", "同一期次请合并为一项分配。", status_code=422)


def _take_from(available: dict[int, int], chosen: dict[int, int], source_ids: list[int], amount: int) -> None:
    for identifier in sorted(source_ids):
        take = min(amount, available[identifier])
        if take > 0:
            chosen[identifier] = chosen.get(identifier, 0) + take
            available[identifier] -= take
            amount -= take
    if amount:
        raise AppError("installment_amount_mismatch", "来源本金已变化，请核对合约和实际欠款后继续。", status_code=409)


def _review_period_allocations(db: Session, parts: list[InstallmentPaymentPart], sources: dict[int, list[int]],
                              balances: dict[int, int]) -> list[tuple[InstallmentPeriod, InstallmentPaymentPart]]:
    records = list(db.scalars(select(InstallmentPeriod).where(InstallmentPeriod.agreement_id.in_(sources))))
    by_public_id = {period.public_id: period for period in records}
    paid = paid_by_period(db, [period.id for period in records])
    scheduled: dict[int, int] = defaultdict(int)
    for period in records:
        scheduled[period.agreement_id] += period.principal_minor - paid[period.id][0]
    remaining = {identifier: sum(balances.get(draw, 0) for draw in draws) for identifier, draws in sources.items()}
    reviewed = []
    for part in parts:
        if not part.principal_minor and not part.fee_minor:
            continue
        period = by_public_id.get(part.period_public_id)
        if period is None:
            raise AppError("state_conflict", "分期期次已变更，请核对最新合约。", status_code=409)
        if part.principal_minor and remaining[period.agreement_id] != scheduled[period.agreement_id]:
            raise AppError("installment_review_required", "退款或更正已改变分期本金，请按实际合约更新剩余排期后继续；已付费用保留。", status_code=409)
        principal = paid[period.id][0]
        if part.principal_minor > period.principal_minor - principal:
            raise AppError("installment_amount_mismatch", "本次本金分配超过该期未付本金；合约有变更时先更新合约。", status_code=422)
        reviewed.append((period, part))
    return reviewed


def validate_paid_fees(account, payer, payload):
    fees = sum(part.fee_minor for part in payload.period_allocations)
    if fees and not payload.new_fee_minor:
        raise AppError("invalid_request", "本次发生的分期费用还需填写实际扣款金额。", status_code=422)
    if account.currency_code == payer.currency_code and fees > payload.new_fee_minor:
        raise AppError("funding_amount_mismatch", "分期费用分配不能超过本次新发生费用。", status_code=422)


def record_installment_payments(db, repayment, periods, fee):
    db.add_all([InstallmentPayment(period_id=period.id, repayment_id=repayment.id,
        principal_minor=part.principal_minor, fee_minor=part.fee_minor,
        fee_expense_id=fee.id if fee is not None and part.fee_minor else None) for period, part in periods])
