"""Explicit correction command for already-confirmed Expense facts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.errors import AppError
from app.models import (
    AccountMovement,
    ApiIdempotencyKey,
    Expense,
    ExpenseFunding,
    ExpenseOffsetFact,
    ExpenseRevision,
    FinancialAccount,
)
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseCorrectionRequest,
    ExpenseItemReplaceRequest,
    ExpenseSplitReplaceRequest,
    ExpenseUpdateRequest,
)
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_revision_service import (
    PreparedCorrectionRevision,
    correction_funding_account_ids,
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.expense_service._field_mutation import apply_expense_fields_to_claimed_row
from app.services.expense_service._helpers import _clean_category
from app.services.expense_service._query import get_expense
from app.services.expense_split_service import (
    apply_expense_splits_to_claimed_row,
    validate_current_expense_split_allocation,
)
from app.services.goal_debt_repayment_achievement import stage_debt_goal_achievements
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.original_text_feedback_service import record_original_text_feedback
from app.services.pending_suggestion_service import record_category_choice
from app.services.receipt_item_service import apply_expense_items_to_claimed_row
from app.services.recognition_field_service import record_field_choices
from app.services.recognition_miss_service import record_unmatched_saves, saved_readings
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import now_utc

__all__ = [
    "CorrectionCommandClaim",
    "batch_update_confirmed_expenses",
    "correct_expense",
    "correction_idempotency_body",
    "claim_correction_command",
    "complete_correction_command",
]


@dataclass(frozen=True)
class CorrectionCommandClaim:
    """Opaque service-owned handle for a claimed correction command."""

    record: ApiIdempotencyKey


def correction_idempotency_body(
    payload: ExpenseCorrectionRequest,
    *,
    actor_account_id: int,
) -> dict[str, object]:
    """Bind a correction replay fingerprint to the accountable writer.

    The idempotency claim is tenant-scoped and a replay returns before the
    correction service runs again. Including the actor prevents a second writer
    in the same ledger from replaying another writer's intent and revision.
    """

    return {
        **payload.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"expected_row_version"},
        ),
        "actor_account_id": actor_account_id,
    }


def claim_correction_command(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    expected_row_version: int,
    idempotency_key: str | None,
    intent_body: dict[str, object],
) -> CorrectionCommandClaim | None:
    """Unique claim owner shared by API and Web correction consumers."""

    record = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="correct_expense",
        target_id=str(expense_id),
        body=intent_body,
        expected_row_version=expected_row_version,
    )
    return CorrectionCommandClaim(record) if record is not None else None


def complete_correction_command(
    db: Session,
    *,
    claim: CorrectionCommandClaim,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseCorrectionRequest,
    actor_account_id: int,
    actor_device_id: int | None,
    idempotency_key: str,
) -> tuple[Expense, ExpenseRevision]:
    """Apply, publish revision, and mark the claim in one transaction."""

    expense, revision = correct_expense(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        payload=payload,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim.record,
        resource_type="expense",
        resource_id=str(expense_id),
    )
    stage_debt_goal_achievements(db, account_ids=correction_funding_account_ids(db, revision))
    db.commit()
    db.refresh(expense)
    db.refresh(revision)
    return expense, revision


@dataclass(frozen=True)
class _BatchCorrectionIntent:
    expense_ids: list[int]
    expected_by_id: dict[int, int]
    category_provided: bool
    category: str | None
    tags_provided: bool
    tags: list[str] | None


def _batch_correction_intent(
    payload: ConfirmedExpenseBatchUpdateRequest,
) -> _BatchCorrectionIntent:
    expense_ids = list(dict.fromkeys(payload.expense_ids))
    expected_by_id = payload.expected_row_version_by_id
    if set(expected_by_id) != set(expense_ids):
        raise AppError("invalid_request", status_code=422)

    category_provided = payload.category is not None
    tags_provided = payload.tags is not None
    if not category_provided and not tags_provided:
        raise AppError("invalid_request", status_code=422)
    category = payload.category.strip() if category_provided else None
    if category_provided and not category:
        raise AppError("invalid_request", status_code=422)
    return _BatchCorrectionIntent(
        expense_ids=expense_ids,
        expected_by_id=expected_by_id,
        category_provided=category_provided,
        category=category,
        tags_provided=tags_provided,
        tags=normalize_tags(payload.tags) if tags_provided else None,
    )


def _apply_one_batch_correction(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    expected_row_version: int,
    intent: _BatchCorrectionIntent,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> bool:
    target_category = _clean_category(intent.category) if intent.category_provided else expense.category
    target_tags = intent.tags if intent.tags_provided else expense.tags
    if target_category == expense.category and target_tags == expense.tags:
        matched_id = db.scalar(
            select(Expense.id)
            .where(Expense.id == expense.id)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.row_version == expected_row_version)
            .with_for_update(read=True)
        )
        if matched_id is None:
            db.rollback()
            raise AppError("state_conflict", status_code=409)
        return False

    prepared = prepare_correction_revision(db, expense)
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"updated_at": now, "fact_revision": Expense.fact_revision + 1},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    if intent.category_provided:
        expense.category = target_category
        ensure_category_preference_for_name(db, tenant_id=tenant_id, name=target_category)
    if intent.tags_provided:
        expense.tags = intent.tags
        sync_expense_tags(db, expense)
    expense.updated_at = now
    db.flush()
    db.refresh(expense)
    record_prepared_correction_revision(
        db,
        expense,
        prepared,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )
    return True


def _claim_batch_idempotency(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
    actor_account_id: int | None,
    idempotency_key: str | None,
) -> tuple[ApiIdempotencyKey | None, ConfirmedExpenseBatchUpdateResponse | None]:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="correct_confirmed_expense_batch",
        target_id="confirmed",
        target_type="expense_batch",
        body={
            **payload.model_dump(mode="json"),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=None,
    )
    if claim is not None:
        return claim, None
    if idempotency_key is None:  # narrowed by claim_idempotent_request
        raise AppError("server_error", status_code=500)
    stored = db.scalar(
        select(ApiIdempotencyKey)
        .where(ApiIdempotencyKey.tenant_id == tenant_id)
        .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
    )
    if stored is None or stored.response_body is None:
        raise AppError("server_error", status_code=500)
    return None, ConfirmedExpenseBatchUpdateResponse.model_validate(stored.response_body)


def batch_update_confirmed_expenses(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    idempotency_key: str | None = None,
) -> ConfirmedExpenseBatchUpdateResponse:
    """Apply one reasoned correction intent to each eligible confirmed fact."""

    intent = _batch_correction_intent(payload)
    claim, replay = _claim_batch_idempotency(
        db,
        tenant_id=tenant_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
    )
    if replay is not None:
        return replay
    if claim is None:
        raise AssertionError("new batch command must hold an idempotency claim")

    authorize_currency_metadata_write(db)
    rows = list(
        db.scalars(select(Expense).where(Expense.tenant_id == tenant_id).where(Expense.id.in_(intent.expense_ids)))
    )
    rows_by_id = {row.id: row for row in rows}

    updated_count = 0
    skipped_not_found = 0
    skipped_not_confirmed = 0
    # Web and Android submit different selection orders; all row locks must
    # still be acquired in one global order for overlapping batches.
    for expense_id in sorted(intent.expense_ids):
        expense = rows_by_id.get(expense_id)
        if expense is None:
            skipped_not_found += 1
            continue
        if expense.status != "confirmed":
            skipped_not_confirmed += 1
            continue
        updated_count += int(
            _apply_one_batch_correction(
                db,
                expense=expense,
                tenant_id=tenant_id,
                expected_row_version=intent.expected_by_id[expense_id],
                intent=intent,
                reason=payload.reason,
                actor_account_id=actor_account_id,
                actor_device_id=actor_device_id,
            )
        )

    result = ConfirmedExpenseBatchUpdateResponse(
        requested_count=len(intent.expense_ids),
        updated_count=updated_count,
        skipped_not_found=skipped_not_found,
        skipped_not_confirmed=skipped_not_confirmed,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense_batch",
        resource_id="confirmed",
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result


def _claim_confirmed_correction(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    expected_row_version: int,
) -> tuple[Expense, PreparedCorrectionRevision, object]:
    current = get_expense(db, expense_id, tenant_id)
    _require_confirmed(current)
    prepared = prepare_correction_revision(db, current)
    if prepared is None:
        raise AssertionError("confirmed correction must capture a revision snapshot")
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"updated_at": now, "fact_revision": Expense.fact_revision + 1},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.expire_all()
        _require_confirmed(get_expense(db, expense_id, tenant_id))
        raise AppError("state_conflict", status_code=409)
    db.expire_all()
    return get_expense(db, expense_id, tenant_id), prepared, now


def _apply_correction_sections(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    payload: ExpenseCorrectionRequest,
    actor_account_id: int,
    now,
) -> None:
    from app.services.expense_funding_service import apply_funding_correction, funding_money_identity
    amount_before = expense.amount_cents
    before_money = funding_money_identity(expense)
    category_before, merchant_before = expense.category, expense.merchant
    readings_before = saved_readings(expense)
    scalar_payload = _scalar_payload(payload)
    if scalar_payload is not None:
        apply_expense_fields_to_claimed_row(
            db,
            expense=expense,
            tenant_id=tenant_id,
            payload=scalar_payload,
        )
    if payload.items is not None:
        apply_expense_items_to_claimed_row(
            db,
            expense=expense,
            payload=ExpenseItemReplaceRequest(
                expected_row_version=expense.row_version,
                items=payload.items,
            ),
            now=now,
        )
    if payload.splits is not None:
        apply_expense_splits_to_claimed_row(
            db,
            expense=expense,
            payload=ExpenseSplitReplaceRequest(
                expected_row_version=expense.row_version,
                splits=payload.splits,
            ),
            actor_account_id=actor_account_id,
            now=now,
        )
    if expense.amount_cents != amount_before or payload.splits is not None:
        validate_current_expense_split_allocation(db, expense=expense)
    restoring_legacy_reversal = _validate_expense_offsets_for_correction(
        db,
        expense=expense,
        before_money=before_money,
        funding_requested=payload.funding is not None,
    )
    if not restoring_legacy_reversal:
        apply_funding_correction(
            db,
            expense=expense,
            before_money=before_money,
            payload=payload,
            actor_account_id=actor_account_id,
        )
    fields_recorded = record_field_choices(
        db,
        expense=expense,
        choices=payload.recognition_field_choices,
        actor_account_id=actor_account_id,
    )
    record_unmatched_saves(db, expense=expense, before=readings_before, actor_account_id=actor_account_id,
        recorded_fields=fields_recorded)
    record_original_text_feedback(
        db,
        expense=expense,
        annotations=payload.original_text_feedback,
        actor_account_id=actor_account_id,
    )
    if payload.category is not None:
        record_category_choice(db, expense=expense, previous_category=category_before,
            previous_merchant=merchant_before, actor_account_id=actor_account_id,
            choice=payload.category_choice, decision_public_id=payload.category_decision_public_id)
    expense.updated_at = now


def _load_reversal_root_movements_and_fundings(
    db: Session,
    *,
    reversals: list[ExpenseOffsetFact],
) -> tuple[list[AccountMovement], list[ExpenseFunding]]:
    child = aliased(AccountMovement)
    reversal_rows = list(
        db.scalars(
            select(AccountMovement)
            .where(AccountMovement.offset_id.in_([offset.id for offset in reversals]))
            .where(
                ~exists(
                    select(child.id).where(child.reversal_of_id == AccountMovement.id)
                )
            )
        )
    )
    if not reversal_rows:
        return [], []
    account_ids = {row.account_id for row in reversal_rows}
    lineage = dict(
        db.execute(
            select(AccountMovement.id, AccountMovement.reversal_of_id).where(
                AccountMovement.account_id.in_(account_ids)
            )
        ).all()
    )
    root_ids: set[int] = set()
    for row in reversal_rows:
        root = row.id
        while lineage.get(root) is not None:
            root = lineage[root]
        root_ids.add(root)
    root_movements = list(
        db.scalars(select(AccountMovement).where(AccountMovement.id.in_(root_ids)))
    )
    restored_fundings = list(
        db.scalars(
            select(ExpenseFunding)
            .join(AccountMovement, AccountMovement.funding_id == ExpenseFunding.id)
            .where(AccountMovement.id.in_(root_ids))
        )
    )
    return root_movements, restored_fundings


def _load_active_fundings_excluding(
    db: Session,
    *,
    expense_id: int,
    excluded_ids: set[int],
) -> list[ExpenseFunding]:
    query = (
        select(ExpenseFunding)
        .where(ExpenseFunding.expense_id == expense_id)
        .where(ExpenseFunding.voided_at.is_(None))
    )
    if excluded_ids:
        query = query.where(ExpenseFunding.id.not_in(excluded_ids))
    return list(db.scalars(query))


def _load_opening_accounts(
    db: Session,
    fundings: tuple[ExpenseFunding, ...],
) -> list[FinancialAccount] | None:
    opening_account_ids = {
        funding.account_id for funding in fundings if funding.included_in_opening
    }
    if not opening_account_ids:
        return []
    opening_accounts = list(
        db.scalars(
            select(FinancialAccount).where(FinancialAccount.id.in_(opening_account_ids))
        )
    )
    if len(opening_accounts) != len(opening_account_ids):
        return None
    return opening_accounts


def _opening_dates_valid(opening_accounts: list[FinancialAccount], candidate_date) -> bool:
    return all(
        account.balance_known and candidate_date <= account.opening_date
        for account in opening_accounts
    )


def _evaluate_reversal_date_restoration(
    root_movements: list[AccountMovement],
    opening_accounts: list[FinancialAccount],
    *,
    before_date,
    after_date,
) -> tuple[bool, bool] | None:
    if root_movements:
        restorable_dates = {row.occurred_on for row in root_movements}
        if len(restorable_dates) != 1:
            return None
        restorable_date = next(iter(restorable_dates))
        before_invalid = before_date != restorable_date or not _opening_dates_valid(
            opening_accounts, before_date
        )
        after_valid = after_date == restorable_date and _opening_dates_valid(
            opening_accounts, after_date
        )
        return before_invalid, after_valid
    before_invalid = not _opening_dates_valid(opening_accounts, before_date)
    after_valid = _opening_dates_valid(opening_accounts, after_date) and (
        after_date == before_date or before_invalid
    )
    return before_invalid, after_valid


def _matches_legacy_reversal_restoration(
    expense: Expense,
    *,
    before_money: tuple[object, ...],
    restorable_currency: str,
    restorable_home: int,
    restorable_total: int,
    before_date_invalid: bool,
    after_date_valid: bool,
) -> bool:
    before_currency, before_original, before_home, _ = before_money
    before_amount = before_original if before_original is not None else before_home
    after_amount = (
        expense.original_amount_minor
        if expense.original_amount_minor is not None
        else expense.amount_cents
    )
    is_legacy_mismatch = (
        before_amount != restorable_total
        or before_currency != restorable_currency
        or before_home != restorable_home
        or before_date_invalid
    )
    return (
        is_legacy_mismatch
        and expense.original_currency_code == restorable_currency
        and after_amount == restorable_total
        and expense.amount_cents == restorable_home
        and after_date_valid
    )


def _restores_legacy_reversal_funding(
    db: Session,
    *,
    expense: Expense,
    before_money: tuple[object, ...],
    reversals: list[ExpenseOffsetFact],
) -> bool:
    root_movements, restored_fundings = _load_reversal_root_movements_and_fundings(
        db, reversals=reversals
    )
    existing_active = _load_active_fundings_excluding(
        db,
        expense_id=expense.id,
        excluded_ids={funding.id for funding in restored_fundings},
    )
    all_fundings = (*existing_active, *restored_fundings)
    if not all_fundings:
        return False
    restorable_currencies = {offset.original_currency_code for offset in reversals}
    restorable_homes = {offset.amount_cents for offset in reversals}
    if len(restorable_currencies) != 1 or len(restorable_homes) != 1:
        return False
    opening_accounts = _load_opening_accounts(db, all_fundings)
    if opening_accounts is None:
        return False
    date_check = _evaluate_reversal_date_restoration(
        root_movements,
        opening_accounts,
        before_date=before_money[3],
        after_date=expense.accounting_date,
    )
    if date_check is None:
        return False
    before_date_invalid, after_date_valid = date_check
    return _matches_legacy_reversal_restoration(
        expense,
        before_money=before_money,
        restorable_currency=next(iter(restorable_currencies)),
        restorable_home=next(iter(restorable_homes)),
        restorable_total=sum(funding.expense_amount_minor for funding in all_fundings),
        before_date_invalid=before_date_invalid,
        after_date_valid=after_date_valid,
    )


def _validate_refund_offsets_for_correction(
    expense: Expense,
    refund_offsets: list[ExpenseOffsetFact],
) -> None:
    from app.services.expense_offset_money import gross_original_minor

    refund_currencies = {offset.original_currency_code for offset in refund_offsets}
    if len(refund_currencies) != 1 or expense.original_currency_code != next(iter(refund_currencies)):
        raise AppError(
            "expense_refund_exists",
            "这笔账单已有生效退款，请先核对币种或撤销退款记录后再更正。",
            status_code=409,
        )
    active_refunded = sum(offset.original_amount_minor for offset in refund_offsets)
    if active_refunded > gross_original_minor(expense):
        raise AppError(
            "expense_refund_exceeds_remaining",
            "更正后的金额不能低于已生效的累计退款金额。",
            status_code=409,
        )


def _validate_expense_offsets_for_correction(
    db: Session,
    *,
    expense: Expense,
    before_money: tuple[object, ...],
    funding_requested: bool,
) -> bool:
    from app.services.expense_funding_service import funding_money_identity

    money_changed = before_money != funding_money_identity(expense)
    if not money_changed and not funding_requested:
        return False
    active_offsets = list(
        db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == expense.tenant_id)
            .where(ExpenseOffsetFact.expense_id == expense.id)
            .where(ExpenseOffsetFact.status == "active")
            .order_by(ExpenseOffsetFact.id)
            .with_for_update()
        )
    )
    if not active_offsets:
        return False
    reversals = [offset for offset in active_offsets if offset.kind == "reversal"]
    if reversals:
        if funding_requested or not _restores_legacy_reversal_funding(
            db,
            expense=expense,
            before_money=before_money,
            reversals=reversals,
        ):
            raise AppError(
                "expense_reversal_active",
                "这笔账单已经冲销，请先撤销冲销记录后再更正金额、币种或付款组成。",
                status_code=409,
            )
        return True
    if not money_changed:
        return False
    refund_offsets = [offset for offset in active_offsets if offset.kind != "reversal"]
    _validate_refund_offsets_for_correction(expense, refund_offsets)
    return False


def _scalar_payload(payload: ExpenseCorrectionRequest) -> ExpenseUpdateRequest | None:
    scalar_fields = payload.model_fields_set - {"reason", "items", "splits"}
    if scalar_fields == {"expected_row_version"}:
        return None
    return ExpenseUpdateRequest.model_validate(
        payload.model_dump(
            exclude_unset=True,
            exclude={"reason", "items", "splits"},
        )
    )


def _require_confirmed(expense: Expense) -> None:
    if expense.status == "confirmed":
        return
    if expense.status == "pending":
        raise AppError("expense_not_confirmed", status_code=409)
    raise AppError("expense_not_found", status_code=404)


def correct_expense(
    db: Session,
    *,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseCorrectionRequest,
    actor_account_id: int,
    actor_device_id: int | None,
    idempotency_key: str,
    commit: bool = True,
) -> tuple[Expense, ExpenseRevision]:
    """Correct one current projection and append exactly one revision atomically."""

    authorize_currency_metadata_write(db)
    expense, prepared, now = _claim_confirmed_correction(
        db,
        expense_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
    )
    _apply_correction_sections(
        db,
        expense=expense,
        tenant_id=tenant_id,
        payload=payload,
        actor_account_id=actor_account_id,
        now=now,
    )
    revision = record_prepared_correction_revision(
        db,
        expense,
        prepared,
        reason=payload.reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=idempotency_key,
    )
    if revision is None:
        raise AssertionError("confirmed correction must publish a revision")
    if commit:
        stage_debt_goal_achievements(db, account_ids=correction_funding_account_ids(db, revision))
        db.commit()
        db.refresh(expense)
        db.refresh(revision)
    return expense, revision
