"""Live database identity and target-shape checks for C07 production."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, text

from app.c07_money_facts import canonical_money_facts_sha256
from app.database._c07_production_connection import (
    _revision,
    _run_alembic_upgrade,
)
from app.database._c07_production_contract import (
    C07_TARGET_REVISION,
    MAINTENANCE_WINDOW_SECONDS,
    PRODUCTION_MIGRATION_EVIDENCE_SCHEMA,
    C07ProductionMigrationError,
    ProductionMigrationContext,
    ValidatedProductionArtifacts,
)
from app.database._c07_production_fence import (
    _assert_connected_database as _assert_connected_database,
)
from app.database._c07_production_fence import (
    _assert_migrator_principal as _assert_migrator_principal,
)
from app.database._c07_production_fence import (
    _assert_production_writer_fence as _assert_production_writer_fence,
)
from app.database._c07_production_fence import (
    _assume_schema_owner as _assume_schema_owner,
)
from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_CONTRACT_PHASE_C07,
    MONEY_CONTRACT_PHASE_KEY,
    MONEY_FINAL_CHECKS_V1,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)

C07_CUTOVER_MONEY_FACTS_KEY = "c07_cutover_money_facts_sha256"
_ANALYZE_TABLES = tuple(
    sorted({contract.table for contract in MONEY_COLUMNS_V1})
)
_ANALYZE_TABLE_SET_SHA256 = hashlib.sha256(
    (
        json.dumps(
            _ANALYZE_TABLES,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
).hexdigest()


def _quoted(connection: Any, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(identifier)


def _read_only_expected_check_expression(
    connection: Any,
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
        raise C07ProductionMigrationError(
            f"C07 could not parse expected CHECK for {table}"
        ) from exc
    return expression.replace(f"{alias}.", "").replace(f'"{alias}".', "")


def _money_column_catalog_shape(
    connection: Any,
    contract,
) -> dict[str, str]:
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
        raise C07ProductionMigrationError(
            f"C07 target catalog identity is missing for "
            f"{contract.table}.{contract.column}"
        )
    identity = str(row[0] or "")
    generated = str(row[1] or "")
    type_kind = str(row[2] or "")
    if identity or generated or type_kind != "b":
        raise C07ProductionMigrationError(
            f"C07 target has identity/generated/domain storage for "
            f"{contract.table}.{contract.column}"
        )
    return {
        "identity": "",
        "generated": "",
        "type_kind": "base",
    }


def _column_shape(connection: Any, inspector, contract) -> dict[str, object]:
    actual = {
        item["name"]: item for item in inspector.get_columns(contract.table)
    }.get(contract.column)
    if actual is None:
        raise C07ProductionMigrationError(
            f"C07 target is missing {contract.table}.{contract.column}"
        )
    raw_type = str(actual["type"]).lower()
    if "bigint" not in raw_type and raw_type != "int8":
        raise C07ProductionMigrationError(
            f"C07 target has non-int8 {contract.table}.{contract.column}"
        )
    if bool(actual["nullable"]) is not contract.nullable:
        raise C07ProductionMigrationError(
            f"C07 target nullability differs for {contract.table}.{contract.column}"
        )
    if actual.get("default") != contract.server_default:
        raise C07ProductionMigrationError(
            f"C07 target server default differs for "
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
    connection: Any,
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
        raise C07ProductionMigrationError(
            f"C07 target CHECK is absent/unvalidated: {contract.table}.{name}"
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
        raise C07ProductionMigrationError(
            f"C07 target CHECK differs: {contract.table}.{name}"
        )
    return {
        "table": contract.table,
        "name": name,
        "expression_sha256": hashlib.sha256(str(row[0]).encode()).hexdigest(),
        "validated": True,
        "no_inherit": False,
    }


def _absent_check_shape(connection: Any, check) -> dict[str, object]:
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
        raise C07ProductionMigrationError(
            f"C07 target retained legacy CHECK {check.table}.{check.name}"
        )
    return {"table": check.table, "name": check.name, "absent": True}


def _money_shape(
    connection: Any,
    *,
    target_revision: str,
) -> dict[str, object]:
    if target_revision != C07_TARGET_REVISION:
        raise C07ProductionMigrationError(
            "C07 target revision has no money shape contract"
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
        raise C07ProductionMigrationError(
            "C07 target money-contract phase is invalid"
        )
    if (
        len(columns) != len(MONEY_COLUMNS_V1)
        or len(checks) != len(MONEY_FINAL_CHECKS_V1)
        or len(absent_checks) != len(MONEY_REMOVED_LEGACY_CHECKS_V1)
    ):
        raise C07ProductionMigrationError(
            "C07 target shape cardinality is invalid"
        )
    shape = {
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
        "shape_sha256": hashlib.sha256(
            (
                json.dumps(
                    shape,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode()
        ).hexdigest(),
        "columns": columns,
        "checks": checks,
        "absent_checks": absent_checks,
    }


def _migrate_or_resume(
    connection: Any,
    *,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
    source_revision: str,
    target_revision: str,
) -> str:
    current = _revision(connection)
    if current == target_revision:
        return "target_observed_after_interruption"
    if current != source_revision:
        raise C07ProductionMigrationError(
            "production database revision is outside the C07 transition"
        )
    source_digest = canonical_money_facts_sha256(
        connection,
        error=C07ProductionMigrationError,
    )
    if source_digest != generation.money_facts_sha256:
        raise C07ProductionMigrationError(
            "live source money facts differ from the recovery generation"
        )
    remaining_seconds = min(
        (
            context.maintenance_deadline_utc - datetime.now(UTC)
        ).total_seconds(),
        context.maintenance_remaining_ceiling_ms / 1000.0,
    )
    if remaining_seconds <= 0:
        raise C07ProductionMigrationError(
            "C07 production whole-operation maintenance window has expired"
        )
    _run_alembic_upgrade(
        connection,
        ceremony_id=context.operation_id,
        deadline=time.monotonic()
        + min(float(MAINTENANCE_WINDOW_SECONDS), remaining_seconds),
    )
    return "target_committed"


def _attest_target_money_facts(
    connection: Any,
    *,
    target_revision: str,
    expected_digest: str,
) -> str:
    if _revision(connection) != target_revision:
        raise C07ProductionMigrationError(
            "production migration did not reach the exact target revision"
        )
    _money_shape(
        connection,
        target_revision=target_revision,
    )
    target_digest = canonical_money_facts_sha256(
        connection,
        error=C07ProductionMigrationError,
    )
    if target_digest != expected_digest:
        raise C07ProductionMigrationError(
            "C07 production migration changed canonical money facts"
        )
    return target_digest


def _persist_cutover_money_facts_seal(
    connection: Any,
    *,
    digest: str,
) -> None:
    connection.execute(
        text(
            "INSERT INTO app_meta (key, value, updated_at) "
            "VALUES (:key, :value, now()) "
            "ON CONFLICT (key) DO UPDATE SET "
            "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
        ),
        {"key": C07_CUTOVER_MONEY_FACTS_KEY, "value": digest},
    )


def _analyze_affected_tables(connection: Any) -> dict[str, object]:
    """Rebuild and verify statistics invalidated by SET DATA TYPE."""

    started_at = connection.scalar(text("SELECT clock_timestamp()"))
    for table in _ANALYZE_TABLES:
        connection.execute(text(f"ANALYZE {_quoted(connection, table)}"))
    connection.execute(text("SELECT pg_stat_clear_snapshot()"))
    rows = {
        str(row[0]): (row[1], int(row[2]))
        for row in connection.execute(
            text(
                "SELECT relname, last_analyze, n_mod_since_analyze "
                "FROM pg_stat_all_tables WHERE schemaname = 'public'"
            )
        )
        if str(row[0]) in _ANALYZE_TABLES
    }
    if set(rows) != set(_ANALYZE_TABLES):
        raise C07ProductionMigrationError(
            "C07 production ANALYZE verification is missing affected tables"
        )
    if any(
        last_analyze is None
        or started_at is None
        or last_analyze < started_at
        or modified_since_analyze != 0
        for last_analyze, modified_since_analyze in rows.values()
    ):
        raise C07ProductionMigrationError(
            "C07 production ANALYZE verification did not reach a clean state"
        )
    return {
        "statistics_table_count": len(_ANALYZE_TABLES),
        "statistics_table_set_sha256": _ANALYZE_TABLE_SET_SHA256,
    }


def _migrate_with_connection(
    connection: Any,
    *,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
    source_revision: str,
    target_revision: str,
) -> dict[str, object]:
    _assert_migrator_principal(connection)
    _assert_production_writer_fence(connection)
    _assume_schema_owner(connection)
    _assert_connected_database(
        connection,
        context=context,
        generation=generation,
    )
    result = _migrate_or_resume(
        connection,
        context=context,
        generation=generation,
        source_revision=source_revision,
        target_revision=target_revision,
    )
    target_money_facts_sha256 = _attest_target_money_facts(
        connection,
        target_revision=target_revision,
        expected_digest=generation.money_facts_sha256,
    )
    statistics = _analyze_affected_tables(connection)
    _persist_cutover_money_facts_seal(
        connection,
        digest=target_money_facts_sha256,
    )
    return {
        "schema": PRODUCTION_MIGRATION_EVIDENCE_SCHEMA,
        "operation_id": context.operation_id,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "result": result,
        "alembic_revision": target_revision,
        "money_facts_sha256": target_money_facts_sha256,
        "statistics_table_count": statistics["statistics_table_count"],
        "statistics_table_set_sha256": statistics[
            "statistics_table_set_sha256"
        ],
    }
