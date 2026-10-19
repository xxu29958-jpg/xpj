"""Complete an existing purchase's payment source through the normal correction owner."""
from sqlalchemy import select

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, ExpenseFunding, ExpenseOffsetFact, FinancialAccount
from app.schemas import ExpenseCorrectionRequest
from app.schemas.funds import ExpenseFundingView, FundingViewPart
from app.services.funds_commands import claim_funds
from app.services.funds_query import account_scope, get_account
from app.services.idempotency import mark_idempotency_succeeded


def expense_funding_view(db, *, ledger_id, actor_account_id, expense_id):
    expense = db.scalar(select(Expense).where(Expense.id == expense_id, Expense.tenant_id == ledger_id))
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    visible = set(db.scalars(select(FinancialAccount.id).where(account_scope(ledger_id, actor_account_id))))
    reversed_expense = db.scalar(select(ExpenseOffsetFact.id).where(ExpenseOffsetFact.expense_id == expense.id,
        ExpenseOffsetFact.kind == "reversal", ExpenseOffsetFact.status == "active").limit(1)) is not None
    parts, editable = [], expense.status == "confirmed" and not reversed_expense
    for funding, account in db.execute(select(ExpenseFunding, FinancialAccount)
            .join(FinancialAccount, FinancialAccount.id == ExpenseFunding.account_id)
            .where(ExpenseFunding.expense_id == expense.id, ExpenseFunding.voided_at.is_(None))):
        allowed = account.id in visible
        editable = editable and allowed
        parts.append(FundingViewPart(component_id=funding.component_id, account_public_id=account.public_id if allowed else None,
            account_row_version=account.row_version if allowed else None,
            account_name=account.name if allowed else "其他成员的私人付款账户",
            currency_code=account.currency_code if allowed else None, expense_amount_minor=funding.expense_amount_minor,
            account_amount_minor=funding.account_amount_minor if allowed else None, included_in_opening=funding.included_in_opening))
    return ExpenseFundingView(expense_id=expense.id, expense_row_version=expense.row_version,
        currency_code=expense.original_currency_code, total_minor=expense.original_amount_minor,
        can_edit=editable, parts=parts)


def save_expense_funding(db, *, auth, expense_id, payload, key):
    claim = claim_funds(db, auth, payload, key, "save_expense_funding", str(expense_id))
    if claim is None:
        return replay_expense_funding(db, auth=auth, key=key)
    from app.services.expense_correction_service import correct_expense
    correct_expense(db, tenant_id=auth.tenant_id, expense_id=expense_id,
        payload=ExpenseCorrectionRequest(expected_row_version=payload.expected_row_version,
            reason=payload.reason, funding=payload.parts), actor_account_id=auth.account_id,
        actor_device_id=auth.device_id, idempotency_key=key, commit=False)
    result = expense_funding_view(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, expense_id=expense_id)
    mark_idempotency_succeeded(db, claim, resource_type="expense", resource_id=str(expense_id), response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def replay_expense_funding(db, *, auth, key) -> ExpenseFundingView:
    """Preserve acceptance without letting the old account details bypass current access."""
    original = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == auth.tenant_id,
        ApiIdempotencyKey.idempotency_key == key))
    result = ExpenseFundingView.model_validate(original.response_body)
    for part in result.parts:
        if part.account_public_id is not None:
            get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=part.account_public_id)
    return result
