"""Create-side flows: upload-driven pending, manual entry, notification draft."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import ExpenseManualCreateRequest, ExpenseResponse, NotificationDraftCreateRequest
from app.services import permission_service
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.classify_service import classify_expense
from app.services.currency_binding_service import (
    assert_currency_binding_consistent,
    require_runtime_home_currency_code,
    resolve_write_capability,
)
from app.services.duplicate_service import mark_duplicate_status
from app.services.exchange_rate_service import (
    apply_currency_payload,
    validate_currency_payload_money_command,
)
from app.services.expense_accounting_time_service import apply_expense_time_input, refresh_legacy_expense_time
from app.services.expense_funding_service import publish_expense_funding
from app.services.expense_response_service import expense_to_response
from app.services.expense_revision_service import record_confirmation_revision
from app.services.expense_service._helpers import (
    _clean_category,
    _clean_optional_text,
    _clean_text,
    _expense_has_pending_fx,
)
from app.services.file_service import SavedUpload
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    mark_idempotency_succeeded,
)
from app.services.manual_expense_receipt import (
    _manual_receipt,
    _manual_receipt_key,
    _manual_request_fingerprint,
    _manual_review_error,
    local_ref_storage_key,
)
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext

__all__ = [
    "create_manual_expense",
    "create_notification_draft",
    "stage_pending_expense",
]


def _materialize_category_preference(db: Session, expense: Expense) -> None:
    ensure_category_preference_for_name(db, tenant_id=expense.tenant_id, name=expense.category)


def stage_pending_expense(
    db: Session,
    saved_file: SavedUpload,
    tenant_id: str,
    *,
    source: str = "iPhone截图",
) -> Expense:
    """Stage one Pending expense without committing the caller's transaction."""

    now = now_utc()
    frozen_home_currency = require_runtime_home_currency_code(db)
    # Pending facts freeze the Owner-confirmed basis before taking a writer proof.
    assert_currency_binding_consistent(db, frozen_home_currency)
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=None,
        home_currency_code=frozen_home_currency,
        original_currency_code=frozen_home_currency,
        original_amount_minor=None,
        merchant=None,
        category="其他",
        note="",
        source=source,
        image_path=saved_file.relative_path,
        thumbnail_path=None,
        image_hash=saved_file.image_hash,
        image_perceptual_hash=saved_file.image_perceptual_hash,
        raw_text="",
        confidence=None,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    refresh_legacy_expense_time(db, expense)
    db.add(expense)
    db.flush()
    mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    db.flush()
    return expense


def _find_manual_expense_by_key(db: Session, tenant_id: str, key: str) -> Expense | None:
    return db.scalar(ledger_scoped_select(Expense, tenant_id).where(Expense.draft_idempotency_key == key))


def _insert_manual_expense(
    db: Session,
    payload: ExpenseManualCreateRequest,
    tenant_id: str,
    *,
    draft_idempotency_key: str,
    draft_request_fingerprint: str,
    actor_account_id: int,
    actor_device_id: int,
) -> Expense:
    resolve_write_capability(db)
    home = payload.home_currency_code
    if home is None:
        has_original_money = (payload.original_currency is not None or payload.original_currency_code is not None) and (
            payload.original_amount is not None or payload.original_amount_minor is not None
        )
        if not has_original_money:
            raise AppError("manual_currency_context_required", "这笔旧草稿缺少币种依据，尚未保存。请先核对输入与已有流水。", status_code=422)
        # The legacy wire promised original payment money only. Its first accepted
        # home projection remains unchanged; new producers capture both currencies.
        home = require_runtime_home_currency_code(db)
    now = now_utc()
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        merchant=_clean_optional_text(payload.merchant),
        category=_clean_category(payload.category),
        note=_clean_text(payload.note),
        source="手动记账",
        image_path=None,
        thumbnail_path=None,
        image_hash=None,
        raw_text="",
        confidence=None,
        status="confirmed",
        expense_time=ensure_utc(payload.spent_at or payload.expense_time) or now,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
        tags=normalize_tags(payload.tags),
        value_score=payload.value_score,
        regret_score=payload.regret_score,
        draft_idempotency_key=draft_idempotency_key,
        draft_request_fingerprint=draft_request_fingerprint,
    )
    apply_expense_time_input(db, expense, payload, creating=True)
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        home_currency_code=home,
        expense=expense,
        payload=payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    if expense.amount_cents is None and expense.original_amount_minor is None:
        raise AppError("amount_required", status_code=400)
    if _expense_has_pending_fx(expense):
        expense.status = "pending"
        expense.confirmed_at = None
    if expense.category == "其他":
        classify_expense(db, expense)
    _materialize_category_preference(db, expense)
    db.add(expense)
    db.flush()
    sync_expense_tags(db, expense)
    mark_duplicate_status(db, expense)
    publish_expense_funding(db, expense=expense, parts=payload.funding, actor_account_id=actor_account_id)
    if expense.status == "confirmed":
        record_confirmation_revision(
            db,
            expense,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )
    db.flush()
    db.refresh(expense)
    return expense


def create_manual_expense(db: Session, payload: ExpenseManualCreateRequest, auth: AuthContext, *, commit: bool = True) -> ExpenseResponse:
    """Accept the original manual request and its typed response in one transaction."""
    from app.services.pending_fx_task_service import prepare_pending_expense_fx, submit_pending_expense_fx
    lock_and_revalidate_mutation_actor(
        db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id,
    )
    permission_service.require_write_expense(auth)
    tenant_id = auth.tenant_id
    key = local_ref_storage_key(auth.device_id, payload.client_ref)
    fingerprint = _manual_request_fingerprint(payload)
    try:
        claim = claim_idempotency_key(db, tenant_id=tenant_id,
            idempotency_key=_manual_receipt_key(auth.device_id, payload.client_ref),
            operation="create_manual_expense", request_fingerprint=fingerprint, target_type="expense")
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return _manual_receipt(claim.row)
        existing = _find_manual_expense_by_key(db, tenant_id, key)
        if existing is not None:
            if existing.draft_request_fingerprint != fingerprint:
                raise AppError("idempotency_key_reused", status_code=422)
            raise _manual_review_error(existing.id)
        validate_currency_payload_money_command(payload, amount_was_explicit=payload.amount_cents is not None)
        expense = _insert_manual_expense(db, payload, tenant_id, draft_idempotency_key=key,
            draft_request_fingerprint=fingerprint, actor_account_id=auth.account_id, actor_device_id=auth.device_id)
        fx_task = prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id)
        receipt = expense_to_response(db, tenant_id=tenant_id, expense=expense)
        mark_idempotency_succeeded(db, claim.row, resource_type="expense", resource_id=str(receipt.id),
            response_body=receipt.model_dump(mode="json"))
        if commit:
            db.commit()
        if fx_task is not None and commit:
            submit_pending_expense_fx(db, fx_task)
        return receipt
    except Exception:
        db.rollback()
        raise


def create_notification_draft(db: Session, payload: NotificationDraftCreateRequest, auth: AuthContext) -> Expense:
    from app.services.payment_capture_service import capture_legacy_expense

    return capture_legacy_expense(db, payload, auth)
