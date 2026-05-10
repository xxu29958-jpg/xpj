"""Multi-ledger HTTP API for v0.4-alpha1.

Routes here translate ``AuthContext`` into ledger-service calls. Business
logic lives in :mod:`app.services.ledger_service`; this file must stay thin.

The Bearer token determines who the caller is:

* ``GET  /api/ledgers``               — any app/admin token; lists ledgers
                                        the caller's account can access.
* ``POST /api/ledgers``               — app token with ``role == 'owner'`` or
                                        any admin token; creates a new ledger
                                        owned by the calling account.
* ``POST /api/ledgers/{id}/switch``   — app token only; rotates the caller's
                                        session token to a new ledger-scoped
                                        token. The previous token is revoked.

Routes never trust ledger ids that arrive in request bodies or headers as a
substitute for ``AuthContext.ledger_id``; only the ledger explicitly named in
the URL of ``/switch`` is used, and even then it is validated against the
account's active membership before any token is issued.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import (
    _bearer_token,
    get_current_app_context,
    get_current_owner_or_admin_context,
)
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    LedgerCreateRequest,
    LedgerListResponse,
    LedgerResponse,
    LedgerSwitchResponse,
)
from app.services.ledger_service import (
    LedgerSummary,
    create_ledger,
    list_ledgers_for_account,
    switch_ledger,
)
from app.tenants import AuthContext


router = APIRouter(prefix="/api/ledgers", tags=["ledgers"])


def _to_response(summary: LedgerSummary) -> LedgerResponse:
    return LedgerResponse(
        ledger_id=summary.ledger_id,
        name=summary.name,
        role=summary.role,
        is_default=summary.is_default,
        created_at=summary.created_at,
        archived_at=summary.archived_at,
    )


@router.get("", response_model=LedgerListResponse)
def list_ledgers(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> LedgerListResponse:
    summaries = list_ledgers_for_account(db, account_id=auth.account_id)
    return LedgerListResponse(ledgers=[_to_response(s) for s in summaries])


@router.post("", response_model=LedgerResponse, status_code=201)
def create_ledger_endpoint(
    payload: LedgerCreateRequest,
    auth: AuthContext = Depends(get_current_owner_or_admin_context),
    db: Session = Depends(get_db),
) -> LedgerResponse:
    summary = create_ledger(db, account_id=auth.account_id, name=payload.name)
    return _to_response(summary)


@router.post("/{ledger_id}/switch", response_model=LedgerSwitchResponse)
def switch_ledger_endpoint(
    ledger_id: str,
    authorization: str | None = Header(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> LedgerSwitchResponse:
    # The dependency above already validated and returned an AuthContext for
    # the caller's *current* (pre-switch) ledger. We still need the raw token
    # value so the service can revoke it atomically with issuing the new one.
    if not authorization:
        raise AppError("invalid_token", status_code=401)
    current_token = _bearer_token(authorization)
    result = switch_ledger(
        db,
        current_token_value=current_token,
        account_id=auth.account_id,
        device_id=auth.device_id,
        target_ledger_id=ledger_id,
    )
    return LedgerSwitchResponse(
        session_token=result.session_token,
        ledger=LedgerResponse(
            ledger_id=result.ledger_id,
            name=result.ledger_name,
            role=result.role,
            is_default=result.is_default,
            created_at=result.created_at,
            archived_at=result.archived_at,
        ),
        account_name=result.account_name,
        device_name=result.device_name,
    )
