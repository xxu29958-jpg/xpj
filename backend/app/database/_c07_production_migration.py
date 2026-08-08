"""Standalone production action for the ADR-0073 C07 BIGINT expansion.

The raw source is loaded by physical path so the maintenance process never
executes ``app.database.__init__``.  Its helpers are normal frozen modules, but
are loaded behind a temporary package seam when the database facade is absent.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.services.secure_file import (
    hold_protected_file_for_read,
    hold_system_authority_file_for_read,
)

_HELPER_MODULE_NAMES = (
    "app.database._c07_production_contract",
    "app.database._c07_production_authority",
    "app.database._c07_transaction_timeout",
    "app.database._c07_production_connection",
    "app.database._c07_production_recovery",
    "app.database._c07_production_restore",
    "app.database._c07_production_shape",
)


def _temporary_database_package() -> tuple[ModuleType, bool]:
    existing = sys.modules.get("app.database")
    if isinstance(existing, ModuleType):
        return existing, False
    package = ModuleType("app.database")
    package.__package__ = "app.database"
    package.__path__ = [str(Path(__file__).resolve().parent)]
    package.__spec__ = importlib.machinery.ModuleSpec(
        "app.database",
        loader=None,
        is_package=True,
    )
    sys.modules["app.database"] = package
    return package, True


def _load_helper_modules() -> tuple[ModuleType, ...]:
    package, temporary = _temporary_database_package()
    app_package = sys.modules["app"]
    previous_attribute = getattr(app_package, "database", None)
    had_attribute = hasattr(app_package, "database")
    app_package.database = package
    try:
        return tuple(importlib.import_module(name) for name in _HELPER_MODULE_NAMES)
    finally:
        if temporary:
            for name in _HELPER_MODULE_NAMES:
                sys.modules.pop(name, None)
            sys.modules.pop("app.database", None)
            if had_attribute:
                app_package.database = previous_attribute
            else:
                delattr(app_package, "database")


(
    _contract,
    _authority,
    _transaction_timeout,
    _connection,
    _recovery,
    _restore,
    _shape,
) = _load_helper_modules()

PRODUCTION_MIGRATION_CONTEXT_SCHEMA = _contract.PRODUCTION_MIGRATION_CONTEXT_SCHEMA
PRODUCTION_MIGRATION_EVIDENCE_SCHEMA = _contract.PRODUCTION_MIGRATION_EVIDENCE_SCHEMA
HOST_ENVELOPE_SCHEMA = _contract.HOST_ENVELOPE_SCHEMA
FREEZE_PROOF_SCHEMA = _contract.FREEZE_PROOF_SCHEMA
RECOVERY_ENVELOPE_SCHEMA = _contract.RECOVERY_ENVELOPE_SCHEMA
RECOVERY_GENERATION_SCHEMA = _contract.RECOVERY_GENERATION_SCHEMA
TARGET_RECOVERY_GENERATION_SCHEMA = _contract.TARGET_RECOVERY_GENERATION_SCHEMA
ISOLATED_RESTORE_EVIDENCE_SCHEMA = _contract.ISOLATED_RESTORE_EVIDENCE_SCHEMA
RECOVERY_INTEGRITY_SCOPE = _contract.RECOVERY_INTEGRITY_SCOPE
DATABASE_AUTHORITY_SCHEMA = _contract.DATABASE_AUTHORITY_SCHEMA
DATABASE_NAME = _contract.DATABASE_NAME
MIGRATOR_ROLE = _contract.MIGRATOR_ROLE
SCHEMA_OWNER_ROLE = _contract.SCHEMA_OWNER_ROLE
MAX_CONTEXT_BYTES = _contract.MAX_CONTEXT_BYTES
MAX_AUTHORITY_ARTIFACT_BYTES = _contract.MAX_AUTHORITY_ARTIFACT_BYTES
MAINTENANCE_WINDOW_SECONDS = _contract.MAINTENANCE_WINDOW_SECONDS
C07_SOURCE_REVISION = _contract.C07_SOURCE_REVISION
C07_TARGET_REVISION = _contract.C07_TARGET_REVISION
C07_CEREMONY_MODE_GUC = _contract.C07_CEREMONY_MODE_GUC
C07_CEREMONY_ID_GUC = _contract.C07_CEREMONY_ID_GUC
C07_STATEMENT_TIMEOUT_GUC = _contract.C07_STATEMENT_TIMEOUT_GUC

C07ProductionMigrationError = _contract.C07ProductionMigrationError
ProductionMigrationContext = _contract.ProductionMigrationContext
ValidatedProductionArtifacts = _contract.ValidatedProductionArtifacts
parse_production_migration_context = _contract.parse_production_migration_context
parse_production_migration_context_bytes = (
    _contract.parse_production_migration_context_bytes
)
read_production_migration_context = _contract.read_production_migration_context
_require_lower_sha = _contract._require_lower_sha
_require_operation_id = _contract._require_operation_id
_require_upper_sha = _contract._require_upper_sha
_require_uuid = _contract._require_uuid

_database_binding_sha256 = _connection._database_binding_sha256
_validated_migrator_url = _connection._validated_migrator_url
_validated_pgpass_path = _connection._validated_pgpass_path
_temporary_pgpass_environment = _connection._temporary_pgpass_environment
_read_held_artifact = _connection._read_held_artifact
_create_production_engine = _connection._create_production_engine
_revision = _connection._revision
_migration_module = _connection._migration_module
_run_alembic_upgrade = _connection._run_alembic_upgrade

validate_production_migration_artifact_bytes = (
    _restore.validate_production_migration_artifact_bytes
)
validate_recovery_generation_upload_root_binding = (
    _recovery.validate_recovery_generation_upload_root_binding
)
_money_shape = _shape._money_shape
_migrate_with_connection = _shape._migrate_with_connection


def _validate_cli_binding(
    *,
    operation_id: str,
    source_revision: str,
    target_revision: str,
    migration_context: ProductionMigrationContext,
) -> None:
    canonical_operation = _require_operation_id(
        operation_id,
        label="production operation_id",
    )
    if (
        canonical_operation != migration_context.operation_id
        or source_revision != C07_SOURCE_REVISION
        or target_revision != C07_TARGET_REVISION
        or migration_context.operation_kind != "c07_money_minor_bigint_v1"
        or migration_context.target_alembic_revision != target_revision
    ):
        raise C07ProductionMigrationError(
            "production CLI operation/revisions do not match the frozen contract"
        )


def _hold_and_validate_artifacts(
    stack: ExitStack,
    migration_context: ProductionMigrationContext,
) -> ValidatedProductionArtifacts:
    freeze_path = stack.enter_context(
        hold_system_authority_file_for_read(
            Path(str(migration_context.writer_freeze_proof_path))
        )
    )
    manifest_path = stack.enter_context(
        hold_system_authority_file_for_read(
            Path(str(migration_context.recovery_manifest_path))
        )
    )
    restore_path = stack.enter_context(
        hold_system_authority_file_for_read(
            Path(str(migration_context.isolated_restore_evidence_path))
        )
    )
    return validate_production_migration_artifact_bytes(
        migration_context,
        writer_freeze_proof=_read_held_artifact(freeze_path),
        recovery_manifest=_read_held_artifact(manifest_path),
        isolated_restore_evidence=_read_held_artifact(restore_path),
    )


def _execute_migration(
    *,
    parsed_url,
    context: ProductionMigrationContext,
    generation: ValidatedProductionArtifacts,
    source_revision: str,
    target_revision: str,
) -> dict[str, object]:
    engine: Engine | None = None
    try:
        engine = _create_production_engine(parsed_url)
        with engine.connect() as connection, _transaction_timeout.c07_prearmed_transaction(
            connection,
            timeout_ms=context.maintenance_remaining_ceiling_ms,
        ):
            return _migrate_with_connection(
                connection,
                context=context,
                generation=generation,
                source_revision=source_revision,
                target_revision=target_revision,
            )
    except C07ProductionMigrationError:
        raise
    except SQLAlchemyError as exc:
        raise C07ProductionMigrationError(
            "production PostgreSQL migration action failed"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


def run_production_migration_action(
    *,
    database_url: str,
    pgpassfile: Path,
    operation_id: str,
    source_revision: str,
    target_revision: str,
    migration_context: ProductionMigrationContext,
) -> dict[str, object]:
    """Validate production authority, migrate, verify shape, and return evidence."""

    _validate_cli_binding(
        operation_id=operation_id,
        source_revision=source_revision,
        target_revision=target_revision,
        migration_context=migration_context,
    )
    parsed_url = _validated_migrator_url(database_url)
    passfile = _validated_pgpass_path(pgpassfile)
    with ExitStack() as stack:
        generation = _hold_and_validate_artifacts(stack, migration_context)
        protected_pgpass = stack.enter_context(
            hold_protected_file_for_read(passfile)
        )
        stack.enter_context(_temporary_pgpass_environment(protected_pgpass))
        return _execute_migration(
            parsed_url=parsed_url,
            context=migration_context,
            generation=generation,
            source_revision=source_revision,
            target_revision=target_revision,
        )
