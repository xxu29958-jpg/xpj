"""ADR-0041 phase-2: one-time SQLite -> PostgreSQL data migration + reconciliation.

Copies every ORM table from a source engine (SQLite, the current store) into a
target engine (local PostgreSQL) preserving primary keys, then reconciles the
two so a cut-over only proceeds when the data matches. Two landmines the ADR
calls out are handled here:

- **UTC attach**: SQLite reads ``DateTime(timezone=True)`` back as *naive*.
  Inserting a naive value into a PostgreSQL ``timestamptz`` would be interpreted
  in the session timezone; every such value is UTC-attached first so the stored
  instant is unchanged.
- **Sequence reset**: rows are inserted with their original ``id``, so each
  PostgreSQL ``SERIAL``/``IDENTITY`` sequence is ``setval``'d to ``max(id)`` or
  the first new insert after cut-over collides on the primary key.

The copy runs with ``session_replication_role = replica`` on PostgreSQL so
foreign-key triggers don't fire mid-load — that sidesteps both cross-table
ordering and self-referential rows (``expenses.duplicate_of_id`` etc.). CHECK
constraints still apply. ``Base.metadata.sorted_tables`` is used as a belt-and-
suspenders dependency order on top of that.

Reconciliation never deletes the source. A failing check returns
``status="error"`` and the caller (CLI / runbook) aborts the cut-over.

Lives under ``app.database`` (not ``app.services``) because it is engine-level
infrastructure that legitimately hand-writes PostgreSQL DDL/DML.

CLI::

    python -m app.database.data_migration \
        --source sqlite:///data/ticketbox.db \
        --target postgresql+psycopg://user:pass@localhost/ticketbox

Add ``--reconcile-only`` to compare two already-populated databases without
copying.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Table, create_engine, func, select, text
from sqlalchemy.engine import Connection, Engine

from app.database._core import Base

_BATCH = 500
_SAMPLE_ROWS = 20


@dataclass(frozen=True)
class MigrationCheck:
    code: str
    status: str  # "ok" | "warn" | "error"
    message: str


@dataclass
class MigrationReport:
    checks: list[MigrationCheck]

    @property
    def ok(self) -> bool:
        return all(check.status != "error" for check in self.checks)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": [asdict(check) for check in self.checks]}


def _is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def _tz_columns(table: Table) -> tuple[str, ...]:
    """Names of ``DateTime(timezone=True)`` columns on the table."""
    return tuple(
        column.name
        for column in table.columns
        if isinstance(column.type, DateTime) and getattr(column.type, "timezone", False)
    )


def _attach_utc(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _prepare_row(row: dict, tz_columns: tuple[str, ...]) -> dict:
    prepared = dict(row)
    for name in tz_columns:
        prepared[name] = _attach_utc(prepared[name])
    return prepared


def _copy_table(source: Connection, target: Connection, table: Table) -> int:
    tz_columns = _tz_columns(table)
    rows = source.execute(select(table)).mappings().all()
    if not rows:
        return 0
    payload = [_prepare_row(dict(row), tz_columns) for row in rows]
    for start in range(0, len(payload), _BATCH):
        target.execute(table.insert(), payload[start : start + _BATCH])
    return len(payload)


def _copy_all_tables(source: Connection, target: Connection) -> list[MigrationCheck]:
    checks: list[MigrationCheck] = []
    for table in Base.metadata.sorted_tables:
        copied = _copy_table(source, target, table)
        checks.append(MigrationCheck(f"copy:{table.name}", "ok", f"{copied} rows"))
    return checks


def _setval_args(max_id: int) -> tuple[int, bool]:
    """``setval`` ``(value, is_called)``. An empty table -> ``(1, False)`` so the
    first new id is 1, not 2; a non-empty table -> ``(max_id, True)`` so the next
    id is ``max_id + 1`` (the cut-over PK-collision guard)."""
    if max_id <= 0:
        return (1, False)
    return (max_id, True)


def _reset_sequences(target: Connection) -> list[MigrationCheck]:
    """``setval`` each autoincrement sequence past ``max(id)``.

    ``pg_get_serial_sequence`` returns NULL for natural string PKs
    (schema_migrations / app_meta / ...): they have no sequence and are skipped.
    """
    checks: list[MigrationCheck] = []
    for table in Base.metadata.sorted_tables:
        if "id" not in table.c:
            continue
        sequence = target.execute(
            text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table.name}
        ).scalar()
        if sequence is None:
            continue
        max_id = int(
            target.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table.name}")).scalar() or 0
        )
        value, is_called = _setval_args(max_id)
        target.execute(
            text("SELECT setval(:seq, :val, :called)"),
            {"seq": sequence, "val": value, "called": is_called},
        )
        next_id = value + 1 if is_called else value
        checks.append(MigrationCheck(f"setval:{table.name}", "ok", f"next id -> {next_id}"))
    return checks


def _table_count(connection: Connection, table: Table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar() or 0)


def _reconcile_counts(source: Connection, target: Connection) -> list[MigrationCheck]:
    checks: list[MigrationCheck] = []
    for table in Base.metadata.sorted_tables:
        src = _table_count(source, table)
        tgt = _table_count(target, table)
        status = "ok" if src == tgt else "error"
        checks.append(MigrationCheck(f"rowcount:{table.name}", status, f"source={src} target={tgt}"))
    return checks


def _confirmed_expense_sums(connection: Connection) -> dict[str, int]:
    expenses = Base.metadata.tables["expenses"]
    rows = connection.execute(
        select(expenses.c.tenant_id, func.coalesce(func.sum(expenses.c.amount_cents), 0))
        .where(expenses.c.status == "confirmed")
        .group_by(expenses.c.tenant_id)
    ).all()
    return {str(tenant): int(total or 0) for tenant, total in rows}


def _reconcile_money(source: Connection, target: Connection) -> list[MigrationCheck]:
    src = _confirmed_expense_sums(source)
    tgt = _confirmed_expense_sums(target)
    if src == tgt:
        return [MigrationCheck("money:confirmed_by_ledger", "ok", f"{len(src)} ledgers match")]
    ledgers = sorted(set(src) | set(tgt))
    mismatched = [led for led in ledgers if src.get(led, 0) != tgt.get(led, 0)]
    return [
        MigrationCheck(
            "money:confirmed_by_ledger",
            "error",
            f"confirmed-spend sum differs for {len(mismatched)} ledger(s): {', '.join(mismatched)}",
        )
    ]


def _accepted_bill_split_counts(connection: Connection) -> dict[str, int]:
    invitations = Base.metadata.tables["bill_split_invitations"]
    rows = connection.execute(
        select(invitations.c.receiver_ledger_id, func.count())
        .where(invitations.c.status == "accepted")
        .group_by(invitations.c.receiver_ledger_id)
    ).all()
    return {str(ledger): int(count or 0) for ledger, count in rows}


def _reconcile_bill_split(source: Connection, target: Connection) -> list[MigrationCheck]:
    """ADR-0041 line 68: reconcile bill_split *received* count (accepted
    invitations), the second financial backstop alongside confirmed-spend sums.
    Keyed by receiver ledger so a per-ledger drift is named, not just a total.
    """
    src = _accepted_bill_split_counts(source)
    tgt = _accepted_bill_split_counts(target)
    if src == tgt:
        total = sum(src.values())
        return [
            MigrationCheck(
                "bill_split:received_count", "ok", f"{total} accepted across {len(src)} ledger(s)"
            )
        ]
    ledgers = sorted(set(src) | set(tgt))
    mismatched = [led for led in ledgers if src.get(led, 0) != tgt.get(led, 0)]
    return [
        MigrationCheck(
            "bill_split:received_count",
            "error",
            f"accepted-invitation count differs for {len(mismatched)} ledger(s): "
            f"{', '.join(mismatched)}",
        )
    ]


def _reconcile_sample(source: Connection, target: Connection) -> list[MigrationCheck]:
    """Field-by-field compare the head AND tail rows (by primary key) of each
    table across engines.

    Sampling both ends — not just the lowest keys — catches systematic
    corruption of the freshest (highest-key) rows. Every table has a single
    primary-key column (no composite / PK-less in this schema), so natural
    string-PK tables (``app_meta`` etc.) are field-sampled too, not just
    integer-id tables. Source timestamps are UTC-attached before comparison so a
    naive-SQLite vs aware-PostgreSQL read of the same instant compares equal.
    """
    checks: list[MigrationCheck] = []
    for table in Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)[0]
        tz_columns = _tz_columns(table)
        head = source.execute(select(table).order_by(pk.asc()).limit(_SAMPLE_ROWS)).mappings().all()
        tail = source.execute(select(table).order_by(pk.desc()).limit(_SAMPLE_ROWS)).mappings().all()
        deduped = {row[pk.name]: row for row in [*head, *tail]}
        mismatches = _sample_mismatches(target, table, pk, list(deduped.values()), tz_columns)
        status = "ok" if not mismatches else "error"
        detail = "matched" if not mismatches else f"row(s) differ: {', '.join(mismatches)}"
        checks.append(MigrationCheck(f"sample:{table.name}", status, detail))
    return checks


def _sample_mismatches(
    target: Connection, table: Table, pk: Column, src_rows, tz_columns: tuple[str, ...]
) -> list[str]:
    mismatches: list[str] = []
    for row in src_rows:
        expected = _prepare_row(dict(row), tz_columns)
        actual = target.execute(select(table).where(pk == row[pk.name])).mappings().first()
        if actual is None or _prepare_row(dict(actual), tz_columns) != expected:
            mismatches.append(str(row[pk.name]))
    return mismatches


def _reconcile(source: Connection, target: Connection) -> list[MigrationCheck]:
    return [
        *_reconcile_counts(source, target),
        *_reconcile_money(source, target),
        *_reconcile_bill_split(source, target),
        *_reconcile_sample(source, target),
    ]


def migrate(source_url: str, target_url: str, *, copy: bool = True) -> MigrationReport:
    """Create the target schema, copy every table, reset sequences, reconcile.

    ``copy=False`` only reconciles two already-populated databases.
    """
    import app.models  # noqa: F401  (populate Base.metadata before use)

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    checks: list[MigrationCheck] = []

    if copy:
        Base.metadata.create_all(target_engine)
        with source_engine.connect() as source, target_engine.begin() as target:
            if _is_postgres(target_engine):
                # Superuser-only; set first, before any copy, so a non-superuser
                # run fails here and rolls back to an empty target rather than
                # mid-load. The one-time migration runs as superuser; the app
                # runtime role does not need it (Slice-3 runbook documents this).
                target.execute(text("SET session_replication_role = 'replica'"))
            checks.extend(_copy_all_tables(source, target))
            if _is_postgres(target_engine):
                target.execute(text("SET session_replication_role = 'origin'"))
                checks.extend(_reset_sequences(target))

    with source_engine.connect() as source, target_engine.connect() as target:
        checks.extend(_reconcile(source, target))

    source_engine.dispose()
    target_engine.dispose()
    return MigrationReport(checks)


def _print_report(report: MigrationReport) -> None:
    for check in report.checks:
        marker = {"ok": "OK  ", "warn": "WARN", "error": "FAIL"}.get(check.status, "????")
        print(f"  {marker} {check.code}: {check.message}")
    print(f"\n{'PASS' if report.ok else 'FAIL'}  data-migration ({len(report.checks)} checks)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite -> PostgreSQL data migration (ADR-0041).")
    parser.add_argument("--source", required=True, help="source SQLAlchemy URL (sqlite:///...)")
    parser.add_argument("--target", required=True, help="target SQLAlchemy URL (postgresql+psycopg://...)")
    parser.add_argument(
        "--reconcile-only",
        action="store_true",
        help="compare two already-populated databases without copying",
    )
    args = parser.parse_args(argv)
    report = migrate(args.source, args.target, copy=not args.reconcile_only)
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
