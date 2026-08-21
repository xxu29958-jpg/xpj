"""Real PostgreSQL counterexamples for the Alembic generation boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

import app.database._database_generation_executor as generation_executor
from app.database import _database_generation_target_verification as target_verification
from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
)
from app.database._database_generation_program import ALEMBIC_PROGRAM_ATTRIBUTE
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
)
from tests.test_managed_postgres_migration_runtime import (
    _C02_TARGET_REVISION,
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
    assert _revision(topology.admin_database_url) == _RELEASE_HEAD_REVISION


def _assert_intermediate_postcondition_is_mandatory(
    topology: _ManagedTopology,
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_revision: str,
) -> None:
    original = generation_executor._assert_postcondition
    observed: list[str] = []

    def reject_intermediate(connection, revision):
        observed.append(revision.revision)
        if revision.revision == _C02_TARGET_REVISION:
            raise generation_executor.DatabaseGenerationExecutionError(
                "injected intermediate postcondition failure"
            )
        return original(connection, revision)

    monkeypatch.setattr(
        generation_executor,
        "_assert_postcondition",
        reject_intermediate,
    )
    with pytest.raises(
        ManagedPostgresMigrationRuntimeError,
        match="managed PostgreSQL migration failed",
    ):
        topology.runtime.run(**_migration_arguments(topology))
    monkeypatch.setattr(generation_executor, "_assert_postcondition", original)
    assert _C02_TARGET_REVISION in observed
    assert _revision(topology.admin_database_url) == expected_revision


def _assert_target_retry_revalidates_postcondition(
    topology: _ManagedTopology,
) -> None:
    owner_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
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
    assert _revision(topology.admin_database_url) == _RELEASE_HEAD_REVISION


def _assert_executor_requires_caller_transaction(topology: _ManagedTopology) -> None:
    engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
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
            )
    finally:
        engine.dispose()


def _assert_invalid_rows_fail_closed(topology: _ManagedTopology) -> None:
    owner_engine = create_engine(topology.admin_database_url, poolclass=NullPool, future=True)
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
    assert _revision(topology.admin_database_url) == _C07_TARGET_REVISION


def test_generation_alembic_boundary_rejects_invalid_rows_and_owns_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        _assert_executor_requires_caller_transaction(topology)
        _assert_invalid_rows_fail_closed(topology)
        _assert_intermediate_postcondition_is_mandatory(
            topology,
            monkeypatch,
            expected_revision=_C07_TARGET_REVISION,
        )
        _assert_alembic_owns_the_exact_transition(topology, monkeypatch)
        _assert_intermediate_postcondition_is_mandatory(
            topology,
            monkeypatch,
            expected_revision=_RELEASE_HEAD_REVISION,
        )
        _assert_target_retry_revalidates_postcondition(topology)


def test_target_verification_consumer_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        assert topology.runtime.run(**_migration_arguments(topology)) == "target_committed"
        original_money_facts = target_verification.canonical_money_facts_sha256
        observations: list[str] = []

        def observe_read_only(connection, *, error: type[Exception]) -> str:
            observations.append(str(connection.scalar(text("SHOW transaction_read_only"))))
            savepoint = connection.begin_nested()
            try:
                with pytest.raises(SQLAlchemyError, match="read-only transaction"):
                    connection.execute(text("CREATE TABLE target_verifier_must_be_read_only (id integer)"))
            finally:
                savepoint.rollback()
            return original_money_facts(connection, error=error)

        monkeypatch.setattr(target_verification, "LIVE_DATABASE", topology.database)
        monkeypatch.setattr(target_verification, "MIGRATOR_ROLE", topology.migrator)
        monkeypatch.setattr(target_verification, "SCHEMA_OWNER_ROLE", topology.owner)
        monkeypatch.setattr(target_verification, "canonical_money_facts_sha256", observe_read_only)
        result = target_verification.run_database_generation_target_verification_action(
            database_url=topology.migrator_url.render_as_string(hide_password=False),
            pgpassfile=topology.pgpass,
            generation_program_path=topology.program_path,
            expected_generation_program_sha256=topology.program.payload_sha256,
            operation_id=topology.operation_id,
            database=topology.database,
            restore_attempt_id="",
            target_revision=_RELEASE_HEAD_REVISION,
        )
        assert result["alembic_revision"] == _RELEASE_HEAD_REVISION
        assert observations == ["on"]
