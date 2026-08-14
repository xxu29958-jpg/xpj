"""Execute one build-declared revision suffix on an existing transaction."""

from __future__ import annotations

import importlib.util
from types import ModuleType
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.database._database_generation_program import (
    BASE_SOURCE,
    DatabaseGenerationProgram,
    DatabaseGenerationRevision,
)
from app.database._release_schema_readiness import (
    ReleaseHeadVerificationError,
    assert_release_head,
)


class DatabaseGenerationExecutionError(RuntimeError):
    """The declared generation suffix could not be executed or verified."""


def _canonical_operation_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatabaseGenerationExecutionError(
            "generation operation id is invalid"
        ) from exc
    if parsed.int == 0 or str(parsed) != value:
        raise DatabaseGenerationExecutionError(
            "generation operation id is not canonical"
        )
    return value


def _load_revision(revision: DatabaseGenerationRevision) -> ModuleType:
    try:
        payload = revision.module_path.read_bytes()
    except OSError as exc:
        raise DatabaseGenerationExecutionError(
            "generation revision is unavailable"
        ) from exc
    import hashlib

    if hashlib.sha256(payload).hexdigest() != revision.module_sha256:
        raise DatabaseGenerationExecutionError("generation revision bytes changed")
    spec = importlib.util.spec_from_file_location(
        f"_ticketbox_generation_{revision.revision}",
        revision.module_path,
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
    if not inspect(connection).has_table("alembic_version", schema="public"):
        return None
    revisions = tuple(
        str(value)
        for value in connection.scalars(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        )
    )
    if len(revisions) > 1:
        raise DatabaseGenerationExecutionError(
            "generation database has multiple Alembic revisions"
        )
    return revisions[0] if revisions else None


def _ensure_base_version_table(connection: Connection) -> None:
    if _current_revision(connection) is not None:
        raise DatabaseGenerationExecutionError("generation base is not empty")
    if not inspect(connection).has_table("alembic_version", schema="public"):
        connection.execute(
            text(
                "CREATE TABLE public.alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )


def _apply_context(
    connection: Connection,
    *,
    revision: DatabaseGenerationRevision,
    operation_id: str,
) -> None:
    if revision.context is None:
        return
    context = dict(revision.context)
    if context.get("kind") != "c07_ceremony_v1":
        raise DatabaseGenerationExecutionError("generation context is unsupported")
    timeout = connection.scalar(
        text(
            "SELECT setting FROM pg_catalog.pg_settings "
            "WHERE name = 'transaction_timeout' AND unit = 'ms'"
        )
    )
    timeout_text = str(timeout)
    if not timeout_text.isascii() or not timeout_text.isdecimal() or int(timeout_text) <= 0:
        raise DatabaseGenerationExecutionError(
            "generation transaction timeout is unavailable"
        )
    settings = (
        (context["ceremony_mode_guc"], context["ceremony_mode"]),
        (context["ceremony_id_guc"], operation_id),
        (context["statement_timeout_guc"], timeout_text),
    )
    for key, value in settings:
        observed = connection.scalar(
            text("SELECT set_config(:key, :value, true)"),
            {"key": key, "value": value},
        )
        if observed != value:
            raise DatabaseGenerationExecutionError(
                "generation revision context was not applied"
            )


def _advance_revision(
    connection: Connection,
    *,
    revision: DatabaseGenerationRevision,
) -> None:
    if revision.down_revision is None:
        statement = (
            "INSERT INTO public.alembic_version (version_num) "
            "VALUES (:revision) RETURNING version_num"
        )
        parameters = {"revision": revision.revision}
    else:
        statement = (
            "UPDATE public.alembic_version SET version_num = :revision "
            "WHERE version_num = :down_revision RETURNING version_num"
        )
        parameters = {
            "down_revision": revision.down_revision,
            "revision": revision.revision,
        }
    if connection.scalar(text(statement), parameters) != revision.revision:
        raise DatabaseGenerationExecutionError(
            "generation revision CAS did not update exactly one row"
        )


def _assert_postcondition(
    connection: Connection,
    revision: DatabaseGenerationRevision,
) -> None:
    if revision.postcondition is None:
        return
    if revision.postcondition != "assert_postcondition":
        raise DatabaseGenerationExecutionError("generation postcondition is unsupported")
    _load_revision(revision).assert_postcondition(connection)


def execute_database_generation(
    connection: Connection,
    *,
    program: DatabaseGenerationProgram,
    source_revision: str,
    target_revision: str,
    operation_id: str,
) -> str:
    """Execute the declared suffix; the caller owns transaction and authority."""

    canonical_operation = _canonical_operation_id(operation_id)
    target_verifier = program.revision(target_revision)
    if _current_revision(connection) == target_revision:
        _assert_postcondition(connection, target_verifier)
        return "target_observed_after_interruption"
    if source_revision == BASE_SOURCE:
        _ensure_base_version_table(connection)
    elif _current_revision(connection) != source_revision:
        raise DatabaseGenerationExecutionError(
            "generation live revision is outside the declared suffix"
        )
    suffix = program.suffix(source_revision, target_revision)
    for revision in suffix:
        module = _load_revision(revision)
        _apply_context(
            connection,
            revision=revision,
            operation_id=canonical_operation,
        )
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        _advance_revision(connection, revision=revision)
        if revision.postcondition is not None:
            module.assert_postcondition(connection)
    try:
        assert_release_head(connection, expected_revision=target_revision)
    except ReleaseHeadVerificationError as exc:
        raise DatabaseGenerationExecutionError(
            "generation suffix missed its target"
        ) from exc
    _assert_postcondition(connection, target_verifier)
    return "target_committed"


__all__ = [
    "DatabaseGenerationExecutionError",
    "execute_database_generation",
]
