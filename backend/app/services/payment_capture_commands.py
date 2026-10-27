"""Explicit capture decisions: one original event, one active draft, one transaction."""

from sqlalchemy import select

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, PaymentCapture, RepaymentDraft
from app.schemas.payment_capture import PaymentCaptureResponse
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import normalize_currency_code
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.payment_capture_identity import (
    append_decision,
    capture_query,
    capture_response,
    identity_hash,
    require_capture,
    reserve_capture,
)
from app.services.payment_capture_service import stage_capture_target
from app.services.time_service import now_utc


def _claim(db, auth, public_id, payload, key, operation):
    if not payload.reason.strip():
        raise AppError("decision_reason_required", "请说明这次核对的原因。", status_code=422)
    body = payload.model_dump(mode="json", exclude={"expected_row_version"})
    # Optional funds correction fields must not change pre-upgrade receipt identities.
    for field in ("expense_currency", "expense_amount_minor"):
        if body.get(field) is None:
            body.pop(field, None)
    if body.get("correction_versions"):
        for field in ("funds_account_versions", "fee_expense_versions"):
            if not body["correction_versions"].get(field):
                body["correction_versions"].pop(field, None)
    return claim_idempotent_request(db, tenant_id=auth.tenant_id, idempotency_key=key,
        operation=operation, target_type="payment_capture", target_id=public_id,
        expected_row_version=getattr(payload, "expected_row_version", None),
        body={**body, "actor_account_id": auth.account_id})


def _commit(db, capture, claim, fx_task=None):
    result = capture_response(db, capture)
    if claim is not None:
        mark_idempotency_succeeded(db, claim, resource_type="payment_capture", resource_id=capture.public_id,
            response_body=result.model_dump(mode="json"))
    db.commit()
    if fx_task is not None:
        from app.services.pending_fx_task_service import submit_pending_expense_fx

        submit_pending_expense_fx(db, fx_task)
    return result


def _accepted_receipt(db, auth, key):
    # The successful claim already checked the actor and complete original body.
    # Later human corrections must not turn an accepted, lost reply into a failure.
    row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == auth.tenant_id,
        ApiIdempotencyKey.idempotency_key == key))
    return PaymentCaptureResponse.model_validate(row.response_body)


def decide_capture(db, *, auth, public_id, payload, idempotency_key):
    claim = _claim(db, auth, public_id, payload, idempotency_key, "decide_payment_capture")
    if claim is None:
        return _accepted_receipt(db, auth, idempotency_key)
    capture = require_capture(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=public_id, lock=True)
    resolve_write_capability(db)
    if capture.row_version != payload.expected_row_version or capture.kind != "review":
        raise AppError("state_conflict", "这条通知已被核对，请刷新后查看结果。", status_code=409)
    currency = normalize_currency_code(payload.original_currency)
    fx_task = None
    if payload.kind != "dismissed":
        capture, fx_task = stage_capture_target(db, capture, auth=auth, kind=payload.kind,
            currency=currency, amount=payload.original_amount_minor, merchant=payload.merchant)
    append_decision(capture, kind=payload.kind, reason=payload.reason.strip(), actor_account_id=auth.account_id)
    capture.original_currency = currency
    capture.original_amount_minor = payload.original_amount_minor
    capture.merchant = payload.merchant
    return _commit(db, capture, claim, fx_task)


def _require_repayment_identity(draft, capture, notification_key):
    if notification_key:
        from app.services.debt_service._repayment_capture import _repayment_draft_key

        expected = _repayment_draft_key(source=draft.source, merchant=draft.merchant_label,
            amount_cents=draft.original_amount_minor or draft.amount_cents,
            home_currency=draft.original_currency_code or draft.home_currency_code,
            captured_at=draft.captured_at, notification_key=notification_key)
        if expected != draft.draft_idempotency_key:
            raise AppError("capture_identity_mismatch", "原通知与这条草稿不匹配，请重新打开原采集。", status_code=409)
        if capture and capture.identity_hash not in (None, identity_hash(notification_key)):
            raise AppError("capture_identity_mismatch", "原通知身份不一致，请重新打开原采集核对。", status_code=409)


def _capture_for_repayment(db, auth, draft, notification_key) -> PaymentCapture:
    capture = db.scalar(capture_query(auth.tenant_id, auth.account_id)
        .where(PaymentCapture.repayment_public_id == draft.public_id).with_for_update())
    if capture is None and draft.source_expense_public_id:
        capture = db.scalar(capture_query(auth.tenant_id, auth.account_id)
            .where(PaymentCapture.expense_public_id == draft.source_expense_public_id).with_for_update())
        if capture is not None:
            capture.repayment_public_id = draft.public_id
    _require_repayment_identity(draft, capture, notification_key)
    if capture is None:
        values = {"source": draft.source, "captured_at": draft.captured_at,
            "original_currency": draft.original_currency_code or draft.home_currency_code,
            "original_amount_minor": draft.original_amount_minor or draft.amount_cents, "merchant": draft.merchant_label,
            "parser_version": "legacy", "candidates": [], "kind": "repayment"}
        if notification_key:
            capture, _ = reserve_capture(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
                notification_key=notification_key, **values)
            if capture.repayment_public_id not in (None, draft.public_id):
                raise AppError("capture_identity_mismatch", "原通知身份不一致，请重新打开原采集核对。", status_code=409)
            capture.repayment_public_id = draft.public_id
        else:
            capture = PaymentCapture(tenant_id=auth.tenant_id, actor_account_id=auth.account_id,
                repayment_public_id=draft.public_id, row_version=1, decisions=[], created_at=now_utc(), **values)
            db.add(capture)
            db.flush()
    elif notification_key:
        capture.identity_hash = identity_hash(notification_key)
    return capture


def repayment_as_expense(db, *, auth, public_id, payload, idempotency_key) -> PaymentCaptureResponse:
    claim = _claim(db, auth, public_id, payload, idempotency_key, "repayment_as_expense")
    if claim is None:
        return _accepted_receipt(db, auth, idempotency_key)
    resolve_write_capability(db)
    draft = db.scalar(select(RepaymentDraft).where(RepaymentDraft.tenant_id == auth.tenant_id,
        RepaymentDraft.created_by_account_id == auth.account_id, RepaymentDraft.public_id == public_id).with_for_update())
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    capture = _capture_for_repayment(db, auth, draft, payload.notification_key)
    if capture.kind == "expense" and capture.expense_public_id and draft.status in {"dismissed", "confirmed"}:
        # Includes lost-response retry and a second click with a new intent key.
        return _commit(db, capture, claim)
    if draft.status == "confirmed":
        return _correct_confirmed_capture(db, auth, draft, capture, payload, idempotency_key, claim)
    if draft.status != "pending":
        raise AppError("state_conflict", "这条采集已处理，请刷新后查看。", status_code=409)
    fx_task = None
    if draft.source_expense_public_id:
        # An Expense -> repayment review has not reversed its source yet. Undoing
        # that review must return the original expense, never make a second one.
        source = db.scalar(select(Expense).where(Expense.tenant_id == auth.tenant_id,
            Expense.public_id == draft.source_expense_public_id))
        if source is None:
            raise AppError("expense_not_found", status_code=404)
        capture.expense_public_id = source.public_id
    elif capture.expense_public_id is None:
        capture, fx_task = stage_capture_target(db, capture, auth=auth, kind="expense",
            currency=capture.original_currency, amount=capture.original_amount_minor, merchant=capture.merchant)
    draft.status = "dismissed"
    from app.services.learning_service._lifecycle import close_active_decisions_for_subject

    close_active_decisions_for_subject(db, tenant_id=draft.tenant_id, subject_kind="repayment_draft", subject_id=draft.id)
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = auth.account_id
    append_decision(capture, kind="expense", reason=payload.reason.strip(), actor_account_id=auth.account_id)
    return _commit(db, capture, claim, fx_task)


def _correct_confirmed_capture(db, auth, draft, capture, payload, key, claim) -> PaymentCaptureResponse:
    from app.models import AccountMovement
    from app.services.expense_funding_service import expense_funding_account_ids
    from app.services.goal_debt_repayment_achievement import stage_debt_goal_achievements
    from app.services.repayment_capture_correction import restore_misclassified_repayment

    if (payload.correction_versions and payload.correction_versions.funds_account_versions
            and not draft.source_expense_public_id and (payload.expense_currency is None or payload.expense_amount_minor is None)):
        raise AppError("invalid_request", "请按实际交易核对消费金额与币种；原还款本金和扣款总额不能代替消费金额。", status_code=422)
    source, repayment = restore_misclassified_repayment(db, draft=draft, versions=payload.correction_versions,
        actor_account_id=auth.account_id, reason=payload.reason.strip(), key=key)
    fx_task = None
    if source is not None:
        capture.expense_public_id = source.public_id
    else:
        # The reviewed payment may differ from the original parser proposal.
        # Use the committed amount, while retaining raw capture evidence/history.
        capture, fx_task = stage_capture_target(db, capture, auth=auth, kind="expense",
            currency=payload.expense_currency or repayment.original_currency_code or draft.home_currency_code,
            amount=payload.expense_amount_minor or repayment.original_amount_minor or repayment.amount_cents, merchant=capture.merchant)
    append_decision(capture, kind="expense", reason=payload.reason.strip(), actor_account_id=auth.account_id)
    account_ids = set(db.scalars(select(AccountMovement.account_id).where(AccountMovement.repayment_id == repayment.id)))
    if source is not None:
        account_ids.update(expense_funding_account_ids(db, source.id))
    stage_debt_goal_achievements(db, debt_ids=[repayment.debt_id], account_ids=account_ids)
    return _commit(db, capture, claim, fx_task)
