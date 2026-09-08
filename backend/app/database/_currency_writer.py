"""PostgreSQL primitives for the installation-currency writer fence."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


def set_currency_writer_proof(
    db: Session,
    *,
    guc_name: str,
    contract_version: int,
    binding_revision: int,
) -> None:
    proof = f"{contract_version}:{binding_revision}"
    db.execute(
        text("SELECT set_config(:key, :proof, true)"),
        {"key": guc_name, "proof": proof},
    )


def lock_currency_evidence_tables(db: Session, tables: Sequence[str]) -> None:
    """Lock the fixed evidence inventory in one PostgreSQL statement."""

    if not tables or any(not table.replace("_", "").isalnum() for table in tables):
        raise ValueError("currency evidence table inventory contains an invalid identifier")
    quoted_tables = ", ".join(f'"{table}"' for table in tables)
    db.execute(text("SET LOCAL lock_timeout = '15s'"))
    db.execute(text(f"LOCK TABLE {quoted_tables} IN SHARE ROW EXCLUSIVE MODE"))


def captured_currency_evidence_rows(connection: Connection) -> Iterator[dict[str, object]]:
    """Read supplemental currency facts without changing frozen schema attestation."""
    for table in ("budgets", "csv_import_rows", "monthly_income_plans"):
        for row in connection.execute(text(
            f"SELECT id, tenant_id, to_jsonb({table})->>'home_currency_code' AS home_currency_code FROM {table} ORDER BY id"
        )):
            yield {"table": table, "id": row.id, "tenant_id": row.tenant_id, "home_currency_code": row.home_currency_code}
    # Frozen migration probes predate revisions. Current Owner adoption locks
    # its full table inventory first, so a missing current table cannot succeed.
    if inspect(connection).has_table("income_plan_revisions", schema="public"):
        for row in connection.execute(text("SELECT to_jsonb(income_plan_revisions)::text FROM income_plan_revisions ORDER BY id")):
            yield {"income_revision": row[0]}
