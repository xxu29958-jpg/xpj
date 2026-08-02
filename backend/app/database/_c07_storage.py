"""PostgreSQL writer barrier, capacity, backup, and restore preflight for C07."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.database._c07_contract import (
    MIGRATION_LEASE_LABEL as _MIGRATION_LEASE_LABEL,
)
from app.database._c07_contract import (
    PG_RESTORE_TIMEOUT_SECONDS as _PG_RESTORE_TIMEOUT_SECONDS,
)
from app.database._c07_contract import (
    SPACE_HEADROOM_FACTOR as _SPACE_HEADROOM_FACTOR,
)
from app.database._c07_contract import (
    BackupEvidence,
    C07CeremonyError,
    DiskBudget,
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
from app.database._c07_contract import (
    sha256_file as _sha256_file,
)
from app.money_contract import MONEY_COLUMNS_V1
from app.services import backup_service
from app.services.postgres_backup_validation_service import find_pg_binary


def _identity_evidence(connection) -> dict[str, str]:
    rows = dict(
        connection.execute(
            text(
                "SELECT key, value FROM app_meta "
                "WHERE key IN ('server_id', 'data_generation')"
            )
        ).all()
    )
    logical = {
        "server_id": _canonical_uuid(rows.get("server_id"), label="server_id"),
        "data_generation": _canonical_uuid(
            rows.get("data_generation"),
            label="data_generation",
        ),
    }
    physical = connection.execute(
        text(
            "SELECT current_database(), d.oid::text, "
            "COALESCE(inet_server_addr()::text, 'local-socket'), "
            "COALESCE(inet_server_port(), 0)::text, "
            "current_setting('server_version_num') "
            "FROM pg_database d WHERE d.datname = current_database()"
        )
    ).one()
    return {
        "logical_digest": _sha256_bytes(
            ("ticketbox:c07:logical:" + _canonical_json(logical)).encode("utf-8")
        ),
        "physical_digest": _sha256_bytes(
            (
                "ticketbox:c07:physical:"
                + _canonical_json(
                    {
                        "database": str(physical[0]),
                        "oid": str(physical[1]),
                        "server_address": str(physical[2]),
                        "server_port": str(physical[3]),
                        "server_version_num": str(physical[4]),
                    }
                )
            ).encode("utf-8")
        ),
    }


def _quoted(connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(identifier)


def _public_tables(connection) -> tuple[str, ...]:
    return tuple(
        connection.scalars(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        )
    )


def _table_counts(connection, tables: tuple[str, ...]) -> dict[str, int]:
    return {
        table: int(
            connection.scalar(
                text(f"SELECT count(*) FROM {_quoted(connection, table)}")
            )
            or 0
        )
        for table in tables
    }


def _relation_metrics(connection) -> list[dict[str, int | str]]:
    metrics: list[dict[str, int | str]] = []
    for table in sorted({column.table for column in MONEY_COLUMNS_V1}):
        row = connection.execute(
            text(
                "SELECT c.reltuples::bigint, "
                "pg_relation_size(c.oid), pg_indexes_size(c.oid), "
                "pg_total_relation_size(c.oid) "
                "FROM pg_class c "
                "WHERE c.oid = CAST(:relation AS regclass)"
            ),
            {"relation": f"public.{table}"},
        ).one()
        metrics.append(
            {
                "table": table,
                "estimated_rows": int(row[0]),
                "relation_bytes": int(row[1]),
                "index_bytes": int(row[2]),
                "total_bytes": int(row[3]),
            }
        )
    return metrics


def _volume_digest(path: Path) -> tuple[int, str]:
    device = int(path.stat().st_dev)
    digest = _sha256_bytes(f"ticketbox:c07:volume:{device}".encode())
    return device, digest


def _disk_budget(
    connection,
    backup_dir: Path,
    *,
    postgres_data_directory: Path,
) -> DiskBudget:
    database_size = int(
        connection.scalar(text("SELECT pg_database_size(current_database())"))
    )
    if database_size <= 0:
        raise C07CeremonyError("pg_database_size returned an invalid value")
    if (
        not postgres_data_directory.is_absolute()
        or not postgres_data_directory.is_dir()
    ):
        raise C07CeremonyError(
            "host-authoritative PostgreSQL data directory is unavailable"
        )
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_usage = shutil.disk_usage(backup_dir)
        data_usage = shutil.disk_usage(postgres_data_directory)
        backup_device, backup_digest = _volume_digest(backup_dir)
        data_device, data_digest = _volume_digest(postgres_data_directory)
    except OSError as exc:
        raise C07CeremonyError(
            "unable to prove backup/data volume free space"
        ) from exc
    estimated_dump = database_size
    declared_scratch = database_size
    same_volume = backup_device == data_device
    if same_volume:
        combined = math.ceil(
            (estimated_dump + declared_scratch) * _SPACE_HEADROOM_FACTOR
        )
        backup_required = combined
        data_required = combined
        enough = min(backup_usage.free, data_usage.free) >= combined
    else:
        backup_required = math.ceil(estimated_dump * _SPACE_HEADROOM_FACTOR)
        data_required = math.ceil(declared_scratch * _SPACE_HEADROOM_FACTOR)
        enough = (
            backup_usage.free >= backup_required
            and data_usage.free >= data_required
        )
    if not enough:
        raise C07CeremonyError(
            "C07 disk preflight refused: free bytes are below "
            "dump/scratch/headroom budget"
        )
    return DiskBudget(
        database_size_bytes=database_size,
        estimated_dump_bytes=estimated_dump,
        declared_scratch_bytes=declared_scratch,
        same_volume=same_volume,
        backup_free_bytes=int(backup_usage.free),
        backup_required_bytes=backup_required,
        data_free_bytes=int(data_usage.free),
        data_required_bytes=data_required,
        backup_volume_digest=backup_digest,
        data_volume_digest=data_digest,
    )


def _active_client_sessions(connection) -> list[dict[str, object]]:
    # PostgreSQL can cache statistics for the duration of a transaction.
    # C07 uses repeated session checks around a long writer barrier, so every
    # decision must start from a fresh collector snapshot.
    connection.execute(text("SELECT pg_stat_clear_snapshot()"))
    rows = connection.execute(
        text(
            "SELECT state, backend_xid IS NOT NULL, wait_event_type "
            "FROM pg_stat_activity "
            "WHERE datid = (SELECT oid FROM pg_database "
            "WHERE datname = current_database()) "
            "AND pid <> pg_backend_pid() "
            "AND backend_type = 'client backend' "
            "ORDER BY pid"
        )
    ).all()
    return [
        {
            "state": str(row[0] or "unknown"),
            "has_transaction_id": bool(row[1]),
            "wait_event_type": str(row[2] or "none"),
        }
        for row in rows
    ]


def _acquire_writer_barrier(
    connection,
    *,
    deadline: float,
) -> tuple[tuple[str, ...], int]:
    """Fence every existing application table before taking the dump snapshot.

    The caller intentionally uses READ COMMITTED.  Catalog inspection and the
    advisory-lock statement may therefore take short-lived snapshots, but the
    snapshot later exported to pg_dump is created only after the SHARE locks
    have waited for all earlier writers.  A REPEATABLE READ transaction here
    would freeze its snapshot before the table locks and could omit a writer
    that committed while the locks were being acquired.
    """

    started = time.perf_counter()
    connection.execute(text("SET LOCAL lock_timeout = '30s'"))
    timeout_ms = max(
        1,
        int(
            _remaining_timeout_seconds(
                deadline,
                cap_seconds=_PG_RESTORE_TIMEOUT_SECONDS,
                phase="PostgreSQL writer barrier",
            )
            * 1000
        ),
    )
    for setting in (
        "statement_timeout",
        "transaction_timeout",
        "idle_in_transaction_session_timeout",
    ):
        connection.execute(
            text("SELECT set_config(:setting, :value, true)"),
            {"setting": setting, "value": f"{timeout_ms}ms"},
        )
    locked = connection.scalar(
        text(
            "SELECT pg_try_advisory_xact_lock("
            "hashtext(current_database()), hashtext(:label))"
        ),
        {"label": _MIGRATION_LEASE_LABEL},
    )
    if locked is not True:
        raise C07CeremonyError("C07 migration advisory lease is busy")
    tables = _public_tables(connection)
    if tables:
        quoted = ", ".join(_quoted(connection, table) for table in tables)
        connection.execute(text(f"LOCK TABLE {quoted} IN SHARE MODE"))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    sessions = _active_client_sessions(connection)
    if sessions:
        raise C07CeremonyError(
            "C07 writer barrier found another client session after host freeze"
        )
    return tables, elapsed_ms


def _backup_evidence(
    *,
    source_url: str,
    exported_snapshot: str,
    deadline: float,
) -> tuple[BackupEvidence, Path]:
    started = time.perf_counter()
    entry = backup_service.create_c07_pre_upgrade_backup(
        database_url=source_url,
        exported_snapshot=exported_snapshot,
    )
    dump_path = backup_service._backup_dir() / entry.file_name  # noqa: SLF001
    restore_binary = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not restore_binary:
        raise C07CeremonyError(
            "pg_restore is unavailable for C07 archive validation"
        )
    try:
        timeout = _remaining_timeout_seconds(
            deadline,
            cap_seconds=60,
            phase="pg_restore archive listing",
        )
        result = subprocess.run(  # noqa: S603
            [restore_binary, "--list", str(dump_path)],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise C07CeremonyError("pg_restore --list could not complete") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise C07CeremonyError("pg_restore --list rejected the C07 archive")
    toc_lines = tuple(
        line
        for line in result.stdout.splitlines()
        if line and not line.startswith(";")
    )
    return (
        BackupEvidence(
            file_name=entry.file_name,
            sha256=_sha256_file(dump_path),
            size_bytes=int(dump_path.stat().st_size),
            toc_sha256=_sha256_bytes(result.stdout.encode("utf-8")),
            toc_entry_count=len(toc_lines),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        ),
        dump_path,
    )


def _pg_restore_archive(
    dump_path: Path,
    restore_url: str,
    *,
    deadline: float,
) -> int:
    binary = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not binary:
        raise C07CeremonyError("pg_restore is unavailable for the isolated drill")
    connection = backup_service._pg_tool_connection(restore_url)  # noqa: SLF001
    started = time.perf_counter()
    timeout = _remaining_timeout_seconds(
        deadline,
        cap_seconds=_PG_RESTORE_TIMEOUT_SECONDS,
        phase="isolated pg_restore",
    )
    with backup_service._pg_tool_environment(connection) as environment:  # noqa: SLF001
        try:
            result = subprocess.run(  # noqa: S603
                [
                    binary,
                    "--no-password",
                    "--dbname",
                    connection.database_url,
                    "--no-owner",
                    "--exit-on-error",
                    str(dump_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise C07CeremonyError(
                "isolated pg_restore could not complete"
            ) from exc
    if result.returncode != 0:
        raise C07CeremonyError(
            f"isolated pg_restore failed with exit code {result.returncode}"
        )
    return int((time.perf_counter() - started) * 1000)


def _source_and_restore_urls_are_distinct(
    source_url: str,
    restore_url: str,
) -> None:
    source = make_url(source_url)
    restore = make_url(restore_url)
    if (
        source.get_backend_name() != "postgresql"
        or restore.get_backend_name() != "postgresql"
    ):
        raise C07CeremonyError(
            "C07 ceremony requires PostgreSQL source and restore URLs"
        )
    if (
        source.host,
        source.port or 5432,
        source.database,
    ) == (
        restore.host,
        restore.port or 5432,
        restore.database,
    ):
        raise C07CeremonyError(
            "isolated restore database must differ from the source"
        )


def _disk_budget_payload(budget: DiskBudget) -> dict[str, object]:
    return {
        "database_size_bytes": budget.database_size_bytes,
        "estimated_dump_bytes": budget.estimated_dump_bytes,
        "declared_scratch_bytes": budget.declared_scratch_bytes,
        "headroom_percent": 20,
        "same_volume": budget.same_volume,
        "backup_free_bytes": budget.backup_free_bytes,
        "backup_required_bytes": budget.backup_required_bytes,
        "data_free_bytes": budget.data_free_bytes,
        "data_required_bytes": budget.data_required_bytes,
        "backup_volume_digest": budget.backup_volume_digest,
        "data_volume_digest": budget.data_volume_digest,
        "result": "sufficient",
    }


def _backup_payload(backup: BackupEvidence) -> dict[str, object]:
    return {
        "archive_name": backup.file_name,
        "sha256": backup.sha256,
        "size_bytes": backup.size_bytes,
        "pg_restore_list_sha256": backup.toc_sha256,
        "pg_restore_list_entry_count": backup.toc_entry_count,
        "elapsed_ms": backup.elapsed_ms,
        "format": "custom",
        "result": "verified",
    }
