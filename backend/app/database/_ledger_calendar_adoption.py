"""PostgreSQL metadata adoption inside the ledger calendar owner's transaction."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def materialize_legacy_accounting_dates(
    db: Session, *, ledger_id: str, revision: int, timezone_name: str,
) -> None:
    """Apply the frozen rule through the database's metadata-only writer fence."""
    setting = "xpj.calendar_adoption"
    proof = json.dumps({"purpose": "legacy_adoption", "ledger_id": ledger_id, "revision": revision})
    db.execute(text("SELECT set_config(:setting, :proof, true)"), {"setting": setting, "proof": proof})
    parameters = {"ledger": ledger_id, "revision": revision, "zone": timezone_name}
    db.execute(text("""
        UPDATE expenses SET calendar_revision = :revision,
            accounting_date = (COALESCE(expense_time, confirmed_at) AT TIME ZONE :zone)::date,
            time_precision = 'unknown',
            accounting_date_basis = CASE WHEN expense_time IS NOT NULL THEN 'legacy_expense_time'
                WHEN confirmed_at IS NOT NULL THEN 'legacy_confirmed_at' ELSE 'legacy_unknown' END
        WHERE tenant_id = :ledger AND calendar_revision IS NULL
    """), parameters)
    db.execute(text("""
        UPDATE expense_offset_facts SET calendar_revision = :revision,
            time_precision = 'date_only', accounting_date_basis = 'legacy_offset_date'
        WHERE tenant_id = :ledger AND calendar_revision IS NULL
    """), parameters)
    db.execute(text("SELECT set_config(:setting, '', true)"), {"setting": setting})
