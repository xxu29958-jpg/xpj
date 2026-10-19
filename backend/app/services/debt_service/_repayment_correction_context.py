"""Read the exact source and versions that a repayment correction will affect."""

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AccountMovement,
    CreditFacility,
    Debt,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    ExpenseOffsetRevision,
    FinancialAccount,
    Repayment,
    RepaymentDraft,
)
from app.schemas.payment_capture import RepaymentCorrectionVersions
from app.services.funds_query import account_query


def repayment_source_rows(db, draft):
    source = db.scalar(select(Expense).where(Expense.tenant_id == draft.tenant_id,
        Expense.public_id == draft.source_expense_public_id)) if draft.source_expense_public_id else None
    offset = db.scalar(select(ExpenseOffsetFact).join(ExpenseOffsetRevision, ExpenseOffsetRevision.offset_id == ExpenseOffsetFact.id)
        .where(ExpenseOffsetFact.tenant_id == draft.tenant_id, ExpenseOffsetRevision.tenant_id == draft.tenant_id,
        ExpenseOffsetFact.expense_id == source.id,
        ExpenseOffsetRevision.idempotency_key == f"repayment-source:{draft.public_id}")) if source else None
    return source, offset


def correction_debt(db: Session, draft: RepaymentDraft, *, lock: bool = False) -> Debt | None:
    allowed = account_query(draft.tenant_id, draft.created_by_account_id).with_only_columns(FinancialAccount.id)
    query = select(Debt).outerjoin(CreditFacility, CreditFacility.debt_id == Debt.id).where(
        Debt.public_id == draft.committed_debt_public_id,
        or_(and_(CreditFacility.id.is_(None), Debt.tenant_id == draft.tenant_id), CreditFacility.account_id.in_(allowed)))
    return db.scalar(query.with_for_update(of=Debt).execution_options(populate_existing=True) if lock else query)


def correction_funds(db: Session, draft: RepaymentDraft, repayment: Repayment, *, lock: bool = False) -> tuple[list[FinancialAccount], list[Expense]]:
    fees = list(db.scalars(select(Expense).join(ExpenseFunding, ExpenseFunding.expense_id == Expense.id)
        .join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id).where(
            Expense.tenant_id == draft.tenant_id, ExpenseFunding.tenant_id == draft.tenant_id,
            AccountMovement.repayment_id == repayment.id, AccountMovement.reversal_of_id.is_(None)).distinct()))
    if lock and fees:
        fees = list(db.scalars(select(Expense).where(Expense.tenant_id == draft.tenant_id,
            Expense.id.in_([fee.id for fee in fees])).order_by(Expense.id).with_for_update().execution_options(populate_existing=True)))
    identifiers = set(db.scalars(select(AccountMovement.account_id).where(AccountMovement.repayment_id == repayment.id)))
    if draft.source_expense_public_id:
        identifiers.update(db.scalars(select(ExpenseFunding.account_id).join(Expense, Expense.id == ExpenseFunding.expense_id)
            .where(ExpenseFunding.tenant_id == draft.tenant_id, Expense.tenant_id == draft.tenant_id,
                Expense.public_id == draft.source_expense_public_id)))
    query = account_query(draft.tenant_id, draft.created_by_account_id).where(FinancialAccount.id.in_(identifiers)).order_by(FinancialAccount.public_id)
    accounts = list(db.scalars(query.with_for_update(of=FinancialAccount).execution_options(populate_existing=True) if lock else query))
    if len(accounts) != len(identifiers):
        raise AppError("fund_account_not_found", "更正涉及的资金账户暂不可访问，请回到原身份与账本核对。", status_code=404)
    return accounts, fees


def repayment_correction_versions(db: Session, draft: RepaymentDraft) -> RepaymentCorrectionVersions | None:
    if draft.status != "confirmed":
        return None
    debt = correction_debt(db, draft)
    if debt is None or debt.status == "voided":
        return None
    source, offset = repayment_source_rows(db, draft)
    if draft.source_expense_public_id and (source is None or offset is None):
        return None
    repayment = db.scalar(select(Repayment).where(Repayment.debt_id == debt.id,
        Repayment.public_id == draft.committed_repayment_public_id))
    if repayment is None:
        return None
    try:
        accounts, fees = correction_funds(db, draft, repayment) if repayment.settlement_kind == "credit" else ([], [])
    except AppError as error:
        if error.error != "fund_account_not_found":
            raise
        return None
    return RepaymentCorrectionVersions(debt_row_version=debt.row_version,
        source_expense_row_version=source.row_version if source else None,
        source_offset_row_version=offset.row_version if offset else None,
        funds_account_versions={row.public_id: row.row_version for row in accounts},
        fee_expense_versions={row.id: row.row_version for row in fees})
