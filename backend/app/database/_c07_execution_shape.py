"""PostgreSQL target-shape verification shared by the C07 ceremony."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.database._c07_contract import (
    C07_TARGET_REVISION,
    C07CeremonyError,
    canonical_json,
    sha256_bytes,
)
from app.database._c07_storage import _quoted
from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_CONTRACT_PHASE_C07,
    MONEY_CONTRACT_PHASE_KEY,
    MONEY_FINAL_CHECKS_V1,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)


def _read_only_expected_check_expression(
    connection,
    *,
    table: str,
    predicate: str,
) -> str:
    alias = "c07_expected"
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
        raise C07CeremonyError(
            f"C07 could not parse expected CHECK for {table}"
        ) from exc
    return expression.replace(f"{alias}.", "").replace(f'"{alias}".', "")


def _money_column_catalog_shape(connection, contract) -> dict[str, str]:
    row = connection.execute(
        text(
            "SELECT a.attidentity, a.attgenerated, t.typtype "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_type t ON t.oid = a.atttypid "
            "WHERE n.nspname = 'public' "
            "AND c.relname = :table AND a.attname = :column "
            "AND a.attnum > 0 AND NOT a.attisdropped "
            "AND c.relkind IN ('r', 'p')"
        ),
        {"table": contract.table, "column": contract.column},
    ).one_or_none()
    if row is None:
        raise C07CeremonyError(
            f"C07 post-check missing catalog identity for "
            f"{contract.table}.{contract.column}"
        )
    identity = str(row[0] or "")
    generated = str(row[1] or "")
    type_kind = str(row[2] or "")
    if identity or generated or type_kind != "b":
        raise C07CeremonyError(
            f"C07 post-check found identity/generated/domain storage at "
            f"{contract.table}.{contract.column}"
        )
    return {
        "identity": "",
        "generated": "",
        "type_kind": "base",
    }


def _column_shape(connection, inspector, contract) -> dict[str, object]:
    actual = {
        item["name"]: item for item in inspector.get_columns(contract.table)
    }.get(contract.column)
    if actual is None:
        raise C07CeremonyError(
            f"C07 post-check missing {contract.table}.{contract.column}"
        )
    raw_type = str(actual["type"]).lower()
    if "bigint" not in raw_type and raw_type != "int8":
        raise C07CeremonyError(
            f"C07 post-check found non-int8 {contract.table}.{contract.column}"
        )
    if bool(actual["nullable"]) is not contract.nullable:
        raise C07CeremonyError(
            f"C07 post-check nullability mismatch "
            f"{contract.table}.{contract.column}"
        )
    if actual.get("default") != contract.server_default:
        raise C07CeremonyError(
            f"C07 post-check server default mismatch "
            f"{contract.table}.{contract.column}"
        )
    return {
        "table": contract.table,
        "column": contract.column,
        "type": "int8",
        "nullable": contract.nullable,
        "server_default": contract.server_default,
        **_money_column_catalog_shape(connection, contract),
    }


def _check_shape(
    connection,
    *,
    contract,
    name: str,
    predicate: str,
) -> dict[str, object]:
    row = connection.execute(
        text(
            "SELECT pg_get_expr(c.conbin, c.conrelid, false), "
            "c.convalidated, c.connoinherit FROM pg_constraint c "
            "WHERE c.conrelid = to_regclass(:table) "
            "AND c.contype = 'c' AND c.conname = :name"
        ),
        {"table": f"public.{contract.table}", "name": name},
    ).one_or_none()
    if row is None or row[1] is not True or row[2] is not False:
        raise C07CeremonyError(
            f"C07 post-check missing/unvalidated {contract.table}.{name}"
        )
    expected = _read_only_expected_check_expression(
        connection,
        table=contract.table,
        predicate=predicate,
    )
    actual = _read_only_expected_check_expression(
        connection,
        table=contract.table,
        predicate=str(row[0]),
    )
    if actual != expected:
        raise C07CeremonyError(
            f"C07 post-check predicate mismatch {contract.table}.{name}"
        )
    return {
        "table": contract.table,
        "name": name,
        "expression_sha256": sha256_bytes(str(row[0]).encode()),
        "validated": True,
        "no_inherit": False,
    }


def _absent_check_shape(connection, check) -> dict[str, object]:
    exists = connection.scalar(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_constraint c "
            "WHERE c.conrelid = to_regclass(:table) "
            "AND c.contype = 'c' AND c.conname = :name)"
        ),
        {"table": f"public.{check.table}", "name": check.name},
    )
    if exists is not False:
        raise C07CeremonyError(
            f"C07 post-check retained legacy CHECK {check.table}.{check.name}"
        )
    return {"table": check.table, "name": check.name, "absent": True}


def _money_shape(
    connection,
    *,
    target_revision: str,
) -> dict[str, object]:
    if target_revision != C07_TARGET_REVISION:
        raise C07CeremonyError(
            "C07 post-check target revision is unsupported"
        )
    inspector = inspect(connection)
    columns = [
        _column_shape(connection, inspector, contract)
        for contract in MONEY_COLUMNS_V1
    ]
    checks = [
        _check_shape(
            connection,
            contract=contract,
            name=name,
            predicate=predicate,
        )
        for contract in MONEY_COLUMNS_V1
        for check in contract.checks
        for name, predicate in ((check.name, check.predicate),)
    ]
    absent_checks = [
        _absent_check_shape(connection, check)
        for check in MONEY_REMOVED_LEGACY_CHECKS_V1
    ]
    phase = connection.scalar(
        text("SELECT value FROM app_meta WHERE key = :key"),
        {"key": MONEY_CONTRACT_PHASE_KEY},
    )
    if phase != MONEY_CONTRACT_PHASE_C07:
        raise C07CeremonyError("C07 post-check phase marker mismatch")
    if (
        len(columns) != len(MONEY_COLUMNS_V1)
        or len(checks) != len(MONEY_FINAL_CHECKS_V1)
        or len(absent_checks) != len(MONEY_REMOVED_LEGACY_CHECKS_V1)
    ):
        raise C07CeremonyError("C07 post-check manifest cardinality mismatch")
    shape_payload = {
        "columns": columns,
        "checks": checks,
        "absent_checks": absent_checks,
        "phase": phase,
    }
    return {
        "column_count": len(columns),
        "check_count": len(checks),
        "absent_check_count": len(absent_checks),
        "phase": phase,
        "shape_sha256": sha256_bytes(
            canonical_json(shape_payload).encode("utf-8")
        ),
        "columns": columns,
        "checks": checks,
        "absent_checks": absent_checks,
    }
