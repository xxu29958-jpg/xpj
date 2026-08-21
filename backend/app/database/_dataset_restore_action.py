"""One-shot isolated restore action for a complete H2 backup generation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import text

from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresRuntimeContractV1,
    _create_engine,
    _temporary_pgpass_environment,
    _validated_migrator_url,
)
from app.database._postgres_operation_failures import (
    close_postgres_owner_resources,
    raise_postgres_operation_failures,
)
from app.errors import AppError
from app.services.dataset_backup_contract import DATABASE_ARCHIVE_NAME, read_manifest
from app.services.dataset_restore_service import (
    CompleteRestoreRequest,
    assert_restored_dataset_candidate,
    finalize_restored_dataset,
    materialize_restored_originals,
    resolve_restored_dataset_plan,
)
from app.services.postgres_backup_adapter import restore_postgres_archive
from app.services.secure_file import hold_protected_file_for_read

RESULT_FIELDS = (
    "schema",
    "backup_id",
    "dataset_id",
    "restore_epoch",
    "schema_revision",
    "original_count",
    "result",
)


def run_isolated_dataset_restore_action(request: CompleteRestoreRequest) -> dict[str, object]:
    source = read_manifest(request.backup_generation, verify_files=True)
    if source.authority.schema_revision != request.target_schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    plan = resolve_restored_dataset_plan(
        source,
        active_dataset_id=request.active_dataset_id,
        active_restore_epoch=request.active_restore_epoch,
        target_schema_revision=request.target_schema_revision,
        clone_dataset_id=request.clone_dataset_id,
    )
    contract = ManagedPostgresRuntimeContractV1(
        database_name=DATABASE_NAME,
        migrator_role=MIGRATOR_ROLE,
        schema_owner_role=SCHEMA_OWNER_ROLE,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=20 * 60 * 1000,
    )
    parsed_url = _validated_migrator_url(request.database_url, contract=contract)
    engine = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    entered: list[AbstractContextManager[Any]] = []
    database_contexts: list[AbstractContextManager[Any]] = []
    result: dict[str, object] | None = None
    try:
        protected = hold_protected_file_for_read(request.passfile)
        protected_passfile = protected.__enter__()
        entered.append(protected)
        environment = _temporary_pgpass_environment(protected_passfile)
        environment.__enter__()
        entered.append(environment)
        engine = _create_engine(parsed_url)
        connection_context = engine.connect()
        connection = connection_context.__enter__()
        database_contexts.append(connection_context)
        relation_count = connection.scalar(
            text(
                "SELECT count(*) FROM pg_class AS relation "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
            )
        )
        if relation_count != 0:
            assert_restored_dataset_candidate(
                connection,
                source=source,
                plan=plan,
            )
        phase_cleanup: list[BaseException] = []
        phase_primary = close_postgres_owner_resources(
            contexts=database_contexts,
            engine=engine,
            primary=None,
            cleanup=phase_cleanup,
        )
        database_contexts.clear()
        engine = None
        raise_postgres_operation_failures(
            primary=phase_primary,
            cleanup=phase_cleanup,
            message="isolated dataset restore probe cleanup failed",
        )

        if relation_count == 0:
            restore_postgres_archive(
                database_url=request.database_url,
                passfile=request.passfile,
                pg_restore_binary=request.pg_restore_binary,
                archive=request.backup_generation / DATABASE_ARCHIVE_NAME,
                restore_role=request.restore_role,
            )
        materialize_restored_originals(
            request.backup_generation,
            target_upload_root=request.target_upload_root,
        )

        engine = _create_engine(parsed_url)
        transaction_context = engine.begin()
        connection = transaction_context.__enter__()
        database_contexts.append(transaction_context)
        connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
        finalize_restored_dataset(connection, source=source, plan=plan)
        result = {
            "schema": "ticketbox-isolated-dataset-restore-result-v1",
            "backup_id": source.backup_id,
            "dataset_id": plan.dataset_id,
            "restore_epoch": plan.restore_epoch,
            "schema_revision": plan.schema_revision,
            "original_count": len(source.originals),
            "result": "isolated_restore_candidate_ready",
        }
    except BaseException as exc:  # noqa: BLE001 - owner boundary preserves primary failure
        primary = exc
    finally:
        primary = close_postgres_owner_resources(
            contexts=database_contexts,
            engine=engine,
            primary=primary,
            cleanup=cleanup,
        )
        primary = close_postgres_owner_resources(
            contexts=entered,
            engine=None,
            primary=primary,
            cleanup=cleanup,
        )
    raise_postgres_operation_failures(
        primary=primary,
        cleanup=cleanup,
        message="isolated dataset restore action failed",
    )
    if result is None:
        raise RuntimeError("isolated dataset restore returned no result")
    return result


__all__ = ["RESULT_FIELDS", "run_isolated_dataset_restore_action"]
