"""Read the exact source and versions that a repayment correction will affect."""

from sqlalchemy import select

from app.models import Debt, Expense, ExpenseOffsetFact, ExpenseOffsetRevision
from app.schemas.payment_capture import RepaymentCorrectionVersions


def repayment_source_rows(db, draft):
    source = db.scalar(select(Expense).where(Expense.tenant_id == draft.tenant_id,
        Expense.public_id == draft.source_expense_public_id)) if draft.source_expense_public_id else None
    offset = db.scalar(select(ExpenseOffsetFact).join(ExpenseOffsetRevision, ExpenseOffsetRevision.offset_id == ExpenseOffsetFact.id)
        .where(ExpenseOffsetFact.tenant_id == draft.tenant_id, ExpenseOffsetRevision.tenant_id == draft.tenant_id,
        ExpenseOffsetFact.expense_id == source.id,
        ExpenseOffsetRevision.idempotency_key == f"repayment-source:{draft.public_id}")) if source else None
    return source, offset


def repayment_correction_versions(db, draft) -> RepaymentCorrectionVersions | None:
    if draft.status != "confirmed":
        return None
    debt = db.scalar(select(Debt).where(Debt.tenant_id == draft.tenant_id,
        Debt.public_id == draft.committed_debt_public_id))
    if debt is None or debt.status == "voided":
        return None
    source, offset = repayment_source_rows(db, draft)
    if draft.source_expense_public_id and (source is None or offset is None):
        return None
    return RepaymentCorrectionVersions(debt_row_version=debt.row_version,
        source_expense_row_version=source.row_version if source else None,
        source_offset_row_version=offset.row_version if offset else None)
