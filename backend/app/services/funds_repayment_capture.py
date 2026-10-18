"""Bind a reviewed capture to the existing funded repayment transaction."""
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import FinancialAccount, PaymentCapture, RepaymentDraft
from app.schemas.funds import CreditPayment
from app.services.payment_capture_identity import append_decision, capture_query
from app.services.repayment_draft_resolution import lock_repayment_draft, lock_source_expense
from app.tenants import AuthContext


def prepare_repayment_capture(db: Session, auth: AuthContext, payload: CreditPayment) -> RepaymentDraft | None:
    if payload.source_repayment_draft_id is None:
        return None
    draft = lock_repayment_draft(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id,
        public_id=payload.source_repayment_draft_id)
    if draft.status != "pending":
        raise AppError("state_conflict", "这条还款采集已经处理，请查看原结果；本次输入仍保留。", status_code=409)
    # Match the existing correction lock order: source Expense before accounts/Debt.
    lock_source_expense(db, draft)
    return draft


def review_capture_amount(db: Session, draft: RepaymentDraft | None, credit: FinancialAccount,
                          payer: FinancialAccount, payload: CreditPayment) -> None:
    if draft is None:
        return
    if payload.source_amount_basis == "corrected":
        if not payload.source_review_reason:
            raise AppError("invalid_request", "通知金额有误时，请填写实际金额与核对依据。", status_code=422)
        capture = db.scalar(capture_query(draft.tenant_id, draft.created_by_account_id).where(
            PaymentCapture.repayment_public_id == draft.public_id).with_for_update())
        if capture is not None:
            append_decision(capture, kind="repayment", reason=payload.source_review_reason,
                actor_account_id=draft.created_by_account_id)
        return
    currency, amount = ((credit.currency_code, payload.principal_minor)
        if payload.source_amount_basis == "principal"
        else (payer.currency_code, payload.payer_amount_minor + payload.new_fee_minor))
    if currency != draft.original_currency_code or amount != draft.original_amount_minor:
        raise AppError("funding_amount_mismatch",
            "还款组成与通知金额不一致，请核对这条金额是扣款总额还是清偿本金；识别有误可填写更正依据。", status_code=422)
