"""Restore a misclassified committed capture through the existing fact commands."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountMovement, Expense, ExpenseOffsetFact, Repayment, RepaymentDraft, RepaymentVoid
from app.schemas import ExpenseOffsetCreateRequest, ExpenseOffsetVoidRequest, RepaymentVoidCreateRequest
from app.schemas.payment_capture import RepaymentCorrectionVersions
from app.services.debt_service._repayment_correction_context import (
    correction_debt,
    correction_funds,
    repayment_correction_versions,
    repayment_source_rows,
)
from app.services.debt_service._void import void_repayment
from app.services.expense_offset_lifecycle_service import void_expense_offset
from app.services.expense_offset_service import create_expense_offset
from app.services.funds_payment_correction import void_credit_payment_facts


def restore_misclassified_repayment(db: Session, *, draft: RepaymentDraft,
        versions: RepaymentCorrectionVersions | None, actor_account_id: int, reason: str, key: str) -> tuple[Expense | None, Repayment]:
    # Same order as confirmation: original Expense, then parent Debt. The capture
    # command already owns its draft lock and publishes the single final receipt.
    if draft.source_expense_public_id:
        db.scalar(select(Expense).where(Expense.tenant_id == draft.tenant_id,
            Expense.public_id == draft.source_expense_public_id).with_for_update())
    debt = correction_debt(db, draft)
    if debt is None:
        raise AppError("debt_not_found", status_code=404)
    repayment = db.scalar(select(Repayment).where(Repayment.debt_id == debt.id,
        Repayment.public_id == draft.committed_repayment_public_id))
    if repayment is None:
        raise AppError("repayment_not_found", status_code=404)
    _, fees = correction_funds(db, draft, repayment, lock=True) if repayment.settlement_kind == "credit" else ([], [])
    debt = correction_debt(db, draft, lock=True)
    if versions is None or versions != repayment_correction_versions(db, draft):
        raise AppError("state_conflict", "还款、付款账户或来源流水已变化，请重新核对更正影响；原输入仍保留。", status_code=409)
    source, offset = repayment_source_rows(db, draft)
    if draft.source_expense_public_id and source is None:
        raise AppError("state_conflict", "来源流水缺失，无法安全恢复；请保留原记录进行核对。", status_code=409)
    if source is not None:
        _restore_source(db, draft, source, offset, versions, actor_account_id, reason, key)
    if repayment.settlement_kind == "credit":
        _restore_credit(db, draft, repayment, fees, versions, actor_account_id, reason, key)
    elif not db.scalar(select(RepaymentVoid.id).where(RepaymentVoid.repayment_id == repayment.id)):
        void_repayment(db, tenant_id=draft.tenant_id, public_id=debt.public_id,
            payload=RepaymentVoidCreateRequest(repayment_public_id=repayment.public_id,
                expected_row_version=versions.debt_row_version, reason=reason),
            actor_account_id=actor_account_id, idempotency_key=key, commit=False)
    # Keep status and committed IDs as the original confirmation's history. A void
    # removes its financial and learning effect; PaymentCapture owns the correction.
    return source, repayment


def _restore_credit(db: Session, draft: RepaymentDraft, repayment: Repayment, fees: list[Expense],
        versions: RepaymentCorrectionVersions, actor_account_id: int, reason: str, key: str) -> None:
    offsets = list(db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.tenant_id == draft.tenant_id,
        ExpenseOffsetFact.expense_id.in_([fee.id for fee in fees]), ExpenseOffsetFact.status == "active")))
    if any(offset.kind != "reversal" for offset in offsets):
        raise AppError("state_conflict", "原还款费用已有退款记录，请先在该费用流水核对退款与更正；本次没有改变任何金额。", status_code=409)
    reversed_fees = {offset.expense_id for offset in offsets}
    for fee in fees:
        if fee.id not in reversed_fees:
            create_expense_offset(db, tenant_id=draft.tenant_id, expense_id=fee.id,
                payload=ExpenseOffsetCreateRequest(kind="reversal", accounting_date=fee.accounting_date,
                    reason=reason, expected_row_version=versions.fee_expense_versions[fee.id]),
                effective_expected_row_version=versions.fee_expense_versions[fee.id],
                actor_account_id=actor_account_id, actor_device_public_id=None, actor_device_name=None,
                idempotency_key=f"restore-fee:{key}:{fee.id}", commit=False)
    if db.scalar(select(RepaymentVoid.id).where(RepaymentVoid.repayment_id == repayment.id)) is not None:
        return
    rows = list(db.scalars(select(AccountMovement).where(AccountMovement.repayment_id == repayment.id,
        AccountMovement.kind == "repayment", AccountMovement.reversal_of_id.is_(None))))
    occurred_on = date.fromisoformat(repayment.accounting_time_snapshot["accounting_date"])
    void_credit_payment_facts(db, ledger_id=draft.tenant_id, actor_account_id=actor_account_id,
        repayment=repayment, rows=rows, reason=reason, occurred_on=occurred_on, key=key)


def _restore_source(db, draft, source, offset, versions, actor_account_id, reason, key):
    if offset is None or offset.kind != "reversal":
        raise AppError("state_conflict", "原消费的冲正关系需要核对，请打开原流水保留这次更正。", status_code=409)
    if offset.status == "active":
        void_expense_offset(db, tenant_id=draft.tenant_id, expense_id=source.id,
            offset_public_id=offset.public_id,
            payload=ExpenseOffsetVoidRequest(expected_row_version=versions.source_offset_row_version,
                void_reason=reason), actor_account_id=actor_account_id,
            actor_device_public_id=None, actor_device_name=None,
            idempotency_key=f"restore-source:{key}", commit=False)
