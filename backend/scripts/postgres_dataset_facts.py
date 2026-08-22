"""Stable PostgreSQL row and sequence facts for recovery qualification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import create_engine, text


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
    finally:
        engine.dispose()


__all__ = ["DatabaseFacts", "TableFacts", "read_database_facts"]
