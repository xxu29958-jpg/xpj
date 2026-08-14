"""Real PostgreSQL counterexamples for the generation revision CAS."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app.database import _database_generation_executor as generation_executor
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


def _assert_cas_rejects_drift(
    topology: _ManagedTopology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_advance = generation_executor._advance_revision
    drift_injected = False

    def drift_before_cas(connection, *, revision):
        nonlocal drift_injected
        if not drift_injected:
            drift_injected = True
            connection.execute(
                text(
                    "UPDATE public.alembic_version SET version_num = :hostile "
                    "WHERE version_num = :expected"
                ),
                {
                    "expected": revision.down_revision,
                    "hostile": "hostile_predecessor",
                },
            )
        original_advance(connection, revision=revision)

    monkeypatch.setattr(generation_executor, "_advance_revision", drift_before_cas)
    with pytest.raises(
        ManagedPostgresMigrationRuntimeError,
        match="managed PostgreSQL migration failed",
    ):
        topology.runtime.run(**_migration_arguments(topology))
    monkeypatch.setattr(generation_executor, "_advance_revision", original_advance)
    assert drift_injected
    assert _revision(topology.owner_url) == _C07_TARGET_REVISION


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


def test_generation_revision_cas_rejects_drift_and_invalid_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        _assert_cas_rejects_drift(topology, monkeypatch)
        _assert_invalid_rows_fail_closed(topology)
