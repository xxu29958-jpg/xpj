"""Reuse purchase/settlement facts to distinguish spent cash from cash still owed."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountMovement, Expense, ExpenseFunding, FinancialAccount
from app.money_contract import round_minor_ratio_half_up
from app.services.credit_allocation_service import allocation_totals
from app.services.money_projection_service import project_recorded_amount, sum_projected_amounts
from app.services.spending_projection_service import PurchaseSpending


@dataclass(frozen=True)
class EnvelopeSpending:
    spent: int | None = 0
    unpaid: int | None = 0
    unlinked: int | None = 0


def _unsettled_parts(db: Session, *, tenant_id: str, home: str, purchases: list[PurchaseSpending]
                     ) -> dict[int, tuple[int | None, int | None]]:
    rows = list(db.execute(select(ExpenseFunding, FinancialAccount.kind, AccountMovement, Expense)
        .join(FinancialAccount, FinancialAccount.id == ExpenseFunding.account_id)
        .join(Expense, Expense.id == ExpenseFunding.expense_id)
        .outerjoin(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id)
        .where(ExpenseFunding.tenant_id == tenant_id, ExpenseFunding.voided_at.is_(None),
               ExpenseFunding.expense_id.in_([purchase.expense_id for purchase in purchases]))))
    used, _, _ = allocation_totals(db, [movement.id for _, _, movement, _ in rows if movement])
    results: dict[int, tuple[int | None, int | None]] = {}
    rates: dict = {}
    for funding, kind, movement, expense in rows:
        unpaid, unlinked = results.get(expense.id, (0, 0))
        if kind == "credit":
            amount = _credit_part(db, tenant_id=tenant_id, home=home, funding=funding, movement=movement,
                                  expense=expense, used=used, rates=rates)
            if funding.included_in_opening:
                unlinked = sum_projected_amounts((unlinked, amount), label="envelope.opening_credit")
            else:
                unpaid = sum_projected_amounts((unpaid, amount), label="envelope.unpaid")
        results[expense.id] = unpaid, unlinked
    return results


def _credit_part(db: Session, *, tenant_id: str, home: str, funding: ExpenseFunding,
                 movement: AccountMovement | None, expense: Expense, used: dict[int, int], rates: dict) -> int | None:
    if movement is None:
        source_currency = expense.home_currency_code
        amount = None if expense.amount_cents is None else round_minor_ratio_half_up(
            expense.amount_cents * funding.expense_amount_minor,
            expense.original_amount_minor or expense.amount_cents, label="envelope.opening_credit")
    elif used.get(movement.id, 0) >= abs(movement.amount_minor):
        return 0
    else:
        source_currency = movement.home_currency_code
        basis = movement.home_amount_cents
        amount = None if basis is None else abs(basis) - round_minor_ratio_half_up(
            abs(basis) * used.get(movement.id, 0), abs(movement.amount_minor), label="envelope.unpaid_credit")
    if amount is None:
        return None
    return project_recorded_amount(db, tenant_id=tenant_id, amount_minor=amount,
        source_currency=source_currency, home_currency=home, rate_date=expense.accounting_date,
        missing_rates=set(), rate_cache=rates)


def spending_by_purpose(db: Session, *, tenant_id: str, home: str, purchases: list[PurchaseSpending],
                        category_purposes: dict[str, set[str]]) -> dict[tuple[str, str], EnvelopeSpending]:
    parts = _unsettled_parts(db, tenant_id=tenant_id, home=home, purchases=purchases)
    results: dict[tuple[str, str], EnvelopeSpending] = {}
    for purchase in purchases:
        if purchase.month is None:
            continue
        category = "category:" + purchase.category
        purpose = category if category in category_purposes.get(purchase.month, set()) else "spending"
        key = purchase.month, purpose
        previous = results.get(key, EnvelopeSpending())
        net = purchase.amount_minor
        unpaid, unlinked = parts.get(purchase.expense_id, (0, None if net is None else max(0, net)))
        # Returns cannot leave more purchase-attributed cash reserved than the
        # remaining purchase; old credit opening amounts remain unlinked.
        unpaid = None if net is None or unpaid is None else min(max(0, net), unpaid)
        unlinked = None if net is None or unpaid is None or unlinked is None else min(max(0, net - unpaid), unlinked)
        results[key] = EnvelopeSpending(
            sum_projected_amounts((previous.spent, net), label="envelope.spent"),
            sum_projected_amounts((previous.unpaid, unpaid), label="envelope.unpaid"),
            sum_projected_amounts((previous.unlinked, unlinked), label="envelope.unlinked"))
    return results
