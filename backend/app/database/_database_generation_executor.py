"""Run one build-declared generation inside a caller-owned transaction."""

from __future__ import annotations

import hashlib
import importlib.util
from types import ModuleType

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from sqlalchemy.engine import Connection

from app.database._database_generation_program import (
    ALEMBIC_PROGRAM_ATTRIBUTE,
    BASE_SOURCE,
    DatabaseGenerationProgram,
    DatabaseGenerationProgramError,
    DatabaseGenerationRevision,
)
from app.database._release_schema_readiness import (
    ReleaseHeadVerificationError,
    assert_release_head,
)

_MANAGED_JSON_PROTOCOL_ATTRIBUTE = "ticketbox_managed_migration_json_protocol_v1"


class DatabaseGenerationExecutionError(RuntimeError):
    """The declared generation could not be executed or verified."""


def _load_revision(revision: DatabaseGenerationRevision) -> ModuleType:
    try:
        payload = revision.module_path.read_bytes()
    except OSError as exc:
        raise DatabaseGenerationExecutionError(
            "generation revision is unavailable"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != revision.module_sha256:
        raise DatabaseGenerationExecutionError("generation revision bytes changed")
    spec = importlib.util.spec_from_file_location(
        f"_ticketbox_generation_{revision.revision}", revision.module_path
    )
    if spec is None or spec.loader is None:
        raise DatabaseGenerationExecutionError("generation revision cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        getattr(module, "revision", None) != revision.revision
        or getattr(module, "down_revision", None) != revision.down_revision
        or not callable(getattr(module, "upgrade", None))
        or (
            revision.postcondition is not None
            and not callable(getattr(module, revision.postcondition, None))
        )
    ):
        raise DatabaseGenerationExecutionError("generation revision metadata changed")
    return module


def _current_revision(connection: Connection) -> str | None:
    heads = tuple(
        str(value)
        for value in MigrationContext.configure(
            connection, opts={"version_table_schema": "public"}
        ).get_current_heads()
    )
    if len(heads) > 1:
        raise DatabaseGenerationExecutionError(
            "generation database has multiple Alembic revisions"
        )
    return heads[0] if heads else None


def _assert_postcondition(
    connection: Connection,
    revision: DatabaseGenerationRevision,
) -> None:
    if revision.postcondition is None:
        return
    if revision.postcondition != "assert_postcondition":
        raise DatabaseGenerationExecutionError("generation postcondition is unsupported")
    _load_revision(revision).assert_postcondition(connection)


def _alembic_config(
    connection: Connection,
    program: DatabaseGenerationProgram,
) -> Config:
    root = program.revisions[0].module_path.parents[2]
    if any(revision.module_path.parents[2] != root for revision in program.revisions):
        raise DatabaseGenerationExecutionError("generation program spans multiple roots")
    try:
        ini_path = (root / "alembic.ini").resolve(strict=True)
        script_path = (root / "migrations").resolve(strict=True)
    except OSError as exc:
        raise DatabaseGenerationExecutionError(
            "generation Alembic environment is unavailable"
        ) from exc
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(script_path))
    config.attributes["connection"] = connection
    config.attributes[_MANAGED_JSON_PROTOCOL_ATTRIBUTE] = True
    config.attributes[ALEMBIC_PROGRAM_ATTRIBUTE] = program
    return config


def execute_database_generation(
    connection: Connection,
    *,
    program: DatabaseGenerationProgram,
    source_revision: str,
    target_revision: str,
) -> bool:
    """Apply the build target through Alembic; return whether work was run."""

    try:
        suffix = program.suffix(source_revision, target_revision)
    except DatabaseGenerationProgramError as exc:
        raise DatabaseGenerationExecutionError(
            "generation suffix is outside the build program"
        ) from exc
    if not connection.in_transaction():
        raise DatabaseGenerationExecutionError(
            "generation execution requires an active caller transaction"
        )
    current = _current_revision(connection)
    if current == target_revision:
        for revision in suffix:
            _assert_postcondition(connection, revision)
        return False
    if current != (None if source_revision == BASE_SOURCE else source_revision):
        raise DatabaseGenerationExecutionError(
            "generation live revision is outside the declared suffix"
        )
    config = _alembic_config(connection, program)
    try:
        command.upgrade(config, target_revision)
        assert_release_head(connection, expected_revision=target_revision)
    except (CommandError, ReleaseHeadVerificationError) as exc:
        raise DatabaseGenerationExecutionError(
            "Alembic did not reach the build-authorized target"
        ) from exc
    for revision in suffix:
        _assert_postcondition(connection, revision)
    return True


__all__ = [
    "DatabaseGenerationExecutionError",
    "execute_database_generation",
]
