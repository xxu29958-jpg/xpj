"""ADR-0049 §7.0 / 8e-6e: correct an existing Debt's repayment-rhythm classification.

The create path accepts ``debt_kind`` up front; this is the post-hoc correction entry (the
Android detail-screen type chip / a fix for a bill_split or NLS-created Debt that defaulted to
``unspecified``). OCC-gated so two concurrent reclassifications cannot both silently win.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt
from app.schemas import DebtKindSetRequest
from app.services.debt_service._query import get_debt
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc


def set_debt_kind(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtKindSetRequest,
    commit: bool = False,
) -> None:
    """Set a Debt's ``debt_kind`` under an OCC token (ADR-0049 §7.0 / 8e-6e).

    ``debt_not_found`` (404) if the Debt is not visible in the tenant; ``state_conflict``
    (409) on a stale ``expected_row_version``. The claim bumps ``row_version`` (the OCC token);
    it is NOT fold-changing — ``debt_kind`` gates only the external-debt payoff projection, so
    ``remaining`` / ``paid`` / ``status`` are untouched. Allowed on any status (reclassifying a
    cleared / voided Debt is inert). ``commit=False`` lets the route commit it together with the
    [[0042]] idempotency-success record.
    """
    debt = get_debt(db, tenant_id=tenant_id, public_id=public_id)
    rowcount = claim_row_with_token(
        db,
        Debt,
        pk_id=debt.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"debt_kind": payload.debt_kind, "updated_at": now_utc()},
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()
    else:
        db.flush()
