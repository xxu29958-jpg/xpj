"""Stage notification evidence inside its caller's transaction, without capture orchestration."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.ledger_scope import ledger_scoped_select
from app.models import Expense
from app.schemas import NotificationDraftCreateRequest
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.currency_binding_service import require_runtime_home_currency_code, resolve_write_capability
from app.services.duplicate_service import mark_duplicate_status
from app.services.exchange_rate_service import apply_currency_payload, validate_currency_payload_money_command
from app.services.expense_accounting_time_service import apply_expense_time_input
from app.services.expense_service._helpers import (
    NOTIFICATION_DRAFT_SOURCE_LABELS,
    NOTIFICATION_DRAFT_SOURCE_PREFIX,
    _clean_category,
    _clean_notification_source,
    _clean_optional_text,
    _notification_draft_fields,
    _notification_draft_key,
)
from app.services.rule_service import classify_expense
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext


def _guard_notification_capture_currency(payload: NotificationDraftCreateRequest, *, home_currency: str) -> None:
    """PR#255 R11 条件门：非 CNY 安装拒绝无 original 字段的通知捕获。

    Android 通知解析器按 CNY 分声明 amount_cents（PaymentNotificationParser 无 FX 路径，
    与 repayment 草稿同洞）——非 CNY 安装把该整数按 home minor 盖章即 100×。仅当币种
    与金额字段**成对完整**（R12-E：仅其一的残缺 FX 载荷按无 original 处理，该路径不为
    部分 FX 设计）才视为显式 FX 放行；否则非 CNY 安装整体拒绝。跨币种契约挂账 D9。
    """
    # R12-E 硬化：只有币种+金额**成对完整**才算显式 FX —— 仅其一的残缺 FX 载荷按无
    # original 处理（该路径不为部分 FX 设计：金额缺失会回落到 None 行值，汇率/金额
    # 语义不可判定）。CNY 下门不触发，行为与之前一致。
    has_original_money = (payload.original_currency is not None or payload.original_currency_code is not None) and (
        payload.original_amount is not None or payload.original_amount_minor is not None
    )
    if home_currency != DEFAULT_HOME_CURRENCY_CODE and not has_original_money:
        raise AppError("notification_draft_currency_unsupported", status_code=422)


def stage_notification_draft(
    db: Session,
    payload: NotificationDraftCreateRequest,
    auth: AuthContext,
) -> tuple[Expense, object | None]:
    from app.services.pending_fx_task_service import prepare_pending_expense_fx

    tenant_id = auth.tenant_id
    validate_currency_payload_money_command(
        payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    now = now_utc()
    source = _clean_notification_source(payload.source)
    _guard_notification_capture_currency(payload, home_currency=require_runtime_home_currency_code(db))
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
        return existing, None

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
    apply_expense_time_input(db, expense, payload, creating=True)
    apply_currency_payload(
        db,
        tenant_id=tenant_id,
        home_currency_code=require_runtime_home_currency_code(db),
        expense=expense,
        payload=payload,
        amount_was_explicit=payload.amount_cents is not None,
    )
    try:
        with db.begin_nested():
            db.add(expense)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(Expense.draft_idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing, None
        raise
    if expense.category == "其他":
        classify_expense(db, expense)
    ensure_category_preference_for_name(db, tenant_id=expense.tenant_id, name=expense.category)
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
        mark_duplicate_status(db, expense)
    expense.updated_at = now_utc()
    fx_task = prepare_pending_expense_fx(db, expense=expense,
        initiator_account_id=auth.account_id, initiator_device_id=auth.device_id)
    return expense, fx_task
