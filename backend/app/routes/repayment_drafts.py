"""ADR-0049 §杠杆③ NLS repayment-capture routes (slice 3a).

Thin route layer (§1): parse + auth + delegate to ``debt_service`` + return a schema.

- ``GET  /api/repayment-drafts`` — the review inbox (default ``status=pending``).
- ``POST /api/repayment-drafts`` — capture one NLS repayment as a pending draft.
- ``POST /api/repayment-drafts/{public_id}/confirm`` — record one ``Repayment`` against
  a chosen open external/manual Debt and latch the draft confirmed (fold-changing →
  carries ``expected_row_version``; [[0042]] Idempotency-Key; a HIT re-serialises the
  draft WITHOUT re-recording).
- ``POST /api/repayment-drafts/{public_id}/dismiss`` — latch a pending draft dismissed.

Writes are writers-only (``get_current_writer_context`` → viewer 403). Capture (create)
and dismiss take no OCC token — create is a brand-new row (safe replay rests on the
content+identity dedup key), dismiss is a status-guarded terminal flip; both are listed
in the ADR-0038 mutate-token ledger. Drafts NEVER auto-record a repayment (§8): the
captured draft lands pending and the user's confirm is the authoritative act.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    RepaymentDraftConfirmRequest,
    RepaymentDraftCreateRequest,
    RepaymentDraftDismissRequest,
    RepaymentDraftListResponse,
    RepaymentDraftResponse,
)
from app.services.debt_service import (
    confirm_repayment_draft,
    create_repayment_draft,
    dismiss_repayment_draft,
    get_repayment_draft_response,
    list_repayment_drafts,
    repayment_draft_response,
)
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/repayment-drafts",
    tags=["repayment-drafts"],
)

_CONFIRM_OPERATION = "confirm_repayment_draft"
_DRAFT_TARGET_TYPE = "repayment_draft"


def _actor_scoped_fingerprint_body(
    body: dict[str, object], *, actor_account_id: int
) -> dict[str, object]:
    # ADR-0049 §3.6: scope the [[0042]] fingerprint by actor — a HIT returns before
    # the writer guard re-runs, so a different actor must not replay past it.
    return {**body, "actor_account_id": actor_account_id}


@router.get("", response_model=RepaymentDraftListResponse)
def get_repayment_drafts(
    status: str = Query(default="pending"),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RepaymentDraftListResponse:
    return list_repayment_drafts(db, tenant_id=auth.tenant_id, status=status)


@router.post("", response_model=RepaymentDraftResponse, status_code=201)
def post_repayment_draft(
    payload: RepaymentDraftCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RepaymentDraftResponse:
    draft = create_repayment_draft(
        db,
        payload=payload,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
    )
    return repayment_draft_response(draft)


@router.post("/{public_id}/confirm", response_model=RepaymentDraftResponse, status_code=201)
def post_repayment_draft_confirm(
    public_id: str,
    payload: RepaymentDraftConfirmRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RepaymentDraftResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_CONFIRM_OPERATION,
        target_id=public_id,
        target_type=_DRAFT_TARGET_TYPE,
        body=_actor_scoped_fingerprint_body(
            payload.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_row_version"}
            ),
            actor_account_id=auth.account_id,
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:  # replay: re-serialise the (already confirmed) draft, no re-record.
        return get_repayment_draft_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    draft = confirm_repayment_draft(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        target_debt_public_id=payload.target_debt_public_id,
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DRAFT_TARGET_TYPE, resource_id=draft.public_id
    )
    db.commit()
    return repayment_draft_response(draft)


@router.post("/{public_id}/dismiss", response_model=RepaymentDraftResponse, status_code=201)
def post_repayment_draft_dismiss(
    public_id: str,
    payload: RepaymentDraftDismissRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RepaymentDraftResponse:
    draft = dismiss_repayment_draft(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        public_id=public_id,
        commit=True,
    )
    return repayment_draft_response(draft)
