"""Validate and execute the build-owned database generation program."""

from __future__ import annotations

from pathlib import Path

from app.database._database_generation_program import (
    DatabaseGenerationProgramError,
    load_database_generation_program,
)
from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
    PostgresOperationFailureError,
)

RESULT_SCHEMA = "ticketbox-managed-schema-upgrade-result-v2"
_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000


class ManagedSchemaUpgradeError(RuntimeError):
    """The frozen helper cannot prove or execute the generation program."""


def run_managed_schema_upgrade_action(
    *,
    database_url: str,
    pgpassfile: Path,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    source_revision: str,
    target_revision: str,
    generation_operation_id: str,
) -> dict[str, object]:
    try:
        program = load_database_generation_program(
            path=generation_program_path,
            expected_sha256=expected_generation_program_sha256,
        )
    except DatabaseGenerationProgramError as exc:
        raise ManagedSchemaUpgradeError(
            "database generation program validation failed"
        ) from exc
    if target_revision != program.target_revision:
        raise ManagedSchemaUpgradeError(
            "managed schema target differs from the generation program"
        )
    runtime = ManagedPostgresMigrationRuntimeV1(
        ManagedPostgresRuntimeContractV1(
            database_name=DATABASE_NAME,
            migrator_role=MIGRATOR_ROLE,
            schema_owner_role=SCHEMA_OWNER_ROLE,
            lease_label=MIGRATION_LEASE_LABEL,
            transaction_timeout_ms=_TRANSACTION_TIMEOUT_MS,
        )
    )
    try:
        result = runtime.run(
            database_url=database_url,
            pgpassfile=pgpassfile,
            program=program,
            source_revision=source_revision,
            target_revision=target_revision,
            generation_operation_id=generation_operation_id,
        )
    except (ManagedPostgresMigrationRuntimeError, PostgresOperationFailureError) as exc:
        raise ManagedSchemaUpgradeError(
            "managed schema PostgreSQL action failed"
        ) from exc
    return {
        "schema": RESULT_SCHEMA,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "generation_program_sha256": program.payload_sha256,
        "result": result,
        "alembic_revision": target_revision,
    }


__all__ = [
    "ManagedSchemaUpgradeError",
    "run_managed_schema_upgrade_action",
]
