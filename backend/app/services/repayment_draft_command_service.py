"""Replay-safe commands for resolving a captured repayment draft.

Both the JSON API and the browser form adapter call this module.  Keeping the
idempotency claim, actor-scoped fingerprint, OCC-backed confirm and commit in one
place prevents the two product surfaces from drifting into different business
semantics.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountMovement, ApiIdempotencyKey, Debt
from app.schemas import RepaymentDraftConfirmRequest, RepaymentDraftResponse
from app.services.debt_service import (
    confirm_repayment_draft,
    get_repayment_draft_response,
    repayment_draft_response,
)
from app.services.debt_service._repayment_correction_context import repayment_source_rows
from app.services.goal_debt_repayment_achievement import stage_debt_goal_achievements
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)

_CONFIRM_OPERATION = "confirm_repayment_draft"
_DRAFT_TARGET_TYPE = "repayment_draft"


def _actor_scoped_fingerprint_body(body: dict[str, object], *, actor_account_id: int) -> dict[str, object]:
    # A replay HIT returns before the writer guard can run again.  Binding the
    # fingerprint to the actor keeps one account from replaying another account's
    # intent even when both participate in the same ledger.
    return {**body, "actor_account_id": actor_account_id}


def confirm_repayment_draft_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: RepaymentDraftConfirmRequest,
    idempotency_key: str | None,
) -> RepaymentDraftResponse:
    """Confirm once; replay the accepted receipt even after a later correction."""

    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_CONFIRM_OPERATION,
        target_id=public_id,
        target_type=_DRAFT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json",
                exclude_unset=True,
                exclude={"expected_row_version"},
            ),
            actor_account_id=actor_account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        receipt = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == tenant_id,
            ApiIdempotencyKey.idempotency_key == idempotency_key))
        if receipt.response_body is not None:
            return RepaymentDraftResponse.model_validate(receipt.response_body)
        # Old successful claims predate response snapshots. Keep their historical reader.
        return get_repayment_draft_response(
            db,
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
        )

    draft = confirm_repayment_draft(
        db,
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        public_id=public_id,
        target_debt_public_id=payload.target_debt_public_id,
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key or "",
        original_currency=payload.original_currency,
        original_amount=payload.original_amount,
        time_input=payload.time_input,
        commit=False,
    )
    if payload.target_choice_explicit:
        from app.services.repayment_learning_service import record_repayment_choice

        record_repayment_choice(db, draft=draft, actor_account_id=actor_account_id)
    result = repayment_draft_response(draft)
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DRAFT_TARGET_TYPE,
        resource_id=draft.public_id,
        response_body=result.model_dump(mode="json"),
    )
    _, source_offset = repayment_source_rows(db, draft)
    account_ids = (set(db.scalars(select(AccountMovement.account_id).where(
        AccountMovement.offset_id == source_offset.id))) if source_offset is not None else set())
    stage_debt_goal_achievements(db, account_ids=account_ids,
        debt_ids=db.scalars(select(Debt.id).where(Debt.public_id == draft.committed_debt_public_id)))
    db.commit()
    return result
