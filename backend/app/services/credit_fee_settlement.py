"""Settle an already recorded expense without publishing another Expense."""
from app.errors import AppError
from app.money_contract import ensure_money_minor
from app.services.credit_allocation_service import allocation_totals
from app.services.credit_fee_query import fee_sources


def reviewed_fee_settlement(db, account, payer, payload):
    sources = {expense.id: (expense, movement) for _, expense, movement, _ in fee_sources(db, [account.id])}
    used, _, _ = allocation_totals(db, [movement.id for _, movement in sources.values()])
    remaining = {movement.id: -movement.amount_minor - used.get(movement.id, 0) for _, movement in sources.values()}
    chosen = {}
    for part in payload.fee_payments:
        source = sources.get(part.expense_id)
        if source is None or source[1].id in chosen:
            raise AppError("state_conflict", "已记费用已变化或重复选择，请查看原费用后继续。", status_code=409)
        expense, movement = source
        if payload.occurred_on < expense.accounting_date or part.amount_minor > remaining[movement.id]:
            raise AppError("funding_amount_mismatch", "费用付款日期不能早于发生日期，金额不能超过尚未清偿的原费用。", status_code=422)
        chosen[movement.id] = part.amount_minor
    amount = ensure_money_minor(sum(chosen.values()), sign="nonnegative", label="credit.fee_settlement")
    if account.currency_code == payer.currency_code and amount != payload.payer_fee_amount_minor:
        raise AppError("funding_amount_mismatch", "同币种已记费用清偿与实际费用扣款须一致。", status_code=422)
    if payload.overpayment_minor and any(value > chosen.get(identifier, 0) for identifier, value in remaining.items()):
        raise AppError("installment_amount_mismatch", "还有已发生费用未清偿，请先明确费用去向，再记录溢缴款。", status_code=422)
    return chosen, amount
