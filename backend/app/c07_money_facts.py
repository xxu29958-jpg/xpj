"""Canonical streaming digest for the ADR-0073 C07 stored money facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, text

from app.c07_money_facts_contract import (
    INSTALLATION_HOME_CURRENCY_KEY,
    MONEY_FACT_CONTEXT_COLUMNS_V1,
    MONEY_FACT_TABLES,
    MONEY_FACTS_SCHEMA,
)
from app.database._c07_app_meta import read_app_meta_value
from app.money_contract import MONEY_COLUMNS_V1


def _fail(error: Callable[[str], Exception], message: str) -> None:
    raise error(message)


def _canonical_identity(
    value: object,
    *,
    error: Callable[[str], Exception],
) -> str:
    if isinstance(value, bool) or value is None:
        _fail(error, "C07 money fact identity is not canonical")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (str, UUID)):
        rendered = str(value)
        if not rendered:
            _fail(error, "C07 money fact identity is empty")
        return rendered
    _fail(error, "C07 money fact identity type is unsupported")
    raise AssertionError("unreachable")


def _canonical_money(
    value: object,
    *,
    error: Callable[[str], Exception],
) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(error, "C07 money fact value is not an integer")
    return str(value)


def _canonical_context(
    value: object,
    *,
    error: Callable[[str], Exception],
) -> dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"type": "boolean", "value": "true" if value else "false"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            _fail(error, "C07 money fact context decimal is not finite")
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    _fail(error, "C07 money fact context type is unsupported")
    raise AssertionError("unreachable")


def _json_line(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _primary_columns(
    inspector: Any,
    *,
    table: str,
    error: Callable[[str], Exception],
) -> tuple[str, ...]:
    primary_key = inspector.get_pk_constraint(table).get(
        "constrained_columns"
    )
    if (
        not isinstance(primary_key, (list, tuple))
        or not primary_key
        or any(
            not isinstance(column, str) or not column
            for column in primary_key
        )
    ):
        _fail(
            error,
            f"C07 money fact table lacks a stable primary key: {table}",
        )
    return tuple(primary_key)


def _update_table_digest(
    connection: Any,
    digest: Any,
    *,
    inspector: Any,
    table: str,
    money_columns: tuple[str, ...],
    context_columns: tuple[str, ...],
    error: Callable[[str], Exception],
) -> None:
    quoted = connection.dialect.identifier_preparer.quote_identifier
    primary_columns = _primary_columns(
        inspector,
        table=table,
        error=error,
    )
    available_columns = {
        item["name"] for item in inspector.get_columns(table)
    }
    required_columns = set(money_columns) | set(context_columns)
    if not required_columns <= available_columns:
        _fail(
            error,
            f"C07 money fact table is missing frozen source columns: {table}",
        )
    digest.update(
        _json_line(
            {
                "table": table,
                "identity_columns": primary_columns,
                "money_columns": money_columns,
                "context_columns": context_columns,
            }
        )
    )
    selected = (*primary_columns, *money_columns, *context_columns)
    result = connection.execute(
        text(
            "SELECT "
            + ", ".join(quoted(column) for column in selected)
            + f" FROM {quoted(table)} ORDER BY "
            + ", ".join(quoted(column) for column in primary_columns)
        ),
        execution_options={"stream_results": True, "yield_per": 1000},
    )
    identity_count = len(primary_columns)
    money_count = len(money_columns)
    money_end = identity_count + money_count
    for row in result:
        digest.update(
            _json_line(
                {
                    "table": table,
                    "identity": [
                        _canonical_identity(value, error=error)
                        for value in row[:identity_count]
                    ],
                    "money": [
                        _canonical_money(value, error=error)
                        for value in row[identity_count:money_end]
                    ],
                    "context": [
                        _canonical_context(value, error=error)
                        for value in row[money_end:]
                    ],
                }
            )
        )


def _installation_currency(
    connection: Any,
    *,
    error: Callable[[str], Exception],
) -> str | None:
    value = read_app_meta_value(connection, INSTALLATION_HOME_CURRENCY_KEY)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        _fail(error, "C07 installation currency marker is invalid")
    return value


def canonical_money_facts_sha256(
    connection: Any,
    *,
    error: Callable[[str], Exception] = RuntimeError,
) -> str:
    """Hash source-existing amount semantics before and after C07 widening.

    Rows are streamed in primary-key order. The digest binds the frozen 30
    amount columns, their stable row identities, existing currency/rate/status
    context, NULL state, and installation currency marker. It deliberately
    excludes every schema field introduced after the C07 source revision.
    """

    digest = hashlib.sha256()
    digest.update((MONEY_FACTS_SCHEMA + "\n").encode())
    digest.update(
        _json_line(
            {
                "installation_home_currency": _installation_currency(
                    connection,
                    error=error,
                )
            }
        )
    )
    inspector = inspect(connection)
    context_by_table = dict(MONEY_FACT_CONTEXT_COLUMNS_V1)
    for table in MONEY_FACT_TABLES:
        money_columns = tuple(
            contract.column
            for contract in MONEY_COLUMNS_V1
            if contract.table == table
        )
        _update_table_digest(
            connection,
            digest,
            inspector=inspector,
            table=table,
            money_columns=money_columns,
            context_columns=context_by_table[table],
            error=error,
        )
    return digest.hexdigest()
