"""Account-scoped original identity shared by notification capture adapters."""

import hashlib
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, PaymentCapture, RepaymentDraft
from app.schemas.notification_fields import NotificationFieldEvidence
from app.schemas.notification_time import NotificationTimeEvidence
from app.schemas.payment_capture import PaymentCaptureResponse
from app.services.currency_binding_service import resolve_write_capability
from app.services.notification_field_service import freeze_notification_fields
from app.services.notification_time_service import freeze_notification_time, notification_time
from app.services.time_service import ensure_utc, now_utc


def capture_query(tenant_id: str, actor_account_id: int):
    return select(PaymentCapture).where(PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.actor_account_id == actor_account_id)


def list_review_captures(db: Session, *, tenant_id: str, actor_account_id: int) -> list[PaymentCaptureResponse]:
    rows = db.scalars(capture_query(tenant_id, actor_account_id).where(PaymentCapture.kind == "review")
        .order_by(PaymentCapture.captured_at.desc(), PaymentCapture.id.desc()))
    return [capture_response(db, row) for row in rows]


def identity_hash(notification_key: str) -> str:
    return hashlib.sha256(notification_key.encode()).hexdigest()


def reserve_capture(db: Session, *, tenant_id: str, actor_account_id: int, notification_key: str, **values):
    resolve_write_capability(db)
    key_hash = identity_hash(notification_key)
    public_id = str(uuid4())
    created = db.scalar(insert(PaymentCapture).values(public_id=public_id, tenant_id=tenant_id,
        actor_account_id=actor_account_id, identity_hash=key_hash, created_at=now_utc(), row_version=1,
        decisions=[], **values).on_conflict_do_nothing(constraint="uq_payment_capture_identity").returning(PaymentCapture.id))
    capture = db.scalar(capture_query(tenant_id, actor_account_id)
        .where(PaymentCapture.identity_hash == key_hash).with_for_update())
    return capture, created is not None


def require_capture(db: Session, *, tenant_id: str, actor_account_id: int, public_id: str, lock: bool = False):
    query = capture_query(tenant_id, actor_account_id).where(PaymentCapture.public_id == public_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppError("payment_capture_not_found", "这条通知不在当前账号和账本中。", status_code=404)
    return row


def capture_response(db: Session, capture: PaymentCapture) -> PaymentCaptureResponse:
    expense_id = db.scalar(select(Expense.id).where(Expense.tenant_id == capture.tenant_id,
        Expense.public_id == capture.expense_public_id)) if capture.expense_public_id else None
    return PaymentCaptureResponse(public_id=capture.public_id, row_version=capture.row_version,
        source=capture.source, captured_at=capture.captured_at, original_currency=capture.original_currency,
        original_amount_minor=capture.original_amount_minor, merchant=capture.merchant, kind=capture.kind,
        parser_version=capture.parser_version, candidates=capture.candidates, expense_id=expense_id,
        expense_public_id=capture.expense_public_id, repayment_public_id=capture.repayment_public_id,
        decisions=capture.decisions, recognition_time=notification_time(capture))


def link_capture(db: Session, capture: PaymentCapture, target: Expense | RepaymentDraft):
    field = PaymentCapture.expense_public_id if isinstance(target, Expense) else PaymentCapture.repayment_public_id
    previous = db.scalar(capture_query(capture.tenant_id, capture.actor_account_id)
        .where(field == target.public_id, PaymentCapture.id != capture.id).with_for_update())
    if previous is not None:
        # An old device replay supplies the identity absent from a historical draft.
        # Preserve the first time fragments before removing the uncommitted reservation;
        # missing years remain anchored to the historical delivery, never replay time.
        if previous.identity_hash not in (None, capture.identity_hash):
            raise AppError("state_conflict", "原通知身份不一致，请核对采集记录。", status_code=409)
        original_hash = capture.identity_hash
        if previous.time_evidence is None and capture.time_evidence is not None:
            previous.time_evidence = freeze_notification_time(
                NotificationTimeEvidence.model_validate(capture.time_evidence["input"]), ensure_utc(previous.captured_at))
        if previous.field_evidence is None and capture.field_evidence is not None:
            previous.field_evidence = freeze_notification_fields(
                NotificationFieldEvidence.model_validate(capture.field_evidence["input"]), previous.original_currency)
        db.delete(capture)
        db.flush()
        previous.identity_hash = original_hash
        return previous
    if isinstance(target, Expense):
        capture.expense_public_id = target.public_id
    else:
        capture.repayment_public_id = target.public_id
    return capture


def append_decision(capture: PaymentCapture, *, kind: str, reason: str, actor_account_id: int) -> None:
    capture.decisions = [*capture.decisions, {
        "from_kind": capture.kind, "to_kind": kind, "reason": reason,
        "at": now_utc().isoformat(), "actor_account_id": actor_account_id,
        "previous_version": capture.row_version,
        "expense_public_id": capture.expense_public_id, "repayment_public_id": capture.repayment_public_id,
    }]
    capture.kind = kind
    capture.row_version += 1
