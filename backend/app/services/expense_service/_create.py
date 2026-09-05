"""Create-side flows: upload-driven pending, manual entry, notification draft."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import ExpenseManualCreateRequest, NotificationDraftCreateRequest
from app.services import permission_service
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.classify_service import classify_expense
from app.services.currency_binding_service import (
    assert_currency_binding_consistent,
    resolve_write_capability,
)
from app.services.currency_common import home_currency_code
from app.services.duplicate_service import mark_duplicate_status
from app.services.exchange_rate_service import (
    apply_currency_payload,
    validate_currency_payload_money_command,
)
from app.services.expense_query import local_ref_storage_key
from app.services.expense_revision_service import record_confirmation_revision
from app.services.expense_service._helpers import (
    NOTIFICATION_DRAFT_SOURCE_LABELS,
    NOTIFICATION_DRAFT_SOURCE_PREFIX,
    _clean_category,
    _clean_notification_source,
    _clean_optional_text,
    _clean_text,
    _expense_has_pending_fx,
    _notification_draft_fields,
    _notification_draft_key,
)
from app.services.file_service import SavedUpload
from app.services.idempotency import fingerprint_request
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
    frozen_home_currency = home_currency_code()
    # ADR-0061 C02 桥接门（PR#255 R9）：pending 行即按 env 盖章成持久事实，漂移时
    # 不得放行（与 freeze_home_amount / apply_currency_payload 同一防线）。
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
    db.add(expense)
    db.flush()
    mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    db.flush()
    return expense


def _manual_request_fingerprint(payload: ExpenseManualCreateRequest) -> str:
    """sha256 of the user-supplied manual-create body (issue #65 slice 1).

    Computed from the REQUEST as sent — never from the stored row — so the server's
    own mutations (auto-classify of ``category``, the ``expense_time`` → ``now``
    default, FX rate-derived ``amount_cents``) can't make a faithful replay look like
    a different request. ``client_ref`` is excluded: it IS the key, not part of the
    intent it guards.
    """
    body = payload.model_dump(mode="json", exclude_unset=True, exclude={"client_ref"})
    return fingerprint_request(
        operation="create_manual_expense",
        target_id=None,
        body=body,
        expected_row_version=None,
    )


def _find_manual_expense_by_key(db: Session, tenant_id: str, key: str) -> Expense | None:
    return db.scalar(ledger_scoped_select(Expense, tenant_id).where(Expense.draft_idempotency_key == key))


def _resolve_existing_manual_create(existing: Expense, fingerprint: str) -> Expense:
    """A row already owns this ``(device_id, client_ref)`` key: idempotent HIT iff the
    request fingerprint matches, else the ref was reused for a different expense."""
    if existing.draft_request_fingerprint != fingerprint:
        raise AppError("idempotency_key_reused", status_code=422)
    return existing


def _insert_manual_expense(
    db: Session,
    payload: ExpenseManualCreateRequest,
    tenant_id: str,
    *,
    draft_idempotency_key: str | None,
    draft_request_fingerprint: str | None,
    actor_account_id: int,
    actor_device_id: int,
) -> Expense:
    resolve_write_capability(db)
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
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
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
    if expense.status == "confirmed":
        record_confirmation_revision(
            db,
            expense,
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
        )
    db.commit()
    db.refresh(expense)
    return expense


def create_manual_expense(db: Session, payload: ExpenseManualCreateRequest, auth: AuthContext) -> Expense:
    lock_and_revalidate_mutation_actor(
        db, auth, actor_account_id=auth.account_id, ledger_id=auth.ledger_id,
    )
    permission_service.require_write_expense(auth)
    validate_currency_payload_money_command(
        payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    tenant_id = auth.tenant_id
    if not payload.client_ref:
        # No client-supplied ref (absent, or empty-string from a client bug) — no
        # dedup; every call is a fresh row. Unchanged pre-#65 behavior. Treating ""
        # as "no ref" (not as the key "{device_id}:") avoids both a 422 on a real
        # expense and silently collapsing distinct creates into one.
        return _insert_manual_expense(
            db,
            payload,
            tenant_id,
            draft_idempotency_key=None,
            draft_request_fingerprint=None,
            actor_account_id=auth.account_id,
            actor_device_id=auth.device_id,
        )

    # Issue #65 slice 1: device-scoped idempotent create. The composite key lives in
    # the expense's own ``draft_idempotency_key`` (unique per tenant) so slice 3 can
    # later resolve a ``local:{client_ref}`` mutation by it; the device prefix is built
    # server-side from the authenticated token, never trusted from the body.
    key = local_ref_storage_key(auth.device_id, payload.client_ref)
    fingerprint = _manual_request_fingerprint(payload)
    existing = _find_manual_expense_by_key(db, tenant_id, key)
    if existing is not None:
        return _resolve_existing_manual_create(existing, fingerprint)
    try:
        return _insert_manual_expense(
            db,
            payload,
            tenant_id,
            draft_idempotency_key=key,
            draft_request_fingerprint=fingerprint,
            actor_account_id=auth.account_id,
            actor_device_id=auth.device_id,
        )
    except IntegrityError:
        # A concurrent request won the (tenant_id, draft_idempotency_key) unique race
        # between our lookup and flush — re-read and treat it as the canonical row.
        db.rollback()
        existing = _find_manual_expense_by_key(db, tenant_id, key)
        if existing is not None:
            return _resolve_existing_manual_create(existing, fingerprint)
        raise


def _guard_notification_capture_currency(payload: NotificationDraftCreateRequest) -> None:
    """PR#255 R11 条件门：非 CNY 安装拒绝无 original 字段的通知捕获。

    Android 通知解析器按 CNY 分声明 amount_cents（PaymentNotificationParser 无 FX 路径，
    与 repayment 草稿同洞）——非 CNY 安装把该整数按 home minor 盖章即 100×。仅当币种
    与金额字段**成对完整**（R12-E：仅其一的残缺 FX 载荷按无 original 处理，该路径不为
    部分 FX 设计）才视为显式 FX 放行；否则非 CNY 安装整体拒绝。跨币种契约挂账 D9。
    """
    home_currency = home_currency_code()
    # R12-E 硬化：只有币种+金额**成对完整**才算显式 FX —— 仅其一的残缺 FX 载荷按无
    # original 处理（该路径不为部分 FX 设计：金额缺失会回落到 None 行值，汇率/金额
    # 语义不可判定）。CNY 下门不触发，行为与之前一致。
    has_original_money = (payload.original_currency is not None or payload.original_currency_code is not None) and (
        payload.original_amount is not None or payload.original_amount_minor is not None
    )
    if home_currency != DEFAULT_HOME_CURRENCY_CODE and not has_original_money:
        raise AppError("notification_draft_currency_unsupported", status_code=422)


def create_notification_draft(
    db: Session,
    payload: NotificationDraftCreateRequest,
    tenant_id: str,
) -> Expense:
    validate_currency_payload_money_command(
        payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    now = now_utc()
    source = _clean_notification_source(payload.source)
    _guard_notification_capture_currency(payload)
    idempotency_key = _notification_draft_key(
        source=source,
        merchant=payload.merchant,
        amount_cents=payload.amount_cents,
        original_currency=payload.original_currency or payload.original_currency_code,
        original_amount=payload.original_amount or payload.original_amount_minor,
        expense_time=payload.spent_at or payload.expense_time,
        now=now,
        notification_key=payload.notification_key,
    )
    existing = db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.draft_idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing

    resolve_write_capability(db)
    source_label = NOTIFICATION_DRAFT_SOURCE_LABELS[source]
    expense = Expense(
        tenant_id=tenant_id,
        amount_cents=payload.amount_cents,
        merchant=_clean_optional_text(payload.merchant),
        category=_clean_category(payload.category),
        note="",
        source=f"{NOTIFICATION_DRAFT_SOURCE_PREFIX}{source_label}",
        image_path=None,
        thumbnail_path=None,
        image_hash=None,
        raw_text="",
        confidence=None,
        ocr_draft_fields=_notification_draft_fields(payload),
        draft_idempotency_key=idempotency_key,
        status="pending",
        expense_time=ensure_utc(payload.spent_at or payload.expense_time)
        if (payload.spent_at or payload.expense_time)
        else None,
        created_at=now,
        updated_at=now,
    )
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    db.add(expense)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.draft_idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        raise
    if expense.category == "其他":
        classify_expense(db, expense)
    _materialize_category_preference(db, expense)
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
        mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    db.commit()
    db.refresh(expense)
    return expense
