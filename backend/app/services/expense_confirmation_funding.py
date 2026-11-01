"""Resolve a selected payer against the authoritative, OCC-reviewed expense."""

from app.errors import AppError
from app.schemas.funds import FundingPart, FundingSelection
from app.services.funds_fact_service import lock_reviewed_accounts


def resolve_confirmation_funding(db, *, expense, selections, actor_account_id) -> list[FundingPart]:
    if not selections:
        return []
    accounts = lock_reviewed_accounts(db, ledger_id=expense.tenant_id, actor_account_id=actor_account_id,
        source_account_ids=[], parts=selections)
    currency = expense.original_currency_code
    total = expense.original_amount_minor
    if total is None and currency == expense.home_currency_code:
        total = expense.amount_cents
    resolved = []
    for index, selected in enumerate(selections):
        part = FundingSelection.model_validate(selected.model_dump())
        account = accounts[part.account_public_id]
        if part.expense_currency_code not in (None, currency) or part.account_currency_code not in (None, account.currency_code):
            raise AppError("state_conflict", "原付款币种已变化，请保留金额并重新核对，不能直接重试。", status_code=409)
        original = part.expense_amount_minor
        if original is None and len(selections) == 1:
            original = total
        if original is None or original <= 0:
            raise _missing_amount(index, "expense_amount_minor", "消费原币金额")
        native = part.account_amount_minor
        if native is None and account.currency_code == currency:
            native = original
        if native is None:
            raise _missing_amount(index, "account_amount_minor", "账户实际付款金额")
        resolved.append(FundingPart.model_validate({**part.model_dump(), "expense_amount_minor": original,
            "account_amount_minor": native, "expense_currency_code": currency,
            "account_currency_code": account.currency_code}))
    return resolved


def _missing_amount(index: int, field: str, label: str) -> AppError:
    return AppError("funding_amount_required", f"第 {index + 1} 项付款缺少{label}。", status_code=422,
        details={"field": f"funding.{index}.{field}"})
