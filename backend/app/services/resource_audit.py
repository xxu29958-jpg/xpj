"""ADR-0038 undo: generic resource-action rows in ``ledger_audit_logs``.

The governance audit log (:class:`LedgerAuditLog`) is reused for
resource-level actions like ``undo`` by setting the generic
``resource_type`` / ``resource_public_id`` columns; the family/membership
columns (target_member_id / invitation_public_id / roles) stay NULL. This
keeps a single audit timeline per ledger instead of a parallel table.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import LedgerAuditLog


def record_resource_action(
    db: Session,
    *,
    ledger_id: str,
    action: str,
    resource_type: str,
    resource_public_id: str,
    actor_account_id: int | None = None,
) -> None:
    """Append one resource-level audit row. The caller owns the commit."""
    db.add(
        LedgerAuditLog(
            ledger_id=ledger_id,
            action=action,
            actor_account_id=actor_account_id,
            resource_type=resource_type,
            resource_public_id=resource_public_id,
        )
    )
