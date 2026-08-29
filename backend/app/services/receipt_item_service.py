from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseItem
from app.money_contract import (
    MoneySign,
    ensure_optional_money_minor,
    projection_sum_to_int,
    projection_values_sum_to_int,
)
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseItemResponse,
    ExpenseItemsResponse,
)
from app.services.category_service import normalize_category
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_query import get_expense, resolve_expense
from app.services.expense_revision_service import (
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.receipt_parse_service import ParsedReceiptItem
from app.services.time_service import now_utc

# tolerance for rounding / floating drift between expense.amount_cents and
# sum(items.amount_cents); 0 = strict integer equality (cents).
_ITEMS_SUM_TOLERANCE_CENTS = 0
_EXPENSE_ITEM_KINDS = frozenset({"product", "discount", "tax", "service_fee"})
_MISMATCH_ACKNOWLEDGEMENT_REASON = "原小票如此：明细合计与账单金额存在差异"


def validate_expense_item_money_command(
    items: Sequence[object],
) -> None:
    """Validate item money before any expense lookup or mutation."""

    for item in items:
        _validate_item_amounts(
            kind=getattr(item, "kind", None),
            unit_price_cents=getattr(item, "unit_price_cents", None),
            amount_cents=getattr(item, "amount_cents", None),
        )


def _validate_item_amounts(
    *,
    kind: object,
    unit_price_cents: object | None,
    amount_cents: object | None,
) -> tuple[int | None, int | None]:
    unit_price = ensure_optional_money_minor(
        unit_price_cents,
        sign=MoneySign.NONNEGATIVE,
        label="expense_item.unit_price_cents",
    )
    amount = ensure_optional_money_minor(
        amount_cents,
        sign=MoneySign.SIGNED,
        label="expense_item.amount_cents",
    )
    if type(kind) is not str or kind not in _EXPENSE_ITEM_KINDS:
        raise AppError("invalid_request", status_code=422)
    if amount is not None and ((kind == "discount" and amount > 0) or (kind != "discount" and amount < 0)):
        raise AppError("amount_invalid", status_code=422)
    return unit_price, amount


def list_expense_items(db: Session, expense_id: int, tenant_id: str) -> ExpenseItemsResponse:
    expense = get_expense(db, expense_id, tenant_id)
    return _build_response(db, expense)


def replace_expense_items(
    db: Session,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseItemReplaceRequest,
    *,
    commit: bool = True,
) -> ExpenseItemsResponse:
    validate_expense_item_money_command(payload.items)
    resolve_write_capability(db)
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"updated_at": now},
        extra_where=(Expense.status == "pending",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        current = resolve_expense(db, tenant_id, expense_id)
        if current is None or current.status == "rejected":
            raise AppError("expense_not_found", status_code=404)
        if current.status == "confirmed":
            raise AppError("expense_correction_required", status_code=409)
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)

    apply_expense_items_to_claimed_row(
        db,
        expense=expense,
        payload=payload,
        now=now,
    )
    if commit:
        db.commit()
        db.refresh(expense)
    else:
        db.flush()
    return _build_response(db, expense)


def apply_expense_items_to_claimed_row(
    db: Session,
    *,
    expense: Expense,
    payload: ExpenseItemReplaceRequest,
    now,
) -> None:
    """Replace item facts after the caller has acquired the parent CAS."""

    validate_expense_item_money_command(payload.items)
    existing = list(
        db.scalars(ledger_scoped_select(ExpenseItem, expense.tenant_id).where(ExpenseItem.expense_id == expense.id))
    )
    for item in existing:
        db.delete(item)
    db.flush()
    for position, request_item in enumerate(payload.items):
        db.add(_new_item(expense, position, request_item, now=now))
    db.flush()
    recompute_items_sum_status(db, expense)


def replace_ocr_draft_items(
    db: Session,
    expense: Expense,
    parsed_items: tuple[ParsedReceiptItem, ...],
) -> None:
    if expense.status != "pending":
        return

    validate_expense_item_money_command(parsed_items)
    resolve_write_capability(db)
    existing = list(
        db.scalars(ledger_scoped_select(ExpenseItem, expense.tenant_id).where(ExpenseItem.expense_id == expense.id))
    )
    if any(not item.is_ocr_draft for item in existing):
        return

    for item in existing:
        db.delete(item)
    db.flush()

    now = now_utc()
    for position, parsed_item in enumerate(parsed_items):
        db.add(_new_ocr_draft_item(expense, position, parsed_item, now=now))
    expense.updated_at = now
    db.flush()
    recompute_items_sum_status(db, expense)


def acknowledge_items_sum_mismatch(
    db: Session,
    expense_id: int,
    tenant_id: str,
    *,
    expected_row_version: int,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    idempotency_key: str | None = None,
    commit: bool = True,
) -> ExpenseItemsResponse:
    """User-confirmed "原小票如此" path: mismatch_known → mismatch_acknowledged.

    ADR-0038 PR-2e atomic optimistic-concurrency claim:
    ``UPDATE expenses SET items_sum_status='mismatch_acknowledged',
    updated_at=now WHERE id, tenant_id, items_sum_status='mismatch_known',
    updated_at=expected``. ``rowcount == 0`` disambiguates:

    - row not visible / vanished → 404 ``expense_not_found``
    - status != ``mismatch_known`` → 409 ``items_sum_not_in_mismatch``
      (existing UX preserved — UI never offers this button unless
      ``mismatch_known``)
    - else → 409 ``state_conflict`` (peer edited amount/items between
      the user's read and this acknowledge)
    """
    resolve_write_capability(db)
    current = get_expense(db, expense_id, tenant_id)
    prepared = prepare_correction_revision(db, current)

    now = now_utc()
    set_values: dict[str, object] = {
        "items_sum_status": "mismatch_acknowledged",
        "updated_at": now,
    }
    if prepared is not None:
        set_values["fact_revision"] = Expense.fact_revision + 1
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values=set_values,
        extra_where=(Expense.items_sum_status == "mismatch_known",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = resolve_expense(db, tenant_id, expense_id)
        if current is None:
            raise AppError("expense_not_found", status_code=404)
        if current.items_sum_status != "mismatch_known":
            raise AppError(
                "items_sum_not_in_mismatch",
                "当前账单不存在可确认的金额差异。",
                status_code=409,
            )
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    record_prepared_correction_revision(
        db,
        expense,
        prepared,
        reason=_MISMATCH_ACKNOWLEDGEMENT_REASON,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=idempotency_key,
    )
    if commit:
        db.commit()
        db.refresh(expense)
    else:
        db.flush()
    return _build_response(db, expense)


def recompute_items_sum_status(db: Session, expense: Expense) -> None:
    """Recompute items_sum_status from current items + expense.amount_cents.

    Caller is responsible for db.flush() / db.commit() after this; this
    function only mutates expense.items_sum_status in-memory.

    Preserves ``mismatch_acknowledged`` when the same mismatch persists —
    user already said "原小票如此", don't bounce them back to warning.
    """
    items_sum = _compute_items_sum_cents(db, expense)
    prev_status = expense.items_sum_status

    if items_sum is None:
        expense.items_sum_status = "no_items"
        return

    if expense.amount_cents is None:
        expense.items_sum_status = "matched"
        return

    delta = abs(
        projection_sum_to_int(
            expense.amount_cents - items_sum,
            label="expense_items.mismatch",
        )
    )
    if delta <= _ITEMS_SUM_TOLERANCE_CENTS:
        expense.items_sum_status = "matched"
        return

    # 已 acknowledged 的不要倒回 mismatch_known — 用户确认过的差异保留。
    if prev_status == "mismatch_acknowledged":
        return
    expense.items_sum_status = "mismatch_known"


def _compute_items_sum_cents(db: Session, expense: Expense) -> int | None:
    items = list(
        db.scalars(ledger_scoped_select(ExpenseItem, expense.tenant_id).where(ExpenseItem.expense_id == expense.id))
    )
    if not items:
        return None
    amounts = [item.amount_cents for item in items if item.amount_cents is not None]
    if not amounts:
        return None
    return projection_values_sum_to_int(
        amounts,
        label="expense_items.total",
    )


def _new_item(
    expense: Expense,
    position: int,
    request_item: ExpenseItemRequest,
    *,
    now,
) -> ExpenseItem:
    unit_price_cents, amount_cents = _validate_item_amounts(
        kind=request_item.kind,
        unit_price_cents=request_item.unit_price_cents,
        amount_cents=request_item.amount_cents,
    )
    return ExpenseItem(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        position=position,
        kind=request_item.kind,
        name=_clean_required_text(request_item.name),
        quantity_text=_clean_optional_text(request_item.quantity_text),
        unit_price_cents=unit_price_cents,
        amount_cents=amount_cents,
        category=normalize_category(request_item.category),
        raw_text=_clean_optional_text(request_item.raw_text),
        confidence=request_item.confidence,
        is_ocr_draft=False,
        created_at=now,
        updated_at=now,
    )


def _new_ocr_draft_item(
    expense: Expense,
    position: int,
    parsed_item: ParsedReceiptItem,
    *,
    now,
) -> ExpenseItem:
    # ParsedReceiptItem.kind 是 PR-2 范围；目前 OCR 草稿默认 product。
    kind = getattr(parsed_item, "kind", "product")
    unit_price_cents, amount_cents = _validate_item_amounts(
        kind=kind,
        unit_price_cents=parsed_item.unit_price_cents,
        amount_cents=parsed_item.amount_cents,
    )
    return ExpenseItem(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        position=position,
        kind=kind,
        name=_clean_required_text(parsed_item.name),
        quantity_text=_clean_optional_text(parsed_item.quantity_text),
        unit_price_cents=unit_price_cents,
        amount_cents=amount_cents,
        category=normalize_category(parsed_item.category),
        raw_text=_clean_optional_text(parsed_item.raw_text),
        confidence=parsed_item.confidence,
        is_ocr_draft=True,
        created_at=now,
        updated_at=now,
    )


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_required_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _build_response(db: Session, expense: Expense) -> ExpenseItemsResponse:
    items = list(
        db.scalars(
            ledger_scoped_select(ExpenseItem, expense.tenant_id)
            .where(ExpenseItem.expense_id == expense.id)
            .order_by(ExpenseItem.position.asc(), ExpenseItem.id.asc())
        )
    )
    amounts = [item.amount_cents for item in items if item.amount_cents is not None]
    items_total = (
        projection_values_sum_to_int(
            amounts,
            label="expense_items.response_total",
        )
        if amounts
        else None
    )
    mismatch = (
        projection_sum_to_int(
            expense.amount_cents - items_total,
            label="expense_items.response_mismatch",
        )
        if expense.amount_cents is not None and items_total is not None
        else None
    )
    return ExpenseItemsResponse(
        expense_id=expense.id,
        parent_amount_cents=expense.amount_cents,
        items_total_amount_cents=items_total,
        mismatch_cents=mismatch,
        items_sum_status=expense.items_sum_status,
        row_version=expense.row_version,
        items=[ExpenseItemResponse.model_validate(item) for item in items],
    )
