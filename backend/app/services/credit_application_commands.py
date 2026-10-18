"""Use existing credit without inventing another payment or changing financial totals."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import CreditApplicationReview
from app.schemas.credit_application import CreditApplicationCreate, CreditApplicationVoid
from app.schemas.funds import FinancialAccountView
from app.services.credit_application_query import credit_application_choices
from app.services.funds_commands import claim_funds, finish_funds, replay_funds, require_account_version
from app.services.funds_fact_service import refresh_credit
from app.services.funds_query import get_account
from app.services.time_service import now_utc
from app.tenants import AuthContext


def apply_retained_credit(db: Session, *, auth: AuthContext, public_id: str, payload: CreditApplicationCreate,
                          key: str) -> FinancialAccountView:
    claim = claim_funds(db, auth, payload, key, "apply_retained_credit", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_account_version(account, payload.expected_row_version)
    if account.kind != "credit":
        raise AppError("invalid_request", "请从信用账户核对退款或预付款的用途。", status_code=422)
    available, outstanding = credit_application_choices(db, account.id)
    source, target = available.get(payload.credit_public_id), outstanding.get(payload.draw_public_id)
    if source is None or target is None or payload.amount_minor > min(source[1], target[1]):
        raise AppError("state_conflict", "原余额或欠款已变化，请保留输入并核对最新可抵扣金额。", status_code=409)
    db.add(CreditApplicationReview(account_id=account.id, credit_movement_id=source[0].id, draw_movement_id=target[0].id,
        amount_minor=payload.amount_minor, reason=payload.reason, actor_account_id=auth.account_id))
    account.row_version += 1
    refresh_credit(db, account)
    return finish_funds(db, auth, claim, account)


def void_credit_application(db: Session, *, auth: AuthContext, public_id: str, payload: CreditApplicationVoid,
                            key: str) -> FinancialAccountView:
    claim = claim_funds(db, auth, payload, key, "void_credit_application", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_account_version(account, payload.expected_row_version, allow_archived=True)
    review = db.scalar(select(CreditApplicationReview).where(CreditApplicationReview.account_id == account.id,
        CreditApplicationReview.public_id == payload.review_public_id))
    if review is None or review.voided_at is not None:
        raise AppError("state_conflict", "这条抵扣记录已变化，请核对原记录。", status_code=409)
    review.voided_at, review.void_actor_account_id, review.void_reason = now_utc(), auth.account_id, payload.reason
    account.row_version += 1
    refresh_credit(db, account)
    return finish_funds(db, auth, claim, account)
