"""Read-only source and target semantic digest actions for C07."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database._c07_contract import C07CeremonyError
from app.database._c07_maintenance_attestation import (
    _money_facts,
    _target_shape_sha256,
)
from app.database._c07_maintenance_common import (
    _apply_local_deadlines,
    _assert_migrator_authority,
    _canonical_operation_id,
    _create_engine,
    _current_revision,
    _maintenance_deadline,
    _remaining_ceiling,
    _remaining_milliseconds,
    _required_lower_sha256,
    _temporary_pgpass_environment,
    _validated_database,
    _validated_migrator_url,
    _validated_pgpass_path,
)
from app.database._c07_transaction_timeout import c07_prearmed_transaction
from app.database._database_generation_program import (
    DatabaseGenerationProgramError,
    load_database_generation_program,
)
from app.database_generation_c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    C07MaintenanceUpgradeError,
)
from app.services.secure_file import hold_protected_file_for_read

MONEY_FACTS_RESULT_SCHEMA = "ticketbox-c07-money-facts-result-v2"
TARGET_SEMANTIC_RESULT_SCHEMA = "ticketbox-c07-target-semantic-result-v1"
_EXPORTED_SNAPSHOT = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}\Z"
)
_MONEY_FACTS_RESULT_FIELDS = (
    "schema",
    "operation_id",
    "database",
    "snapshot_id",
    "maintenance_authority_sha256",
    "maintenance_remaining_ceiling_ms",
    "alembic_revision",
    "money_facts_sha256",
)
_TARGET_SEMANTIC_RESULT_FIELDS = (
    "schema",
    "operation_id",
    "database",
    "snapshot_id",
    "source_revision",
    "target_revision",
    "revision_manifest_sha256",
    "maintenance_authority_sha256",
    "maintenance_remaining_ceiling_ms",
    "alembic_revision",
    "resource_shape_sha256",
    "money_facts_sha256",
)


@contextmanager
def _read_transaction(
    connection: Connection,
    *,
    deadline: datetime,
    ceiling_ms: int,
    snapshot_id: str,
) -> Iterator[Connection]:
    remaining = _remaining_milliseconds(deadline, ceiling_ms=ceiling_ms)
    with c07_prearmed_transaction(connection, timeout_ms=remaining):
        connection.execute(
            text(
                "SET TRANSACTION ISOLATION LEVEL "
                "REPEATABLE READ READ ONLY"
            )
        )
        if snapshot_id:
            connection.execute(
                text(f"SET TRANSACTION SNAPSHOT '{snapshot_id}'")
            )
        _apply_local_deadlines(connection, remaining_ms=remaining)
        yield connection


def _validated_snapshot_id(value: object) -> str:
    if not isinstance(value, str) or (
        value and _EXPORTED_SNAPSHOT.fullmatch(value) is None
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance exported snapshot id is invalid"
        )
    return value


def _open_read_action(
    *,
    database_url: str,
    pgpassfile: Path,
    operation_id: str,
    database: str,
) -> tuple[URL, Path, str, str]:
    operation = _canonical_operation_id(operation_id)
    bound_database = _validated_database(
        database,
        operation_id=operation,
    )
    return (
        _validated_migrator_url(
            database_url,
            database=bound_database,
        ),
        _validated_pgpass_path(pgpassfile),
        operation,
        bound_database,
    )


def run_money_facts_digest_action(
    *,
    database_url: str,
    pgpassfile: Path,
    operation_id: str,
    database: str,
    snapshot_id: str,
    maintenance_deadline_utc: str,
    maintenance_remaining_ceiling_ms: int,
    maintenance_authority_sha256: str,
) -> dict[str, object]:
    """Read canonical C07 money facts from one bound database snapshot."""

    parsed_url, passfile, operation, bound_database = _open_read_action(
        database_url=database_url,
        pgpassfile=pgpassfile,
        operation_id=operation_id,
        database=database,
    )
    snapshot = _validated_snapshot_id(snapshot_id)
    deadline = _maintenance_deadline(maintenance_deadline_utc)
    ceiling = _remaining_ceiling(maintenance_remaining_ceiling_ms)
    authority = _required_lower_sha256(
        maintenance_authority_sha256,
        label="maintenance authority",
    )
    engine: Engine | None = None
    try:
        with (
            hold_protected_file_for_read(passfile) as protected_pgpass,
            _temporary_pgpass_environment(protected_pgpass),
        ):
            engine = _create_engine(parsed_url)
            with (
                engine.connect() as connection,
                _read_transaction(
                    connection,
                    deadline=deadline,
                    ceiling_ms=ceiling,
                    snapshot_id=snapshot,
                ),
            ):
                _assert_migrator_authority(
                    connection,
                    database=bound_database,
                )
                revision = _current_revision(connection)
                if revision not in {
                    C07_SOURCE_REVISION,
                    C07_TARGET_REVISION,
                }:
                    raise C07MaintenanceUpgradeError(
                        "money-facts database revision is outside C07"
                    )
                facts = _money_facts(connection)
        result: dict[str, object] = {
            "schema": MONEY_FACTS_RESULT_SCHEMA,
            "operation_id": operation,
            "database": bound_database,
            "snapshot_id": snapshot,
            "maintenance_authority_sha256": authority,
            "maintenance_remaining_ceiling_ms": ceiling,
            "alembic_revision": revision,
            "money_facts_sha256": facts,
        }
        if tuple(result) != _MONEY_FACTS_RESULT_FIELDS:
            raise AssertionError("C07 money-facts result field order changed")
        return result
    except C07MaintenanceUpgradeError:
        raise
    except (C07CeremonyError, OSError, SQLAlchemyError, RuntimeError, ValueError):
        raise C07MaintenanceUpgradeError(
            "C07 frozen money-facts read failed"
        ) from None
    finally:
        if engine is not None:
            engine.dispose()


def _target_digest_values(
    parsed_url: URL,
    passfile: Path,
    *,
    bound_database: str,
    deadline: datetime,
    ceiling: int,
    snapshot: str,
) -> tuple[str, str]:
    engine: Engine | None = None
    try:
        with (
            hold_protected_file_for_read(passfile) as protected_pgpass,
            _temporary_pgpass_environment(protected_pgpass),
        ):
            engine = _create_engine(parsed_url)
            with (
                engine.connect() as connection,
                _read_transaction(
                    connection,
                    deadline=deadline,
                    ceiling_ms=ceiling,
                    snapshot_id=snapshot,
                ),
            ):
                _assert_migrator_authority(
                    connection,
                    database=bound_database,
                )
                if _current_revision(connection) != C07_TARGET_REVISION:
                    raise C07MaintenanceUpgradeError(
                        "target attestation database is not at C07"
                    )
                return _target_shape_sha256(connection), _money_facts(connection)
    finally:
        if engine is not None:
            engine.dispose()


def _target_digest_result(
    *,
    operation: str,
    database: str,
    snapshot: str,
    revision_manifest_sha256: str,
    authority: str,
    ceiling: int,
    shape: str,
    facts: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": TARGET_SEMANTIC_RESULT_SCHEMA,
        "operation_id": operation,
        "database": database,
        "snapshot_id": snapshot,
        "source_revision": C07_SOURCE_REVISION,
        "target_revision": C07_TARGET_REVISION,
        "revision_manifest_sha256": revision_manifest_sha256,
        "maintenance_authority_sha256": authority,
        "maintenance_remaining_ceiling_ms": ceiling,
        "alembic_revision": C07_TARGET_REVISION,
        "resource_shape_sha256": shape,
        "money_facts_sha256": facts,
    }
    if tuple(result) != _TARGET_SEMANTIC_RESULT_FIELDS:
        raise AssertionError("C07 target attestation result field order changed")
    return result


def run_target_semantic_digest_action(
    *,
    database_url: str,
    pgpassfile: Path,
    generation_program_path: Path,
    expected_generation_program_sha256: str,
    operation_id: str,
    database: str,
    snapshot_id: str,
    source_revision: str,
    target_revision: str,
    expected_revision_manifest_sha256: str,
    maintenance_deadline_utc: str,
    maintenance_remaining_ceiling_ms: int,
    maintenance_authority_sha256: str,
) -> dict[str, object]:
    """Attest only the exact C07 money resources and stored facts."""

    try:
        program = load_database_generation_program(
            path=generation_program_path,
            expected_sha256=expected_generation_program_sha256,
        )
        if (
            source_revision != program.c07.source_revision
            or target_revision != program.c07.target_revision
        ):
            raise C07MaintenanceUpgradeError(
                "target attestation edge differs from the generation program"
            )
        expected_manifest = _required_lower_sha256(
            expected_revision_manifest_sha256,
            label="maintenance revision manifest",
        )
        if expected_manifest != program.c07.revision_manifest_sha256:
            raise C07MaintenanceUpgradeError(
                "target attestation manifest differs from the packaged edge"
            )
        parsed_url, passfile, operation, bound_database = _open_read_action(
            database_url=database_url,
            pgpassfile=pgpassfile,
            operation_id=operation_id,
            database=database,
        )
        snapshot = _validated_snapshot_id(snapshot_id)
        deadline = _maintenance_deadline(maintenance_deadline_utc)
        ceiling = _remaining_ceiling(maintenance_remaining_ceiling_ms)
        authority = _required_lower_sha256(
            maintenance_authority_sha256,
            label="maintenance authority",
        )
        shape, facts = _target_digest_values(
            parsed_url,
            passfile,
            bound_database=bound_database,
            deadline=deadline,
            ceiling=ceiling,
            snapshot=snapshot,
        )
        return _target_digest_result(
            operation=operation,
            database=bound_database,
            snapshot=snapshot,
            revision_manifest_sha256=program.c07.revision_manifest_sha256,
            authority=authority,
            ceiling=ceiling,
            shape=shape,
            facts=facts,
        )
    except (C07MaintenanceUpgradeError, DatabaseGenerationProgramError):
        raise
    except (C07CeremonyError, OSError, SQLAlchemyError, RuntimeError, ValueError):
        raise C07MaintenanceUpgradeError(
            "C07 frozen target attestation failed"
        ) from None
