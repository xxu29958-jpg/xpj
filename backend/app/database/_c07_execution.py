"""Alembic execution, target verification, and isolated recovery drill for C07."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import ModuleType

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy import Engine, inspect, text

from app.database._c07_contract import (
    ANALYZE_TABLES as _ANALYZE_TABLES,
)
from app.database._c07_contract import (
    C07_CEREMONY_ID_GUC,
    C07_CEREMONY_MODE_FRESH,
    C07_CEREMONY_MODE_GUC,
    C07_CEREMONY_MODE_MANAGED,
    C07_FRESH_CEREMONY_ID,
    C07_SOURCE_REVISION,
    C07_STATEMENT_TIMEOUT_GUC,
    C07_TARGET_REVISION,
    C07CeremonyError,
)
from app.database._c07_contract import (
    MAINTENANCE_WINDOW_SECONDS as _MAINTENANCE_WINDOW_SECONDS,
)
from app.database._c07_contract import (
    InjectedRollbackError as _InjectedRollbackError,
)
from app.database._c07_contract import (
    canonical_json as _canonical_json,
)
from app.database._c07_contract import (
    canonical_uuid as _canonical_uuid,
)
from app.database._c07_contract import (
    remaining_timeout_seconds as _remaining_timeout_seconds,
)
from app.database._c07_contract import (
    sha256_bytes as _sha256_bytes,
)
from app.database._c07_execution_shape import _money_shape
from app.database._c07_storage import (
    _identity_evidence,
    _pg_restore_archive,
    _public_tables,
    _quoted,
    _table_counts,
)
from app.database._c07_transaction_timeout import c07_prearmed_transaction
from app.money_contract import MONEY_COLUMNS_V1


def _revision(connection) -> str | None:
    if not inspect(connection).has_table("alembic_version"):
        return None
    revisions = tuple(
        connection.scalars(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    )
    if len(revisions) > 1:
        raise C07CeremonyError(
            f"C07 requires exactly one Alembic revision; found {len(revisions)}"
        )
    return None if not revisions else str(revisions[0])


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return config


def _revision_includes_c07(
    revision: str | None,
    *,
    alembic_config: Config | None = None,
) -> bool:
    """Resolve the C07 capability from the revision graph, not today's head."""

    if revision is None:
        return False
    script = ScriptDirectory.from_config(alembic_config or _alembic_config())
    try:
        lineage = script.iterate_revisions(revision, "base")
        return any(item.revision == C07_TARGET_REVISION for item in lineage)
    except RevisionError as exc:
        raise C07CeremonyError(
            f"unable to resolve C07 ancestry for revision {revision!r}"
        ) from exc


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "20260729_0001_money_minor_bigint_expand.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ticketbox_c07_money_expand",
        path,
    )
    if spec is None or spec.loader is None:
        raise C07CeremonyError("unable to load the C07 migration module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def set_c07_migration_context(
    connection,
    *,
    mode: str,
    ceremony_id: str,
    statement_timeout_ms: int | None = None,
) -> None:
    if mode not in {C07_CEREMONY_MODE_FRESH, C07_CEREMONY_MODE_MANAGED}:
        raise C07CeremonyError("unsupported C07 migration mode")
    if mode == C07_CEREMONY_MODE_FRESH:
        if ceremony_id != C07_FRESH_CEREMONY_ID:
            raise C07CeremonyError("fresh C07 migration id is invalid")
    else:
        _canonical_uuid(ceremony_id, label="ceremony_id")
    connection.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": C07_CEREMONY_MODE_GUC, "value": mode},
    )
    connection.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": C07_CEREMONY_ID_GUC, "value": ceremony_id},
    )
    if statement_timeout_ms is not None:
        if not 1 <= statement_timeout_ms <= _MAINTENANCE_WINDOW_SECONDS * 1000:
            raise C07CeremonyError("C07 statement timeout is outside its window")
        connection.execute(
            text("SELECT set_config(:key, :value, true)"),
            {
                "key": C07_STATEMENT_TIMEOUT_GUC,
                "value": str(statement_timeout_ms),
            },
        )


def _run_alembic_upgrade(
    connection,
    *,
    ceremony_id: str,
    deadline: float,
) -> None:
    config = _alembic_config()
    config.attributes["connection"] = connection
    set_c07_migration_context(
        connection,
        mode=C07_CEREMONY_MODE_MANAGED,
        ceremony_id=ceremony_id,
        statement_timeout_ms=int(
            _remaining_timeout_seconds(
                deadline,
                cap_seconds=_MAINTENANCE_WINDOW_SECONDS,
                phase="C07 Alembic upgrade",
            )
            * 1000
        ),
    )
    command.upgrade(config, C07_TARGET_REVISION)


def _analyze_affected_tables(connection) -> dict[str, object]:
    """Rebuild statistics invalidated by SET DATA TYPE and verify completion."""

    started_at = connection.scalar(text("SELECT clock_timestamp()"))
    started = time.perf_counter()
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
        raise C07CeremonyError(
            "C07 ANALYZE verification is missing affected tables"
        )
    if any(
        last_analyze is None
        or started_at is None
        or last_analyze < started_at
        or modified_since_analyze != 0
        for last_analyze, modified_since_analyze in rows.values()
    ):
        raise C07CeremonyError(
            "C07 ANALYZE verification did not reach a clean state"
        )
    return {
        "result": "verified",
        "table_count": len(_ANALYZE_TABLES),
        "table_set_sha256": _sha256_bytes(
            _canonical_json(_ANALYZE_TABLES).encode("utf-8")
        ),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _ensure_restore_target_is_empty(restore_engine: Engine) -> None:
    with restore_engine.connect() as connection:
        object_count = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' "
                    "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
                )
            )
            or 0
        )
    if object_count != 0:
        raise C07CeremonyError(
            "isolated restore target is not empty; refusing destructive cleanup"
        )


def _verify_int4_source_shape(connection) -> None:
    inspector = inspect(connection)
    for contract in MONEY_COLUMNS_V1:
        actual = {
            item["name"]: item
            for item in inspector.get_columns(contract.table)
        }.get(contract.column)
        if actual is None:
            raise C07CeremonyError(
                f"isolated source missing {contract.table}.{contract.column}"
            )
        raw_type = str(actual["type"]).lower()
        if raw_type not in {"integer", "int", "int4"}:
            raise C07CeremonyError(
                f"isolated source is not int4 at "
                f"{contract.table}.{contract.column}"
            )


def _isolated_failure_rollback_drill(
    restore_engine: Engine,
    *,
    ceremony_id: str,
    deadline: float,
) -> int:
    module = _migration_module()
    started = time.perf_counter()
    try:
        timeout_ms = int(
            _remaining_timeout_seconds(
                deadline,
                cap_seconds=_MAINTENANCE_WINDOW_SECONDS,
                phase="isolated rollback drill",
            )
            * 1000
        )
        with restore_engine.connect() as connection, c07_prearmed_transaction(
            connection,
            timeout_ms=timeout_ms,
        ):
            set_c07_migration_context(
                connection,
                mode=C07_CEREMONY_MODE_MANAGED,
                ceremony_id=ceremony_id,
                statement_timeout_ms=timeout_ms,
            )
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                module._acquire_barrier(connection)
                _verify_int4_source_shape(connection)
                module._scan_existing_rows(connection)
                module._widen(connection)
                raise _InjectedRollbackError(
                    "C07 isolated rollback drill"
                )
    except _InjectedRollbackError:
        pass
    with restore_engine.connect() as connection:
        if _revision(connection) != C07_SOURCE_REVISION:
            raise C07CeremonyError(
                "isolated failure drill changed Alembic revision"
            )
        _verify_int4_source_shape(connection)
    return int((time.perf_counter() - started) * 1000)


def _assert_restored_source(
    restore_engine: Engine,
    *,
    source_identity: dict[str, str],
    source_counts: dict[str, int],
) -> None:
    with restore_engine.connect() as connection:
        if _revision(connection) != C07_SOURCE_REVISION:
            raise C07CeremonyError(
                "isolated restore revision does not match C07 source"
            )
        restored_identity = _identity_evidence(connection)
        if restored_identity["logical_digest"] != source_identity["logical_digest"]:
            raise C07CeremonyError(
                "isolated restore logical database identity mismatch"
            )
        if restored_identity["physical_digest"] == source_identity["physical_digest"]:
            raise C07CeremonyError(
                "isolated restore did not use a distinct database"
            )
        restored_counts = _table_counts(connection, _public_tables(connection))
        if restored_counts != source_counts:
            raise C07CeremonyError(
                "isolated restore table counts differ from the snapshot"
            )


def _run_isolated_forward_repair(
    restore_engine: Engine,
    *,
    ceremony_id: str,
    deadline: float,
) -> tuple[int, dict[str, object]]:
    started = time.perf_counter()
    timeout_ms = int(
        _remaining_timeout_seconds(
            deadline,
            cap_seconds=_MAINTENANCE_WINDOW_SECONDS,
            phase="isolated forward repair",
        )
        * 1000
    )
    with restore_engine.connect() as connection, c07_prearmed_transaction(
        connection,
        timeout_ms=timeout_ms,
    ):
        _run_alembic_upgrade(
            connection,
            ceremony_id=ceremony_id,
            deadline=deadline,
        )
        if _revision(connection) != C07_TARGET_REVISION:
            raise C07CeremonyError(
                "isolated forward repair did not reach C07 target"
            )
        shape = _money_shape(connection, target_revision=C07_TARGET_REVISION)
    return int((time.perf_counter() - started) * 1000), shape


def _isolated_restore_and_forward_drill(
    *,
    restore_engine: Engine,
    restore_url: str,
    dump_path: Path,
    source_identity: dict[str, str],
    source_counts: dict[str, int],
    ceremony_id: str,
    deadline: float,
) -> dict[str, object]:
    _ensure_restore_target_is_empty(restore_engine)
    restore_elapsed_ms = _pg_restore_archive(
        dump_path,
        restore_url,
        deadline=deadline,
    )
    _assert_restored_source(
        restore_engine,
        source_identity=source_identity,
        source_counts=source_counts,
    )
    rollback_elapsed_ms = _isolated_failure_rollback_drill(
        restore_engine,
        ceremony_id=ceremony_id,
        deadline=deadline,
    )
    forward_elapsed_ms, shape = _run_isolated_forward_repair(
        restore_engine,
        ceremony_id=ceremony_id,
        deadline=deadline,
    )
    return {
        "restore_elapsed_ms": restore_elapsed_ms,
        "rollback_drill_elapsed_ms": rollback_elapsed_ms,
        "forward_repair_elapsed_ms": forward_elapsed_ms,
        "failure_rollback_verified": True,
        "forward_repair_verified": True,
        "logical_identity_matched": True,
        "physical_database_isolated": True,
        "table_count": len(source_counts),
        "total_rows": sum(source_counts.values()),
        "row_count_digest": _sha256_bytes(
            _canonical_json(source_counts).encode("utf-8")
        ),
        "target_shape_sha256": shape["shape_sha256"],
    }


def c07_managed_upgrade_required(
    *,
    current_revision: str | None,
    target_revision: str,
    alembic_config: Config | None = None,
) -> bool:
    """Return whether an ordinary managed startup would cross C07."""

    return (
        current_revision is not None
        and _revision_includes_c07(
            target_revision,
            alembic_config=alembic_config,
        )
        and not _revision_includes_c07(
            current_revision,
            alembic_config=alembic_config,
        )
    )
