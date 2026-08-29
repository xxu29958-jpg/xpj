"""Startup never impersonates the offline dataset maintenance owner."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import inspect, text

from app.database._lifecycle import DatabaseLifecycleKind

pytestmark = pytest.mark.real_db

_BEHIND_REVISION = "20260729_0001"


def _stamp_revision(db_pkg, revision: str) -> None:
    with db_pkg.engine.begin() as connection:
        connection.execute(
            text("UPDATE alembic_version SET version_num = :revision"),
            {"revision": revision},
        )


def _catalog(db_pkg) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    with db_pkg.engine.connect() as connection:
        objects = tuple(
            connection.execute(
                text(
                    "SELECT c.relname, c.relkind FROM pg_class AS c "
                    "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' ORDER BY c.relname, c.relkind"
                )
            )
        )
        revisions = tuple(
            connection.scalars(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        )
    return objects, revisions


def test_source_runtime_refuses_existing_dataset_upgrade_without_mutation() -> None:
    import app.database as db_pkg

    _stamp_revision(db_pkg, _BEHIND_REVISION)
    before = _catalog(db_pkg)

    with pytest.raises(
        db_pkg.DatabaseMigrationPreflightError,
        match=r"当前没有已资格的离线升级 owner.*继续 HOLD",
    ):
        db_pkg.init_db()

    assert _catalog(db_pkg) == before


def test_installed_runtime_refuses_behind_revision_before_maintenance_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.database as db_pkg
    from app.database import _database_generation_program as program_reader

    alembic = db_pkg.load_alembic_context()
    monkeypatch.setattr(
        program_reader,
        "load_installed_database_generation_program",
        lambda: object(),
    )
    monkeypatch.setattr(
        db_pkg,
        "load_alembic_context",
        lambda *, installed_program=None: alembic,
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _stamp_revision(db_pkg, _BEHIND_REVISION)
    before = _catalog(db_pkg)

    with pytest.raises(
        db_pkg.DatabaseMigrationPreflightError,
        match=r"当前安装版不提供既有数据集升级.*继续 HOLD",
    ):
        db_pkg.init_db()

    assert _catalog(db_pkg) == before


def test_empty_source_still_uses_alembic_owned_first_creation() -> None:
    import app.database as db_pkg

    with db_pkg.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    assert db_pkg.inspect_database_lifecycle().kind is DatabaseLifecycleKind.EMPTY
    db_pkg.init_db()

    with db_pkg.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert {"alembic_version", "dataset_authority", "expenses"}.issubset(tables)
    assert revision == "20260828_0001"
