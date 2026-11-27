"""Explicit correction command for already-confirmed Expense facts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, ExpenseRevision
from app.schemas import (
    ExpenseCorrectionRequest,
    ExpenseItemReplaceRequest,
    ExpenseSplitReplaceRequest,
    ExpenseUpdateRequest,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_correction_batch import batch_update_confirmed_expenses
from app.services.expense_correction_reversal import (
    validate_expense_offsets_for_correction as _validate_expense_offsets_for_correction,
)
from app.services.expense_revision_service import (
    PreparedCorrectionRevision,
    correction_funding_account_ids,
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.expense_service._field_mutation import apply_expense_fields_to_claimed_row
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
    record_unmatched_saves(
        db,
        expense=expense,
        before=readings_before,
        actor_account_id=actor_account_id,
        recorded_fields=fields_recorded,
    )
    record_original_text_feedback(
        db,
        expense=expense,
        annotations=payload.original_text_feedback,
        actor_account_id=actor_account_id,
    )
    if payload.category is not None:
        record_category_choice(
            db,
            expense=expense,
            previous_category=category_before,
            previous_merchant=merchant_before,
            actor_account_id=actor_account_id,
            choice=payload.category_choice,
            decision_public_id=payload.category_decision_public_id,
        )
    expense.updated_at = now


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
