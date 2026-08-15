"""Real PostgreSQL counterexamples for the Alembic generation boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

import app.database._database_generation_executor as generation_executor
from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
)
from app.database._database_generation_program import ALEMBIC_PROGRAM_ATTRIBUTE
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
)
from tests.test_managed_postgres_migration_runtime import (
    _C07_TARGET_REVISION,
    _RELEASE_HEAD_REVISION,
    _managed_topology,
    _ManagedTopology,
    _revision,
)

pytestmark = pytest.mark.real_db


def _migration_arguments(topology: _ManagedTopology) -> dict[str, object]:
    return {
        "database_url": topology.migrator_url.render_as_string(hide_password=False),
        "pgpassfile": topology.pgpass,
        "program": topology.program,
        "source_revision": _C07_TARGET_REVISION,
        "target_revision": _RELEASE_HEAD_REVISION,
        "generation_operation_id": topology.operation_id,
    }


def _assert_alembic_owns_the_exact_transition(
    topology: _ManagedTopology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_upgrade = generation_executor.command.upgrade
    observed: list[tuple[object, str, object]] = []

    def observe_upgrade(config, target_revision):
        observed.append(
            (
                config.attributes.get("connection"),
                target_revision,
                config.attributes.get(ALEMBIC_PROGRAM_ATTRIBUTE),
            )
        )
        return original_upgrade(config, target_revision)

    monkeypatch.setattr(generation_executor.command, "upgrade", observe_upgrade)
    assert topology.runtime.run(**_migration_arguments(topology)) == "target_committed"
    monkeypatch.setattr(generation_executor.command, "upgrade", original_upgrade)
    assert len(observed) == 1
    assert observed[0][0] is not None
    assert observed[0][1:] == (_RELEASE_HEAD_REVISION, topology.program)
    assert _revision(topology.owner_url) == _RELEASE_HEAD_REVISION


def _assert_target_retry_revalidates_postcondition(
    topology: _ManagedTopology,
) -> None:
    owner_engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
    try:
        with owner_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE public.installation_owner_claims "
                    "DROP CONSTRAINT uq_installation_owner_claim_installation_id"
                )
            )
        with pytest.raises(
            ManagedPostgresMigrationRuntimeError,
            match="managed PostgreSQL migration failed",
        ):
            topology.runtime.run(**_migration_arguments(topology))
    finally:
        owner_engine.dispose()
    assert _revision(topology.owner_url) == _RELEASE_HEAD_REVISION


def _assert_executor_requires_caller_transaction(topology: _ManagedTopology) -> None:
    engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as connection, pytest.raises(
            DatabaseGenerationExecutionError,
            match="active caller transaction",
        ):
            generation_executor.execute_database_generation(
                connection,
                program=topology.program,
                source_revision=_C07_TARGET_REVISION,
                target_revision=_RELEASE_HEAD_REVISION,
                operation_id=topology.operation_id,
            )
    finally:
        engine.dispose()


def _assert_invalid_rows_fail_closed(topology: _ManagedTopology) -> None:
    owner_engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
    try:
        with owner_engine.begin() as connection:
            connection.execute(text("DELETE FROM public.alembic_version"))
        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(**_migration_arguments(topology))
        with owner_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO public.alembic_version (version_num) "
                    "VALUES (:revision), ('hostile_second_head')"
                ),
                {"revision": _C07_TARGET_REVISION},
            )
        with pytest.raises(ManagedPostgresMigrationRuntimeError):
            topology.runtime.run(**_migration_arguments(topology))
        with owner_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM public.alembic_version "
                    "WHERE version_num = 'hostile_second_head'"
                )
            )
        with owner_engine.connect() as connection:
            assert "installation_currency_bindings" not in inspect(
                connection
            ).get_table_names(schema="public")
    finally:
        owner_engine.dispose()
    assert _revision(topology.owner_url) == _C07_TARGET_REVISION


def test_generation_alembic_boundary_rejects_invalid_rows_and_owns_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        _assert_executor_requires_caller_transaction(topology)
        _assert_invalid_rows_fail_closed(topology)
        _assert_alembic_owns_the_exact_transition(topology, monkeypatch)
        _assert_target_retry_revalidates_postcondition(topology)
