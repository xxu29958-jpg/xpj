"""Capture produces candidates; only explicit existing commands confirm financial facts."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, RepaymentDraft
from app.schemas import NotificationDraftCreateRequest, RepaymentDraftCreateRequest
from app.schemas.payment_capture import PaymentCaptureCreate, PaymentCaptureResponse
from app.services.currency_common import minor_amount_value, normalize_currency_code
from app.services.exchange_rate_service import amount_major_to_minor
from app.services.notification_field_service import freeze_notification_fields
from app.services.notification_time_service import freeze_notification_time
from app.services.payment_capture_identity import capture_response, link_capture, reserve_capture
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext


def _finish_expense(db, expense, fx_task):
    from app.services.pending_fx_task_service import submit_pending_expense_fx

    db.commit()
    if fx_task is not None:
        submit_pending_expense_fx(db, fx_task)
    db.refresh(expense)
    return expense


def _wrong_kind():
    return AppError("notification_classification_changed", "这条通知已有核对结果，请查看原采集记录，不要重复记账。", status_code=409)


def capture_legacy_expense(db: Session, payload: NotificationDraftCreateRequest, auth) -> Expense:
    from app.services.expense_service._notification_draft import stage_notification_draft

    capture = None
    if payload.notification_key:
        currency = normalize_currency_code(payload.original_currency or payload.original_currency_code or "CNY")
        amount = (amount_major_to_minor(payload.original_amount, currency) if payload.original_amount is not None
            else payload.original_amount_minor if payload.original_amount_minor is not None else payload.amount_cents)
        capture, fresh = reserve_capture(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
            notification_key=payload.notification_key, source=payload.source,
            captured_at=ensure_utc(payload.spent_at or payload.expense_time or now_utc()), original_currency=currency,
            original_amount_minor=amount if amount else None, merchant=payload.merchant, parser_version="legacy",
            candidates=[], kind="expense")
        if not fresh:
            if capture.kind != "expense" or capture.expense_public_id is None:
                raise _wrong_kind()
            return db.scalar(select(Expense).where(Expense.tenant_id == auth.tenant_id, Expense.public_id == capture.expense_public_id))
    expense, fx_task = stage_notification_draft(db, payload, auth)
    if capture:
        link_capture(db, capture, expense)
    return _finish_expense(db, expense, fx_task)


def capture_legacy_repayment(db, payload, *, tenant_id, actor_account_id) -> RepaymentDraft:
    from app.services.debt_service._repayment_capture import stage_repayment_draft

    capture = None
    if payload.notification_key:
        currency = normalize_currency_code(payload.original_currency or "CNY")
        amount = (amount_major_to_minor(payload.original_amount, currency) if payload.original_amount is not None else payload.amount_cents)
        capture, fresh = reserve_capture(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
            notification_key=payload.notification_key, source=payload.source,
            captured_at=ensure_utc(payload.captured_at or now_utc()), original_currency=currency,
            original_amount_minor=amount, merchant=payload.merchant_label, parser_version="legacy", candidates=[], kind="repayment")
        if not fresh:
            if capture.kind != "repayment" or capture.repayment_public_id is None:
                raise _wrong_kind()
            return db.scalar(select(RepaymentDraft).where(RepaymentDraft.tenant_id == tenant_id,
                RepaymentDraft.created_by_account_id == actor_account_id, RepaymentDraft.public_id == capture.repayment_public_id))
    draft = stage_repayment_draft(db, payload=payload, tenant_id=tenant_id, actor_account_id=actor_account_id)
    if capture:
        capture = link_capture(db, capture, draft)
        if capture.kind != "repayment":
            db.commit()  # identity backfill is safe; classification stays human-owned.
            raise _wrong_kind()
    db.commit()
    db.refresh(draft)
    return draft


def stage_capture_target(db, capture, *, auth, kind, currency, amount, merchant, notification_key=None):
    if amount is None or amount <= 0:
        raise AppError("amount_required", "请选择并核对这次交易的金额。", status_code=422)
    # A classification revision creates one pending target, never a confirmed fact.
    key = notification_key or f"capture:{capture.public_id}:{capture.row_version}:{kind}"
    if kind == "expense":
        from app.services.expense_service._notification_draft import stage_notification_draft

        expense, fx_task = stage_notification_draft(db, NotificationDraftCreateRequest(source=capture.source,
            original_currency=currency, original_amount=minor_amount_value(amount, currency),
            # Delivery can be delayed; no transaction time was supplied here.
            merchant=merchant, notification_key=key), auth)
        return link_capture(db, capture, expense), fx_task
    from app.services.debt_service._repayment_capture import stage_repayment_draft

    draft = stage_repayment_draft(db, payload=RepaymentDraftCreateRequest(source=capture.source,
        original_currency=currency, original_amount=minor_amount_value(amount, currency),
        merchant_label=merchant, captured_at=capture.captured_at, notification_key=key),
        tenant_id=auth.tenant_id, actor_account_id=auth.account_id)
    return link_capture(db, capture, draft), None


def capture_notification(db: Session, *, auth: AuthContext, payload: PaymentCaptureCreate) -> PaymentCaptureResponse:
    from app.services.expense_service._helpers import _clean_notification_source

    source = _clean_notification_source(payload.source)
    currency = normalize_currency_code(payload.original_currency)
    capture, fresh = reserve_capture(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        notification_key=payload.notification_key, source=source, captured_at=ensure_utc(payload.captured_at),
        original_currency=currency, original_amount_minor=payload.original_amount_minor, merchant=payload.merchant,
        parser_version=payload.parser_version, candidates=[item.model_dump() for item in payload.candidates],
        time_evidence=freeze_notification_time(payload.time_evidence, ensure_utc(payload.captured_at)),
        field_evidence=freeze_notification_fields(payload.field_evidence, currency),
        kind=payload.suggested_kind)
    fx_task = None
    if fresh and capture.kind != "review":
        capture, fx_task = stage_capture_target(db, capture, auth=auth, kind=capture.kind,
            currency=currency, amount=payload.original_amount_minor, merchant=payload.merchant,
            notification_key=payload.notification_key)
    db.commit()
    if fx_task is not None:
        from app.services.pending_fx_task_service import submit_pending_expense_fx

        submit_pending_expense_fx(db, fx_task)
    return capture_response(db, capture)
