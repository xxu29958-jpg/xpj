"""PostgreSQL primitives for the installation-currency writer fence."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
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
