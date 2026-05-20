"""Owner Console rule-application audit view-models.

Read-only listing of recent rule application batches. Reuses the
existing ``classify_service.list_rule_applications`` rather than
duplicating its query.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.ledger_service import LedgerSummary
from app.services.owner_console_service._ledger_console import (
    list_console_ledger_choices,
)


@dataclass
class RuleApplicationAuditRow:
    ledger_id: str
    ledger_name: str
    public_id: str
    status: str
    pending_scanned: int
    changed_count: int
    created_at: object
    rolled_back_at: object | None


@dataclass
class RuleApplicationAuditVM:
    ledger_choices: list[LedgerSummary]
    selected_ledger_id: str | None
    selected_ledger_name: str | None
    rows: list[RuleApplicationAuditRow]


def get_rule_application_audit(
    db: Session,
    *,
    ledger_id: str | None = None,
    limit: int = 20,
) -> RuleApplicationAuditVM:
    """Recent rule application batches for the Owner Console.

    This is a read-only audit view. It intentionally reuses the existing rule
    application list service and only allows ledgers the local owner account
    can already manage from the console.
    """
    from app.services.classify_service import list_rule_applications

    choices = list_console_ledger_choices(db)
    if not choices:
        return RuleApplicationAuditVM(
            ledger_choices=[],
            selected_ledger_id=None,
            selected_ledger_name=None,
            rows=[],
        )

    by_id = {row.ledger_id: row for row in choices}
    if ledger_id:
        selected = by_id.get(ledger_id)
        if selected is None:
            raise AppError("ledger_forbidden", "请选择一个有权限的账本。", status_code=403)
    else:
        selected = choices[0]

    batches = list_rule_applications(db, tenant_id=selected.ledger_id, limit=limit)
    rows = [
        RuleApplicationAuditRow(
            ledger_id=selected.ledger_id,
            ledger_name=selected.name,
            public_id=batch.public_id,
            status=batch.status,
            pending_scanned=batch.pending_scanned,
            changed_count=batch.changed_count,
            created_at=batch.created_at,
            rolled_back_at=batch.rolled_back_at,
        )
        for batch in batches
    ]
    return RuleApplicationAuditVM(
        ledger_choices=choices,
        selected_ledger_id=selected.ledger_id,
        selected_ledger_name=selected.name,
        rows=rows,
    )
