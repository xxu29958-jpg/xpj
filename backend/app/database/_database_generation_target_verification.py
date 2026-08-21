"""Read-only semantic proof for one build-owned database generation target."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from app.canonical_money_facts import canonical_money_facts_sha256
from app.database._database_generation_program import (
    DatabaseGenerationProgramError,
    load_database_generation_program,
)
from app.database._managed_postgres_contract import (
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresRuntimeContractV1,
    _create_engine,
    _prearmed_transaction,
    _temporary_pgpass_environment,
    _validated_migrator_url,
)
from app.database._managed_postgres_role_authority import (
    assume_managed_postgres_schema_owner,
)
from app.database._money_schema_attestation import (
    MoneySchemaAttestationError,
    read_money_schema_shape,
)
from app.database._postgres_operation_failures import (
    close_postgres_owner_resources,
    raise_postgres_operation_failures,
)
from app.database._release_schema_readiness import (
    ReleaseHeadVerificationError,
    assert_release_head,
)
from app.services.secure_file import hold_protected_file_for_read

RESULT_SCHEMA = "ticketbox-database-generation-target-verification-v2"
LIVE_DATABASE = "ticketbox"
RESTORE_PREFIX = "ticketbox_generation_restore_"
_RESTORE_DATABASE = re.compile(rf"{RESTORE_PREFIX}[0-9a-f]{{32}}\Z")
_TIMEOUT_MS = 20 * 60 * 1000
class DatabaseGenerationTargetVerificationError(RuntimeError):
    """The frozen helper could not prove the requested target."""


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatabaseGenerationTargetVerificationError(f"{label} is invalid") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise DatabaseGenerationTargetVerificationError(f"{label} is not canonical")
    return value


def _restore_database_name(operation_id: str, attempt_id: str) -> str:
    _canonical_uuid(operation_id, label="generation operation id")
    attempt = _canonical_uuid(attempt_id, label="restore attempt id")
    database = RESTORE_PREFIX + UUID(attempt).hex
    if _RESTORE_DATABASE.fullmatch(database) is None:
        raise AssertionError("generation restore database naming drifted")
    return database


def _validated_database(
    database: str,
    *,
    operation_id: str,
    restore_attempt_id: str,
) -> str:
    expected = LIVE_DATABASE if not restore_attempt_id else _restore_database_name(operation_id, restore_attempt_id)
    if database != expected:
        raise DatabaseGenerationTargetVerificationError("target verification database is outside the exact operation")
    return expected


def _read_target_facts(
    *,
    parsed_url: URL,
    pgpassfile: Path,
    contract: ManagedPostgresRuntimeContractV1,
    target_revision: str,
) -> tuple[str, str, str]:
    engine = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    facts: tuple[str, str, str] | None = None
    entered_contexts: list[AbstractContextManager[Any]] = []
    try:
        protected_context = hold_protected_file_for_read(pgpassfile)
        protected_pgpass = protected_context.__enter__()
        entered_contexts.append(protected_context)
        environment_context = _temporary_pgpass_environment(protected_pgpass)
        environment_context.__enter__()
        entered_contexts.append(environment_context)
        engine = _create_engine(parsed_url)
        connection_context = engine.connect()
        connection = connection_context.__enter__()
        entered_contexts.append(connection_context)
        with _prearmed_transaction(
            connection,
            timeout_ms=_TIMEOUT_MS,
            access_mode="read_only",
        ):
            assume_managed_postgres_schema_owner(
                connection,
                contract=contract,
            )
            revision = assert_release_head(
                connection,
                expected_revision=target_revision,
            )
            shape = read_money_schema_shape(connection)
            money_facts = canonical_money_facts_sha256(
                connection,
                error=DatabaseGenerationTargetVerificationError,
            )
            facts = revision, str(shape["shape_sha256"]), money_facts
    except BaseException as exc:  # noqa: BLE001 - explicit target-read owner boundary
        primary = exc
    finally:
        primary = close_postgres_owner_resources(
            contexts=entered_contexts,
            engine=engine,
            primary=primary,
            cleanup=cleanup,
        )
    if isinstance(primary, Exception) and not isinstance(
        primary,
        DatabaseGenerationTargetVerificationError,
    ):
        wrapped = DatabaseGenerationTargetVerificationError(
            "database generation target fact read failed"
        )
        wrapped.__cause__ = primary
        primary = wrapped
    raise_postgres_operation_failures(
        primary=primary,
        cleanup=cleanup,
        message="database generation target verification and cleanup failed",
    )
    if facts is None:
        raise AssertionError("database generation target verification completed without facts")
    return facts


def run_database_generation_target_verification_action(
    *,
    database_url: str,
    pgpassfile: Path,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    operation_id: str,
    database: str,
    restore_attempt_id: str,
    target_revision: str,
) -> dict[str, object]:
    """Prove exact revision plus core resource and canonical money facts."""

    operation = _canonical_uuid(operation_id, label="generation operation id")
    bound_database = _validated_database(
        database,
        operation_id=operation,
        restore_attempt_id=restore_attempt_id,
    )
    try:
        program = load_database_generation_program(
            path=generation_program_path,
            expected_sha256=expected_generation_program_sha256,
        )
    except DatabaseGenerationProgramError as exc:
        raise DatabaseGenerationTargetVerificationError("target verification generation program is invalid") from exc
    if target_revision != program.target_revision:
        raise DatabaseGenerationTargetVerificationError(
            "target verification revision differs from the generation program"
        )
    contract = ManagedPostgresRuntimeContractV1(
        database_name=bound_database,
        migrator_role=MIGRATOR_ROLE,
        schema_owner_role=SCHEMA_OWNER_ROLE,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=_TIMEOUT_MS,
    )
    parsed_url = _validated_migrator_url(database_url, contract=contract)
    if not isinstance(pgpassfile, Path) or not pgpassfile.is_absolute():
        raise DatabaseGenerationTargetVerificationError("target verification pgpass path must be absolute")
    try:
        revision, resource_shape, money_facts = _read_target_facts(
            parsed_url=parsed_url,
            pgpassfile=pgpassfile,
            contract=contract,
            target_revision=target_revision,
        )
    except DatabaseGenerationTargetVerificationError:
        raise
    except (
        ManagedPostgresMigrationRuntimeError,
        MoneySchemaAttestationError,
        OSError,
        ReleaseHeadVerificationError,
        RuntimeError,
        SQLAlchemyError,
        ValueError,
    ) as exc:
        raise DatabaseGenerationTargetVerificationError("database generation target verification failed") from exc
    return {
        "schema": RESULT_SCHEMA,
        "operation_id": operation,
        "database": bound_database,
        "target_revision": target_revision,
        "generation_program_sha256": program.payload_sha256,
        "alembic_revision": revision,
        "resource_shape_sha256": resource_shape,
        "money_facts_sha256": money_facts,
    }


__all__ = [
    "DatabaseGenerationTargetVerificationError",
    "run_database_generation_target_verification_action",
]
