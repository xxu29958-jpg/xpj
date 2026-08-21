"""One-shot isolated restore action for a complete H2 backup generation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

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
_SANITATION_TABLES = (
    "desktop_activation_attempts",
    "session_refresh_attempts",
    "auth_tokens",
    "device_enrollment_attempts",
    "installation_owner_claims",
    "bootstrap_secret_consumptions",
    "upload_link_daily_usage",
    "upload_link_remote_attempts",
    "upload_links",
    "pairing_attempt_failures",
    "pairing_codes",
    "invitations",
    "installation_idempotency_keys",
    "scheduler_leases",
    "budget_advisor_quota_locks",
    "ai_transaction_temp_id_map",
)


def assert_restored_dataset_candidate(
    connection: Connection,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    """Accept only the source snapshot or this request's finalized candidate."""

    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) not in (_source_authority_shape(source), _planned_authority_shape(plan)):
        raise AppError("backup_incomplete", status_code=409)


def finalize_restored_dataset(
    connection: Connection,
    *,
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> None:
    """Sanitize host credentials and publish Dataset Authority in one DB transaction."""

    alembic_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if alembic_revision != plan.schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    observed = (
        connection.execute(
            text(
                "SELECT dataset_id, restore_epoch, schema_revision, "
                "client_generation, schema_min_compatible, semantic_revision, restored_from_backup_id "
                "FROM dataset_authority WHERE singleton_id = 1 FOR UPDATE"
            )
        )
        .mappings()
        .one()
    )
    if dict(observed) == _planned_authority_shape(plan):
        return
    if dict(observed) != _source_authority_shape(source):
        raise AppError("backup_incomplete", status_code=409)
    for table in _SANITATION_TABLES:
        connection.execute(text(f'DELETE FROM "{table}"'))
    connection.execute(
        text(
            "DELETE FROM app_meta WHERE key IN "
            "('csrf_signing_key', 'database_generation_binding', 'budget_advisor_audit_key')"
        )
    )
    connection.execute(
        text(
            "UPDATE dataset_authority SET dataset_id = :dataset_id, "
            "client_generation = :client_generation, restore_epoch = :restore_epoch, "
            "schema_revision = :schema_revision, schema_min_compatible = :schema_min_compatible, "
            "semantic_revision = :semantic_revision, "
            "restored_from_backup_id = :backup_id WHERE singleton_id = 1"
        ),
        {
            "dataset_id": plan.dataset_id,
            "client_generation": plan.client_generation,
            "restore_epoch": plan.restore_epoch,
            "schema_revision": plan.schema_revision,
            "schema_min_compatible": plan.schema_min_compatible,
            "semantic_revision": plan.semantic_revision,
            "backup_id": plan.restored_from_backup_id,
        },
    )


def _source_authority_shape(source: DatasetBackupManifest) -> dict[str, object]:
    authority = source.authority
    return {
        "dataset_id": authority.dataset_id,
        "client_generation": authority.client_generation,
        "restore_epoch": authority.restore_epoch,
        "schema_revision": authority.schema_revision,
        "schema_min_compatible": authority.schema_min_compatible,
        "semantic_revision": authority.semantic_revision,
        "restored_from_backup_id": authority.restored_from_backup_id,
    }


def _planned_authority_shape(plan: RestoredDatasetPlan) -> dict[str, object]:
    return {
        "dataset_id": plan.dataset_id,
        "client_generation": plan.client_generation,
        "restore_epoch": plan.restore_epoch,
        "schema_revision": plan.schema_revision,
        "schema_min_compatible": plan.schema_min_compatible,
        "semantic_revision": plan.semantic_revision,
        "restored_from_backup_id": plan.restored_from_backup_id,
    }


def run_isolated_dataset_restore_action(request: CompleteRestoreRequest) -> dict[str, object]:
    source = read_manifest(request.backup_generation, verify_files=True)
    if source.authority.schema_revision != request.target_schema_revision:
        raise AppError("backup_incomplete", status_code=409)
    plan = resolve_restored_dataset_plan(
        source,
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
        relation_count = _probe_restore_target(
            engine,
            contexts=database_contexts,
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

        _materialize_restore_payload(
            request,
            target_is_empty=relation_count == 0,
        )
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


def _probe_restore_target(
    engine: Any,
    *,
    contexts: list[AbstractContextManager[Any]],
    source: DatasetBackupManifest,
    plan: RestoredDatasetPlan,
) -> int:
    connection_context = engine.connect()
    connection = connection_context.__enter__()
    contexts.append(connection_context)
    relation_count = connection.scalar(
        text(
            "SELECT count(*) FROM pg_class AS relation "
            "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
            "WHERE namespace.nspname = 'public' "
            "AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
        )
    )
    if relation_count != 0:
        assert_restored_dataset_candidate(connection, source=source, plan=plan)
    return int(relation_count)


def _materialize_restore_payload(
    request: CompleteRestoreRequest,
    *,
    target_is_empty: bool,
) -> None:
    if target_is_empty:
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


__all__ = [
    "RESULT_FIELDS",
    "RUNTIME_VERIFICATION_FIELDS",
    "assert_restored_dataset_candidate",
    "finalize_restored_dataset",
    "run_isolated_dataset_restore_action",
    "verify_restored_originals_action",
]
