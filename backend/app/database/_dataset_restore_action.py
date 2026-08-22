"""One-shot isolated restore action for a complete H2 backup generation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database._database_generation_target_verification import (
    run_database_generation_target_verification_action,
)
from app.database._dataset_restore_authority import (
    assert_restored_dataset_candidate_accepted,
    finalize_restored_dataset,
)
from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresRuntimeContractV1,
    _create_engine,
    _prearmed_transaction,
    _temporary_pgpass_environment,
    _validated_migrator_url,
)
from app.database._managed_postgres_role_authority import (
    assume_managed_postgres_schema_owner,
)
from app.database._postgres_operation_failures import (
    close_postgres_owner_resources,
    raise_postgres_operation_failures,
)
from app.errors import AppError
from app.services.dataset_backup_contract import DATABASE_ARCHIVE_NAME, DatasetBackupManifest, read_manifest
from app.services.dataset_restore_service import (
    CompleteRestoreRequest,
    RestoredDatasetPlan,
    materialize_restored_originals,
    resolve_restored_dataset_plan,
    verify_restored_originals,
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
    "generation_program_sha256",
    "resource_shape_sha256",
    "money_facts_sha256",
    "result",
)
RUNTIME_VERIFICATION_FIELDS = (
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
        active_installation_id=request.active_installation_id,
        active_dataset_id=request.active_dataset_id,
        active_restore_epoch=request.active_restore_epoch,
        target_schema_revision=request.target_schema_revision,
    )
    contract = ManagedPostgresRuntimeContractV1(
        database_name=DATABASE_NAME,
        migrator_role=MIGRATOR_ROLE,
        schema_owner_role=SCHEMA_OWNER_ROLE,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=20 * 60 * 1000,
    )
    parsed_url = _validated_migrator_url(request.database_url, contract=contract)
    return _execute_isolated_restore(request, source=source, plan=plan, parsed_url=parsed_url)


def _execute_isolated_restore(
    request: CompleteRestoreRequest,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
    parsed_url: object,
) -> dict[str, object]:
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
        _reset_restore_target(
            engine,
            contexts=database_contexts,
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

        _materialize_restore_payload(request)
        engine = _create_engine(parsed_url)
        result = _publish_restore_candidate(
            engine,
            contexts=database_contexts,
            source=source,
            plan=plan,
        )
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
        raise AppError("backup_incomplete", status_code=500)
    return result


def _reset_restore_target(
    engine: Any,
    *,
    contexts: list[AbstractContextManager[Any]],
) -> None:
    transaction_context = engine.begin()
    connection = transaction_context.__enter__()
    contexts.append(transaction_context)
    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    foreign_schema_count = connection.scalar(
        text(
            "SELECT count(*) FROM pg_namespace "
            "WHERE nspname <> 'public' "
            "AND nspname <> 'information_schema' "
            "AND nspname !~ '^pg_'"
        )
    )
    if foreign_schema_count != 0:
        raise AppError("backup_incomplete", status_code=409)
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text(f'CREATE SCHEMA public AUTHORIZATION "{SCHEMA_OWNER_ROLE}"'))


def _materialize_restore_payload(
    request: CompleteRestoreRequest,
) -> None:
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


def _publish_restore_candidate(
    engine: Any,
    *,
    contexts: list[AbstractContextManager[Any]],
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> dict[str, object]:
    transaction_context = engine.begin()
    connection = transaction_context.__enter__()
    contexts.append(transaction_context)
    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    finalize_restored_dataset(connection, source=source, plan=plan)
    return {
        "schema": "ticketbox-isolated-dataset-restore-result-v1",
        "backup_id": source.backup_id,
        "dataset_id": plan.dataset_id,
        "restore_epoch": plan.restore_epoch,
        "schema_revision": plan.schema_revision,
        "original_count": len(source.originals),
        "result": "isolated_restore_candidate_ready",
    }


def verify_restored_originals_action(
    backup_generation: Path,
    restored_upload_root: Path,
) -> dict[str, object]:
    """Re-read stable restored originals against the immutable backup manifest."""

    source = read_manifest(backup_generation, verify_files=True)
    verify_restored_originals(source, backup_generation, restored_upload_root)
    return {
        "schema": "ticketbox-restored-originals-verification-v1",
        "backup_id": source.backup_id,
        "dataset_id": source.authority.dataset_id,
        "restore_epoch": source.authority.restore_epoch,
        "schema_revision": source.authority.schema_revision,
        "original_count": len(source.originals),
        "result": "restored_originals_verified",
    }


def _verify_restored_dataset_candidate(
    request: CompleteRestoreRequest,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    verify_restored_originals(source, request.backup_generation, request.target_upload_root)
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
        entered.append(connection_context)
        with _prearmed_transaction(
            connection,
            timeout_ms=contract.transaction_timeout_ms,
            access_mode="read_only",
        ):
            assume_managed_postgres_schema_owner(connection, contract=contract)
            assert_restored_dataset_candidate_accepted(connection, plan=plan)
    except BaseException as exc:  # noqa: BLE001 - preserve verifier owner failure
        primary = exc
    finally:
        primary = close_postgres_owner_resources(
            contexts=entered,
            engine=engine,
            primary=primary,
            cleanup=cleanup,
        )
    raise_postgres_operation_failures(
        primary=primary,
        cleanup=cleanup,
        message="restored dataset candidate verification failed",
    )


def run_verified_isolated_dataset_restore_action(
    *,
    request: CompleteRestoreRequest,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    operation_id: str,
) -> dict[str, object]:
    """Restore and fully accept one isolated candidate before returning success."""

    restored = run_isolated_dataset_restore_action(request)
    target = run_database_generation_target_verification_action(
        database_url=request.database_url,
        pgpassfile=request.passfile,
        generation_program_path=generation_program_path,
        expected_generation_program_sha256=expected_generation_program_sha256,
        operation_id=operation_id,
        database=DATABASE_NAME,
        restore_attempt_id="",
        target_revision=request.target_schema_revision,
    )
    source = read_manifest(request.backup_generation, verify_files=True)
    plan = resolve_restored_dataset_plan(
        source,
        active_installation_id=request.active_installation_id,
        active_dataset_id=request.active_dataset_id,
        active_restore_epoch=request.active_restore_epoch,
        target_schema_revision=request.target_schema_revision,
    )
    _verify_restored_dataset_candidate(request, source=source, plan=plan)
    return {
        "schema": "ticketbox-isolated-dataset-restore-result-v2",
        "backup_id": restored["backup_id"],
        "dataset_id": restored["dataset_id"],
        "restore_epoch": restored["restore_epoch"],
        "schema_revision": restored["schema_revision"],
        "original_count": restored["original_count"],
        "generation_program_sha256": target["generation_program_sha256"],
        "resource_shape_sha256": target["resource_shape_sha256"],
        "money_facts_sha256": target["money_facts_sha256"],
        "result": "isolated_restore_candidate_verified",
    }


__all__ = [
    "RESULT_FIELDS",
    "RUNTIME_VERIFICATION_FIELDS",
    "assert_restored_dataset_candidate_accepted",
    "finalize_restored_dataset",
    "run_isolated_dataset_restore_action",
    "run_verified_isolated_dataset_restore_action",
    "verify_restored_originals_action",
]
