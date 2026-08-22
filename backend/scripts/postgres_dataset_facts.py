"""Stable PostgreSQL row and sequence facts for recovery qualification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class TableFacts:
    row_count: int
    rows_sha256: str


@dataclass(frozen=True)
class DatabaseFacts:
    tables: dict[str, TableFacts]
    sequences: dict[str, tuple[int, bool]]


def read_database_facts(url: str) -> DatabaseFacts:
    """Hash every PUBLIC row canonically and observe every sequence state."""

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return _read_database_facts(connection)
    finally:
        engine.dispose()


def assert_database_fact_mutations_observed(url: str, baseline: DatabaseFacts) -> None:
    """Prove same-count row and sequence-only changes alter the real PG facts."""

    row_probe_table = "alembic_version"
    if baseline.tables.get(row_probe_table, TableFacts(0, "")).row_count != 1 or not baseline.sequences:
        raise SystemExit("FAIL drill: database fact mutation oracle lacks a row or sequence")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "UPDATE public.alembic_version "
                        "SET version_num = "
                        "CASE WHEN left(version_num, 1) = '0' THEN '1' ELSE '0' END "
                        "|| substring(version_num FROM 2)"
                    )
                )
                row_mutation = _read_database_facts(connection)
            finally:
                transaction.rollback()

            sequence = sorted(baseline.sequences)[0]
            identifier = connection.dialect.identifier_preparer.quote_identifier(sequence)
            restart = baseline.sequences[sequence][0] + 1
            transaction = connection.begin()
            try:
                connection.execute(text(f"ALTER SEQUENCE public.{identifier} RESTART WITH {restart}"))
                sequence_mutation = _read_database_facts(connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()

    restored = read_database_facts(url)
    if (
        row_mutation.tables[row_probe_table].row_count != baseline.tables[row_probe_table].row_count
        or row_mutation.tables[row_probe_table].rows_sha256 == baseline.tables[row_probe_table].rows_sha256
        or row_mutation.sequences != baseline.sequences
        or sequence_mutation.tables != baseline.tables
        or sequence_mutation.sequences == baseline.sequences
        or restored != baseline
    ):
        raise SystemExit("FAIL drill: PostgreSQL fact mutation oracle is incomplete")


def _read_database_facts(connection: Connection) -> DatabaseFacts:
    preparer = connection.dialect.identifier_preparer
    tables = tuple(
        str(row[0])
        for row in connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        )
    )
    table_facts: dict[str, TableFacts] = {}
    for table in tables:
        identifier = preparer.quote_identifier(table)
        rows = connection.execute(
            text(
                f"SELECT to_jsonb(row_value)::text FROM public.{identifier} AS row_value "
                "ORDER BY to_jsonb(row_value)::text"
            )
        )
        digest = hashlib.sha256()
        count = 0
        for row in rows:
            encoded = str(row[0]).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        table_facts[table] = TableFacts(row_count=count, rows_sha256=digest.hexdigest())
    sequences = tuple(
        str(row[0])
        for row in connection.execute(
            text("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' ORDER BY sequencename")
        )
    )
    sequence_facts: dict[str, tuple[int, bool]] = {}
    for sequence in sequences:
        identifier = preparer.quote_identifier(sequence)
        row = connection.execute(text(f"SELECT last_value, is_called FROM public.{identifier}")).one()
        sequence_facts[sequence] = int(row[0]), bool(row[1])
    return DatabaseFacts(tables=table_facts, sequences=sequence_facts)


__all__ = [
    "DatabaseFacts",
    "TableFacts",
    "assert_database_fact_mutations_observed",
    "read_database_facts",
]
