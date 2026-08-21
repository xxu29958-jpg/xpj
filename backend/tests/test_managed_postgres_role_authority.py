"""Hostile real-PostgreSQL mutations for the maintenance role boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from psycopg import sql

from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
)
from tests.test_managed_postgres_migration_runtime import (
    _C07_TARGET_REVISION,
    _RELEASE_HEAD_REVISION,
    _managed_topology,
    _revision,
)

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize(
    "drift",
    ["owner_login", "migrator_inherit", "extra_membership"],
)
def test_role_authority_drift_refuses_before_alembic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    with _managed_topology(tmp_path, monkeypatch) as topology:
        if drift == "owner_login":
            topology.admin.execute(
                sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(topology.owner))
            )
        elif drift == "migrator_inherit":
            topology.admin.execute(
                sql.SQL("ALTER ROLE {} INHERIT").format(sql.Identifier(topology.migrator))
            )
        else:
            topology.admin.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(topology.runtime_role),
                    sql.Identifier(topology.migrator),
                )
            )

        with pytest.raises(
            ManagedPostgresMigrationRuntimeError,
            match="managed PostgreSQL migration failed",
        ):
            topology.runtime.run(
                database_url=topology.migrator_url.render_as_string(hide_password=False),
                pgpassfile=topology.pgpass,
                program=topology.program,
                source_revision=_C07_TARGET_REVISION,
                target_revision=_RELEASE_HEAD_REVISION,
                generation_operation_id=topology.operation_id,
            )
        assert _revision(topology.admin_database_url) == _C07_TARGET_REVISION
