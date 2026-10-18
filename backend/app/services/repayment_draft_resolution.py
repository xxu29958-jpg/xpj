"""One source latch and expense correction for both ordinary and funded repayments."""
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, PaymentCapture, RepaymentDraft
from app.schemas import ExpenseOffsetCreateRequest
from app.services.payment_capture_identity import append_decision, capture_query
from app.services.time_service import now_utc


def lock_repayment_draft(db: Session, *, tenant_id: str, actor_account_id: int, public_id: str) -> RepaymentDraft:
    draft = db.scalar(ledger_scoped_select(RepaymentDraft, tenant_id).where(
        RepaymentDraft.created_by_account_id == actor_account_id,
        RepaymentDraft.public_id == public_id).with_for_update())
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    return draft


def lock_source_expense(db: Session, draft: RepaymentDraft) -> Expense | None:
    if draft.source_expense_public_id is None:
        return None
    source = db.scalar(ledger_scoped_select(Expense, draft.tenant_id).where(
        Expense.public_id == draft.source_expense_public_id).with_for_update())
    if (source is None or draft.source_expense_row_version is None
        or source.row_version != draft.source_expense_row_version):
        raise AppError("state_conflict", "原流水已变化，请回到原流水重新核对后作为还款处理。", status_code=409)
    if source.accounting_date is None:
        raise AppError("accounting_time_invalid", "请先补齐原流水的账务日期，再作为还款处理。", status_code=409)
    return source


def reverse_source_expense(db: Session, draft: RepaymentDraft, actor_account_id: int) -> None:
    source = lock_source_expense(db, draft)
    if source is None:
        return
    from app.services.expense_offset_service import create_expense_offset

    create_expense_offset(db, tenant_id=draft.tenant_id, expense_id=source.id,
        payload=ExpenseOffsetCreateRequest(kind="reversal", accounting_date=source.accounting_date,
            reason="误记为消费，已确认为还款", expected_row_version=draft.source_expense_row_version),
        effective_expected_row_version=draft.source_expense_row_version, actor_account_id=actor_account_id,
        actor_device_public_id=None, actor_device_name=None,
        idempotency_key=f"repayment-source:{draft.public_id}", commit=False)


def resolve_repayment_draft(db: Session, draft: RepaymentDraft, *, actor_account_id: int,
                            debt_public_id: str, repayment_public_id: str) -> None:
    draft.status = "confirmed"
    draft.committed_debt_public_id = debt_public_id
    draft.committed_repayment_public_id = repayment_public_id
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    if draft.source_expense_public_id:
        capture = db.scalar(capture_query(draft.tenant_id, actor_account_id).where(
            PaymentCapture.expense_public_id == draft.source_expense_public_id).with_for_update())
        if capture is not None:
            capture.repayment_public_id = draft.public_id
            append_decision(capture, kind="repayment", reason="误记为消费，人工确认还款并冲正原消费",
                actor_account_id=actor_account_id)
    db.flush()
