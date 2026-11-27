"""Reversal and refund offset invariants for confirmed expense corrections."""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.errors import AppError
from app.models import (
    AccountMovement,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    FinancialAccount,
)


def _load_reversal_root_movements_and_fundings(
    db: Session,
    *,
    reversals: list[ExpenseOffsetFact],
) -> tuple[list[AccountMovement], list[ExpenseFunding]]:
    child = aliased(AccountMovement)
    reversal_rows = list(
        db.scalars(
            select(AccountMovement)
            .where(AccountMovement.offset_id.in_([offset.id for offset in reversals]))
            .where(
                ~exists(
                    select(child.id).where(child.reversal_of_id == AccountMovement.id)
                )
            )
        )
    )
    if not reversal_rows:
        return [], []
    account_ids = {row.account_id for row in reversal_rows}
    lineage = dict(
        db.execute(
            select(AccountMovement.id, AccountMovement.reversal_of_id).where(
                AccountMovement.account_id.in_(account_ids)
            )
        ).all()
    )
    root_ids: set[int] = set()
    for row in reversal_rows:
        root = row.id
        while lineage.get(root) is not None:
            root = lineage[root]
        root_ids.add(root)
    root_movements = list(
        db.scalars(select(AccountMovement).where(AccountMovement.id.in_(root_ids)))
    )
    restored_fundings = list(
        db.scalars(
            select(ExpenseFunding)
            .join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id)
            .where(AccountMovement.id.in_(root_ids))
        )
    )
    return root_movements, restored_fundings


def _load_active_fundings_excluding(
    db: Session,
    *,
    expense_id: int,
    excluded_ids: set[int],
) -> list[ExpenseFunding]:
    query = (
        select(ExpenseFunding)
        .where(ExpenseFunding.expense_id == expense_id)
        .where(ExpenseFunding.voided_at.is_(None))
    )
    if excluded_ids:
        query = query.where(ExpenseFunding.id.not_in(excluded_ids))
    return list(db.scalars(query))


def _load_opening_accounts(
    db: Session,
    fundings: tuple[ExpenseFunding, ...],
) -> list[FinancialAccount] | None:
    opening_account_ids = {
        funding.account_id for funding in fundings if funding.included_in_opening
    }
    if not opening_account_ids:
        return []
    opening_accounts = list(
        db.scalars(
            select(FinancialAccount).where(FinancialAccount.id.in_(opening_account_ids))
        )
    )
    if len(opening_accounts) != len(opening_account_ids):
        return None
    return opening_accounts


def _opening_dates_valid(opening_accounts: list[FinancialAccount], candidate_date) -> bool:
    return all(
        account.balance_known and candidate_date <= account.opening_date
        for account in opening_accounts
    )


def _evaluate_reversal_date_restoration(
    root_movements: list[AccountMovement],
    opening_accounts: list[FinancialAccount],
    *,
    before_date,
    after_date,
) -> tuple[bool, bool] | None:
    if root_movements:
        restorable_dates = {row.occurred_on for row in root_movements}
        if len(restorable_dates) != 1:
            return None
        restorable_date = next(iter(restorable_dates))
        before_invalid = before_date != restorable_date or not _opening_dates_valid(
            opening_accounts, before_date
        )
        after_valid = after_date == restorable_date and _opening_dates_valid(
            opening_accounts, after_date
        )
        return before_invalid, after_valid
    before_invalid = not _opening_dates_valid(opening_accounts, before_date)
    after_valid = _opening_dates_valid(opening_accounts, after_date) and (
        after_date == before_date or before_invalid
    )
    return before_invalid, after_valid


def _matches_legacy_reversal_restoration(
    expense: Expense,
    *,
    before_money: tuple[object, ...],
    restorable_currency: str,
    restorable_home: int,
    restorable_total: int,
    before_date_invalid: bool,
    after_date_valid: bool,
) -> bool:
    before_currency, before_original, before_home, _ = before_money
    before_amount = before_original if before_original is not None else before_home
    after_amount = (
        expense.original_amount_minor
        if expense.original_amount_minor is not None
        else expense.amount_cents
    )
    is_legacy_mismatch = (
        before_amount != restorable_total
        or before_currency != restorable_currency
        or before_home != restorable_home
        or before_date_invalid
    )
    return (
        is_legacy_mismatch
        and expense.original_currency_code == restorable_currency
        and after_amount == restorable_total
        and expense.amount_cents == restorable_home
        and after_date_valid
    )


def _restores_legacy_reversal_funding(
    db: Session,
    *,
    expense: Expense,
    before_money: tuple[object, ...],
    reversals: list[ExpenseOffsetFact],
) -> bool:
    root_movements, restored_fundings = _load_reversal_root_movements_and_fundings(
        db, reversals=reversals
    )
    existing_active = _load_active_fundings_excluding(
        db,
        expense_id=expense.id,
        excluded_ids={funding.id for funding in restored_fundings},
    )
    all_fundings = (*existing_active, *restored_fundings)
    if not all_fundings:
        return False
    restorable_currencies = {offset.original_currency_code for offset in reversals}
    restorable_homes = {offset.amount_cents for offset in reversals}
    if len(restorable_currencies) != 1 or len(restorable_homes) != 1:
        return False
    opening_accounts = _load_opening_accounts(db, all_fundings)
    if opening_accounts is None:
        return False
    date_check = _evaluate_reversal_date_restoration(
        root_movements,
        opening_accounts,
        before_date=before_money[3],
        after_date=expense.accounting_date,
    )
    if date_check is None:
        return False
    before_date_invalid, after_date_valid = date_check
    return _matches_legacy_reversal_restoration(
        expense,
        before_money=before_money,
        restorable_currency=next(iter(restorable_currencies)),
        restorable_home=next(iter(restorable_homes)),
        restorable_total=sum(funding.expense_amount_minor for funding in all_fundings),
        before_date_invalid=before_date_invalid,
        after_date_valid=after_date_valid,
    )


def _validate_refund_offsets_for_correction(
    expense: Expense,
    refund_offsets: list[ExpenseOffsetFact],
) -> None:
    from app.services.expense_offset_money import gross_original_minor

    refund_currencies = {offset.original_currency_code for offset in refund_offsets}
    if len(refund_currencies) != 1 or expense.original_currency_code != next(iter(refund_currencies)):
        raise AppError(
            "expense_refund_exists",
            "这笔账单已有生效退款，请先核对币种或撤销退款记录后再更正。",
            status_code=409,
        )
    active_refunded = sum(offset.original_amount_minor for offset in refund_offsets)
    if active_refunded > gross_original_minor(expense):
        raise AppError(
            "expense_refund_exceeds_remaining",
            "更正后的金额不能低于已生效的累计退款金额。",
            status_code=409,
        )


def validate_expense_offsets_for_correction(
    db: Session,
    *,
    expense: Expense,
    before_money: tuple[object, ...],
    funding_requested: bool,
) -> bool:
    from app.services.expense_funding_service import funding_money_identity

    money_changed = before_money != funding_money_identity(expense)
    if not money_changed and not funding_requested:
        return False
    active_offsets = list(
        db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == expense.tenant_id)
            .where(ExpenseOffsetFact.expense_id == expense.id)
            .where(ExpenseOffsetFact.status == "active")
            .order_by(ExpenseOffsetFact.id)
            .with_for_update()
        )
    )
    if not active_offsets:
        return False
    reversals = [offset for offset in active_offsets if offset.kind == "reversal"]
    if reversals:
        if funding_requested or not _restores_legacy_reversal_funding(
            db,
            expense=expense,
            before_money=before_money,
            reversals=reversals,
        ):
            raise AppError(
                "expense_reversal_active",
                "这笔账单已经冲销，请先撤销冲销记录后再更正金额、币种或付款组成。",
                status_code=409,
            )
        return True
    if not money_changed:
        return False
    refund_offsets = [offset for offset in active_offsets if offset.kind != "reversal"]
    _validate_refund_offsets_for_correction(expense, refund_offsets)
    return False
