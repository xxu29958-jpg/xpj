"""Exact transactional C07 maintenance upgrade action."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database._c07_contract import C07CeremonyError
from app.database._c07_maintenance_attestation import (
    _assert_isolated_source_shape,
    _money_facts,
    _target_shape_sha256,
)
from app.database._c07_maintenance_common import (
    _acquire_isolated_writer_fence,
    _apply_local_deadlines,
    _assert_migrator_authority,
    _canonical_operation_id,
    _create_engine,
    _current_revision,
    _maintenance_deadline,
    _release_session_fence,
    _remaining_ceiling,
    _remaining_milliseconds,
    _required_lower_sha256,
    _restore_database_name,
    _temporary_pgpass_environment,
    _validated_database,
    _validated_migrator_url,
    _validated_pgpass_path,
)
from app.database._c07_transaction_timeout import c07_prearmed_transaction
from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
    execute_database_generation,
)
from app.database._database_generation_program import (
    DatabaseGenerationProgram,
    DatabaseGenerationProgramError,
    load_database_generation_program,
)
from app.database_generation_c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    ISOLATED_MODE,
    C07MaintenanceUpgradeError,
)
from app.services.secure_file import hold_protected_file_for_read

MAINTENANCE_RESULT_SCHEMA = "ticketbox-c07-maintenance-upgrade-result-v3"
_RESULT_FIELDS = (
    "schema",
    "mode",
    "operation_id",
    "source_revision",
    "target_revision",
    "revision_manifest_sha256",
    "maintenance_authority_sha256",
    "maintenance_remaining_ceiling_ms",
    "resource_shape_sha256",
    "result",
    "alembic_revision",
    "target_shape_sha256",
    "money_facts_sha256",
)


def _run_exact_upgrade(
    connection: Connection,
    *,
    program: DatabaseGenerationProgram,
    operation_id: str,
) -> tuple[str, str, str]:
    current = _current_revision(connection)
    if current == C07_TARGET_REVISION:
        target_shape = _target_shape_sha256(connection)
        return (
            "isolated_forward_replay_verified",
            target_shape,
            _money_facts(connection),
        )
    if current != C07_SOURCE_REVISION:
        raise C07MaintenanceUpgradeError(
            "isolated replay revision differs from the C07 source"
        )
    _assert_isolated_source_shape(connection)
    before = _money_facts(connection)
    try:
        execute_database_generation(
            connection,
            program=program,
            source_revision=C07_SOURCE_REVISION,
            target_revision=C07_TARGET_REVISION,
            operation_id=operation_id,
        )
    except DatabaseGenerationExecutionError as exc:
        raise C07MaintenanceUpgradeError(
            "isolated replay generation execution failed"
        ) from exc
    if _current_revision(connection) != C07_TARGET_REVISION:
        raise C07MaintenanceUpgradeError(
            "isolated replay did not reach the exact C07 target"
        )
    target_shape = _target_shape_sha256(connection)
    after = _money_facts(connection)
    if after != before:
        raise C07MaintenanceUpgradeError(
            "isolated replay changed canonical stored money facts"
        )
    return "isolated_forward_replay_verified", target_shape, after
@dataclass(frozen=True)
class _UpgradeRequest:
    operation: str
    database: str
    program: DatabaseGenerationProgram
    authority: str
    deadline: datetime
    ceiling: int
    remaining: int
    parsed_url: URL
    passfile: Path


def _upgrade_request(
    *,
    mode: str,
    database_url: str,
    pgpassfile: Path,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    operation_id: str,
    source_revision: str,
    target_revision: str,
    expected_revision_manifest_sha256: str,
    maintenance_deadline_utc: str,
    maintenance_remaining_ceiling_ms: int,
    maintenance_authority_sha256: str,
) -> _UpgradeRequest:
    if mode != ISOLATED_MODE:
        raise C07MaintenanceUpgradeError(
            "C07 maintenance accepts isolated replay only"
        )
    operation = _canonical_operation_id(operation_id)
    database = _validated_database(
        _restore_database_name(operation),
        operation_id=operation,
        isolated_only=True,
    )
    try:
        program = load_database_generation_program(
            path=generation_program_path,
            expected_sha256=expected_generation_program_sha256,
        )
    except DatabaseGenerationProgramError as exc:
        raise C07MaintenanceUpgradeError(
            "maintenance generation program is invalid"
        ) from exc
    if (
        source_revision != program.c07.source_revision
        or target_revision != program.c07.target_revision
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance edge differs from the generation program"
        )
    expected_manifest = _required_lower_sha256(
        expected_revision_manifest_sha256,
        label="maintenance revision manifest",
    )
    if expected_manifest != program.c07.revision_manifest_sha256:
        raise C07MaintenanceUpgradeError(
            "maintenance revision manifest differs from the packaged edge"
        )
    deadline = _maintenance_deadline(maintenance_deadline_utc)
    ceiling = _remaining_ceiling(maintenance_remaining_ceiling_ms)
    return _UpgradeRequest(
        operation=operation,
        database=database,
        program=program,
        authority=_required_lower_sha256(
            maintenance_authority_sha256,
            label="maintenance authority",
        ),
        deadline=deadline,
        ceiling=ceiling,
        remaining=_remaining_milliseconds(deadline, ceiling_ms=ceiling),
        parsed_url=_validated_migrator_url(database_url, database=database),
        passfile=_validated_pgpass_path(pgpassfile),
    )


def _upgrade_on_connection(
    connection: Connection,
    request: _UpgradeRequest,
) -> tuple[str, str, str]:
    fence_held = False
    try:
        with c07_prearmed_transaction(
            connection,
            timeout_ms=request.remaining,
        ):
            _apply_local_deadlines(connection, remaining_ms=request.remaining)
            _assert_migrator_authority(connection, database=request.database)
            _acquire_isolated_writer_fence(connection)
            fence_held = True
            return _run_exact_upgrade(
                connection,
                program=request.program,
                operation_id=request.operation,
            )
    finally:
        if fence_held:
            _release_session_fence(connection)


def _execute_upgrade(request: _UpgradeRequest) -> tuple[str, str, str]:
    engine: Engine | None = None
    try:
        with (
            hold_protected_file_for_read(request.passfile) as protected_pgpass,
            _temporary_pgpass_environment(protected_pgpass),
        ):
            engine = _create_engine(request.parsed_url)
            with engine.connect() as connection:
                return _upgrade_on_connection(connection, request)
    finally:
        if engine is not None:
            engine.dispose()


def _upgrade_result(
    request: _UpgradeRequest,
    outcome: tuple[str, str, str],
) -> dict[str, object]:
    result_name, target_shape, facts = outcome
    result: dict[str, object] = {
        "schema": MAINTENANCE_RESULT_SCHEMA,
        "mode": ISOLATED_MODE,
        "operation_id": request.operation,
        "source_revision": C07_SOURCE_REVISION,
        "target_revision": C07_TARGET_REVISION,
        "revision_manifest_sha256": request.program.c07.revision_manifest_sha256,
        "maintenance_authority_sha256": request.authority,
        "maintenance_remaining_ceiling_ms": request.ceiling,
        "resource_shape_sha256": target_shape,
        "result": result_name,
        "alembic_revision": C07_TARGET_REVISION,
        "target_shape_sha256": target_shape,
        "money_facts_sha256": facts,
    }
    if tuple(result) != _RESULT_FIELDS:
        raise AssertionError("C07 maintenance result field order changed")
    return result


def run_maintenance_upgrade_action(
    *,
    mode: str,
    database_url: str,
    pgpassfile: Path,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    operation_id: str,
    source_revision: str,
    target_revision: str,
    expected_revision_manifest_sha256: str,
    maintenance_deadline_utc: str,
    maintenance_remaining_ceiling_ms: int,
    maintenance_authority_sha256: str,
) -> dict[str, object]:
    """Replay only the exact C07 edge in its operation-bound restore DB."""

    try:
        request = _upgrade_request(
            mode=mode,
            database_url=database_url,
            pgpassfile=pgpassfile,
            generation_program_path=generation_program_path,
            expected_generation_program_sha256=(
                expected_generation_program_sha256
            ),
            operation_id=operation_id,
            source_revision=source_revision,
            target_revision=target_revision,
            expected_revision_manifest_sha256=expected_revision_manifest_sha256,
            maintenance_deadline_utc=maintenance_deadline_utc,
            maintenance_remaining_ceiling_ms=maintenance_remaining_ceiling_ms,
            maintenance_authority_sha256=maintenance_authority_sha256,
        )
        return _upgrade_result(request, _execute_upgrade(request))
    except C07MaintenanceUpgradeError:
        raise
    except (C07CeremonyError, OSError, SQLAlchemyError, RuntimeError, ValueError):
        raise C07MaintenanceUpgradeError(
            "C07 frozen isolated replay failed"
        ) from None
