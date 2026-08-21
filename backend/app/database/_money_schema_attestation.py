"""Read-only PostgreSQL attestation for Ticketbox's durable money schema."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_FINAL_CHECKS_V1,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)


class MoneySchemaAttestationError(RuntimeError):
    """The live database does not match the released money contract."""


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _quoted(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(identifier)


def _normalized_check_expression(
    connection: Connection,
    *,
    table: str,
    predicate: str,
) -> str:
    alias = "money_expected"
    plan = connection.scalar(
        text(
            "EXPLAIN (VERBOSE, FORMAT JSON, COSTS FALSE) "
            f"SELECT 1 FROM {_quoted(connection, table)} AS {alias} "
            f"WHERE ({predicate})"
        )
    )
    try:
        expression = str(plan[0]["Plan"]["Filter"])
    except (IndexError, KeyError, TypeError) as exc:
        raise MoneySchemaAttestationError(
            f"money schema could not parse expected CHECK for {table}"
        ) from exc
    return expression.replace(f"{alias}.", "").replace(f'"{alias}".', "")


def _catalog_column_shape(
    connection: Connection,
    *,
    table: str,
    column: str,
) -> dict[str, str]:
    row = connection.execute(
        text(
            "SELECT a.attidentity, a.attgenerated, t.typtype "
            "FROM pg_catalog.pg_attribute AS a "
            "JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "JOIN pg_catalog.pg_type AS t ON t.oid = a.atttypid "
            "WHERE n.nspname = 'public' "
            "AND c.relname = :table AND a.attname = :column "
            "AND a.attnum > 0 AND NOT a.attisdropped "
            "AND c.relkind IN ('r', 'p')"
        ),
        {"table": table, "column": column},
    ).one_or_none()
    if row is None:
        raise MoneySchemaAttestationError(
            f"money schema is missing catalog identity for {table}.{column}"
        )
    identity = str(row[0] or "")
    generated = str(row[1] or "")
    type_kind = str(row[2] or "")
    if identity or generated or type_kind != "b":
        raise MoneySchemaAttestationError(
            f"money schema found identity/generated/domain storage at {table}.{column}"
        )
    return {"identity": "", "generated": "", "type_kind": "base"}


def _column_shape(
    connection: Connection,
    inspector,
    contract,
) -> dict[str, object]:
    actual = {
        item["name"]: item
        for item in inspector.get_columns(contract.table, schema="public")
    }.get(contract.column)
    if actual is None:
        raise MoneySchemaAttestationError(
            f"money schema is missing {contract.table}.{contract.column}"
        )
    raw_type = str(actual["type"]).lower()
    if "bigint" not in raw_type and raw_type != "int8":
        raise MoneySchemaAttestationError(
            f"money schema found non-int8 {contract.table}.{contract.column}"
        )
    if bool(actual["nullable"]) is not contract.nullable:
        raise MoneySchemaAttestationError(
            f"money schema nullability drifted at {contract.table}.{contract.column}"
        )
    if actual.get("default") != contract.server_default:
        raise MoneySchemaAttestationError(
            f"money schema default drifted at {contract.table}.{contract.column}"
        )
    return {
        "table": contract.table,
        "column": contract.column,
        "type": "int8",
        "nullable": contract.nullable,
        "server_default": contract.server_default,
        **_catalog_column_shape(
            connection,
            table=contract.table,
            column=contract.column,
        ),
    }


def _check_shape(
    connection: Connection,
    *,
    table: str,
    name: str,
    predicate: str,
) -> dict[str, object]:
    row = connection.execute(
        text(
            "SELECT pg_get_expr(c.conbin, c.conrelid, false), "
            "c.convalidated, c.connoinherit "
            "FROM pg_catalog.pg_constraint AS c "
            "WHERE c.conrelid = to_regclass(:table) "
            "AND c.contype = 'c' AND c.conname = :name"
        ),
        {"table": f"public.{table}", "name": name},
    ).one_or_none()
    if row is None or row[1] is not True or row[2] is not False:
        raise MoneySchemaAttestationError(
            f"money schema is missing or has an unvalidated CHECK {table}.{name}"
        )
    expected = _normalized_check_expression(
        connection,
        table=table,
        predicate=predicate,
    )
    actual = _normalized_check_expression(
        connection,
        table=table,
        predicate=str(row[0]),
    )
    if actual != expected:
        raise MoneySchemaAttestationError(
            f"money schema CHECK predicate drifted at {table}.{name}"
        )
    return {
        "table": table,
        "name": name,
        "expression_sha256": hashlib.sha256(str(row[0]).encode("utf-8")).hexdigest(),
        "validated": True,
        "no_inherit": False,
    }


def _absent_check_shape(
    connection: Connection,
    *,
    table: str,
    name: str,
) -> dict[str, object]:
    exists = connection.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_constraint AS c "
            "WHERE c.conrelid = to_regclass(:table) "
            "AND c.contype = 'c' AND c.conname = :name)"
        ),
        {"table": f"public.{table}", "name": name},
    )
    if exists is not False:
        raise MoneySchemaAttestationError(
            f"money schema retained legacy CHECK {table}.{name}"
        )
    return {"table": table, "name": name, "absent": True}


def read_money_schema_shape(connection: Connection) -> dict[str, object]:
    """Return the canonical read-only shape of the released money contract."""

    inspector = inspect(connection)
    columns = [
        _column_shape(connection, inspector, contract)
        for contract in MONEY_COLUMNS_V1
    ]
    checks = [
        _check_shape(
            connection,
            table=contract.table,
            name=check.name,
            predicate=check.predicate,
        )
        for contract in MONEY_COLUMNS_V1
        for check in contract.checks
    ]
    absent_checks = [
        _absent_check_shape(
            connection,
            table=check.table,
            name=check.name,
        )
        for check in MONEY_REMOVED_LEGACY_CHECKS_V1
    ]
    if (
        len(columns) != len(MONEY_COLUMNS_V1)
        or len(checks) != len(MONEY_FINAL_CHECKS_V1)
        or len(absent_checks) != len(MONEY_REMOVED_LEGACY_CHECKS_V1)
    ):
        raise MoneySchemaAttestationError("money schema manifest cardinality drifted")
    payload = {
        "columns": columns,
        "checks": checks,
        "absent_checks": absent_checks,
    }
    return {
        "column_count": len(columns),
        "check_count": len(checks),
        "absent_check_count": len(absent_checks),
        "shape_sha256": _canonical_sha256(payload),
        **payload,
    }


__all__ = [
    "MoneySchemaAttestationError",
    "read_money_schema_shape",
]
