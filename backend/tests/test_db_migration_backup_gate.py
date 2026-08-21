"""ADR-0067 inspect/compatibility/backup/Alembic startup ordering tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from app.database._lifecycle import DatabaseLifecycleKind
from app.database._managed_postgres_contract import MIGRATION_LEASE_LABEL
from app.database_model_registry import Base

pytestmark = pytest.mark.real_db

_OLDER_REVISION = "20260630_0002"
_MANAGED_SOURCE_REVISION = "20260722_0001"
_MONEY_BIGINT_REVISION = "20260729_0001"


def _stamp_revision(db_pkg, revision: str) -> None:
    with db_pkg.engine.begin() as conn:
        conn.execute(
            text("UPDATE alembic_version SET version_num = :revision"),
            {"revision": revision},
        )


def _head_revision(db_pkg) -> str:
    with db_pkg.engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")))


def _catalog_snapshot(db_pkg) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
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
        tables = set(inspect(connection).get_table_names())
        revisions = (
            tuple(connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY version_num")))
            if "alembic_version" in tables
            else ()
        )
    return objects, revisions


def _patch_database_writes(monkeypatch, db_pkg, calls: list[str]) -> None:
    monkeypatch.setattr(Base.metadata, "create_all", lambda *a, **k: calls.append("create_all"))
    monkeypatch.setattr(db_pkg, "record_schema_migration", lambda *a, **k: calls.append("seed"))
    monkeypatch.setattr(db_pkg, "seed_identity_data", lambda: calls.append("seed"))
    monkeypatch.setattr(db_pkg, "seed_runtime_data", lambda: calls.append("seed"))
    monkeypatch.setattr(db_pkg, "reconcile_expense_tag_mirror_once", lambda: calls.append("seed"))


def _assert_migration_lease_blocks(db_pkg, calls: list[str]) -> None:
    contender_engine = create_engine(
        db_pkg.engine.url,
        poolclass=NullPool,
        future=True,
    )
    try:
        with contender_engine.begin() as blocker:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(current_database()), hashtext(:label))"),
                {"label": MIGRATION_LEASE_LABEL},
            )
            with pytest.raises(
                db_pkg.DatabaseMigrationPreflightError,
                match="schema migration lease",
            ):
                db_pkg.init_db()
            assert calls == []
            assert _head_revision(db_pkg) == _MONEY_BIGINT_REVISION
    finally:
        contender_engine.dispose()


def _assert_old_runtime_blocks(db_pkg, calls: list[str]) -> None:
    old_runtime_engine = create_engine(
        db_pkg.engine.url,
        poolclass=NullPool,
        future=True,
    )
    try:
        with old_runtime_engine.connect() as old_runtime:
            old_runtime.execute(text("SELECT 1"))
            with pytest.raises(
                db_pkg.DatabaseMigrationPreflightError,
                match="another client session",
            ):
                db_pkg.init_db()
            assert calls == []
            assert _head_revision(db_pkg) == _MONEY_BIGINT_REVISION
    finally:
        old_runtime_engine.dispose()


@pytest.mark.parametrize("revision", [_OLDER_REVISION, _MANAGED_SOURCE_REVISION])
def test_installed_runtime_refuses_known_behind_revision_before_writes(
    monkeypatch,
    revision: str,
):
    """The frozen runtime leaves every known behind revision to its host owner."""
    import app.database as db_pkg
    from app.database import _database_generation_program as program_reader
    from app.services import backup_service

    alembic = db_pkg.load_alembic_context()
    calls: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_pre_upgrade_backup",
        lambda: calls.append("backup"),
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: calls.append("upgrade"))
    monkeypatch.setattr("alembic.command.stamp", lambda *a, **k: calls.append("stamp"))
    _patch_database_writes(monkeypatch, db_pkg, calls)
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
    _stamp_revision(db_pkg, revision)
    before = _catalog_snapshot(db_pkg)
    with pytest.raises(
        db_pkg.DatabaseMigrationPreflightError,
        match="安装器.*短命 migrator",
    ):
        db_pkg.init_db()

    assert calls == []
    assert _catalog_snapshot(db_pkg) == before


def test_empty_database_first_start_uses_alembic_only(monkeypatch):
    """A truly empty database reaches head without backup or create_all."""
    import app.database as db_pkg
    from app.services import backup_service

    with db_pkg.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    def _unexpected(*args, **kwargs):
        raise AssertionError("empty first start must not call backup/create_all")

    monkeypatch.setattr(backup_service, "create_pre_upgrade_backup", _unexpected)
    monkeypatch.setattr(Base.metadata, "create_all", _unexpected)
    assert db_pkg.inspect_database_lifecycle().kind is DatabaseLifecycleKind.EMPTY
    db_pkg.init_db()

    with db_pkg.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        category_rule_columns = {column["name"] for column in inspect(connection).get_columns("category_rules")}
        audit_columns = {column["name"] for column in inspect(connection).get_columns("ledger_audit_logs")}
    assert {"expenses", "app_meta", "alembic_version"}.issubset(tables)
    assert "deleted_at" in category_rule_columns
    assert {"resource_type", "resource_public_id"}.issubset(audit_columns)
    assert _head_revision(db_pkg) == db_pkg.load_alembic_context().head_revision


def test_managed_schema_at_head_skips_lifecycle_backup(monkeypatch):
    """At-head startup performs no lifecycle backup or Alembic mutation."""
    import app.database as db_pkg
    from app.services import backup_service

    calls: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_pre_upgrade_backup",
        lambda: calls.append("backup") or SimpleNamespace(file_name="at-head.dump"),
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: calls.append("upgrade"))
    _patch_database_writes(monkeypatch, db_pkg, calls)
    db_pkg.init_db()

    assert "backup" not in calls
    assert "upgrade" not in calls
    assert "seed" in calls


def test_post_money_bigint_managed_revision_backs_up_then_upgrades(monkeypatch):
    """Managed startup is lease-fenced, then backs up and reaches head."""
    from alembic import command

    import app.database as db_pkg
    from app.database import _database_generation_program as program_reader
    from app.services import backup_service
    from tests._infra.alembic_runtime import run_alembic_for_test

    alembic = db_pkg.load_alembic_context()
    command.downgrade(alembic.config, _MONEY_BIGINT_REVISION)
    assert _head_revision(db_pkg) == _MONEY_BIGINT_REVISION

    calls: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_pre_upgrade_backup",
        lambda: calls.append("backup") or SimpleNamespace(file_name="pre-c02.dump"),
    )
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

    with monkeypatch.context() as installed_runtime:
        installed_runtime.setattr(sys, "frozen", True, raising=False)
        with pytest.raises(
            db_pkg.DatabaseMigrationPreflightError,
            match="安装器.*短命 migrator",
        ):
            db_pkg.init_db()
    assert calls == []
    assert _head_revision(db_pkg) == _MONEY_BIGINT_REVISION

    # Development/operator Alembic still uses the same external-connection
    # environment. The dedicated installed-role runtime has its own topology
    # integration proof.
    run_alembic_for_test(
        db_pkg.engine,
        alembic.config,
        command.upgrade,
        "head",
    )
    assert _head_revision(db_pkg) == alembic.head_revision
    command.downgrade(alembic.config, _MONEY_BIGINT_REVISION)
    assert _head_revision(db_pkg) == _MONEY_BIGINT_REVISION

    _assert_migration_lease_blocks(db_pkg, calls)
    _assert_old_runtime_blocks(db_pkg, calls)
    db_pkg.init_db()

    assert calls == ["backup"]
    assert _head_revision(db_pkg) == alembic.head_revision
    with db_pkg.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM public.alembic_version")) == alembic.head_revision


def test_pre_money_managed_revision_is_prearmed_before_upgrade(monkeypatch):
    """A known source revision can execute the timeout-guarded money migration."""
    from alembic import command

    import app.database as db_pkg
    from app.services import backup_service
    from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

    alembic = db_pkg.load_alembic_context()
    reset_public_schema(db_pkg.engine)
    run_alembic_for_test(
        db_pkg.engine,
        alembic.config,
        command.upgrade,
        _MANAGED_SOURCE_REVISION,
    )
    assert _head_revision(db_pkg) == _MANAGED_SOURCE_REVISION

    calls: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_pre_upgrade_backup",
        lambda: calls.append("backup") or SimpleNamespace(file_name="pre-money.dump"),
    )

    db_pkg.init_db()

    assert calls == ["backup"]
    assert _head_revision(db_pkg) == alembic.head_revision


def test_legacy_database_without_revision_refuses_without_backup(monkeypatch):
    """Unknown lineage is read-only refused before backup, DDL, or seed."""
    import app.database as db_pkg
    from app.services import backup_service

    calls: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_pre_upgrade_backup",
        lambda: calls.append("backup") or SimpleNamespace(file_name="legacy.dump"),
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: calls.append("upgrade"))
    monkeypatch.setattr("alembic.command.stamp", lambda *a, **k: calls.append("stamp"))
    _patch_database_writes(monkeypatch, db_pkg, calls)

    with db_pkg.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    before = _catalog_snapshot(db_pkg)

    with pytest.raises(db_pkg.DatabaseMigrationPreflightError, match="adoption"):
        db_pkg.init_db()
    assert calls == []
    assert _catalog_snapshot(db_pkg) == before

    with db_pkg.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('future_unknown')"))
    before_unknown = _catalog_snapshot(db_pkg)
    with pytest.raises(db_pkg.DatabaseMigrationPreflightError, match="不属于当前 binary"):
        db_pkg.init_db()
    assert calls == []
    assert _catalog_snapshot(db_pkg) == before_unknown


def test_default_database_url_fallback_warns_at_startup(monkeypatch):
    """DATABASE_URL unset → the superuser@localhost fallback is in use → startup
    WARNs (that fallback is the table-owner-trap precondition: running migrations
    as the ``postgres`` superuser is the 2026-06-04 cut-over setup). Spies on
    ``_logger.warning`` directly so the assertion pins the production code path
    regardless of pytest's logging-level/propagation config."""
    import app.database as db_pkg
    from app.config import database_url_is_default_fallback

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url_is_default_fallback() is True

    messages: list[str] = []
    monkeypatch.setattr(db_pkg._logger, "warning", lambda msg, *a, **k: messages.append(msg))
    db_pkg._warn_if_default_database_url()
    assert any("DATABASE_URL 未设置" in message for message in messages)


def test_explicit_database_url_does_not_warn(monkeypatch):
    """DATABASE_URL set (a real deployment pointing at the app role) → no WARN."""
    import app.database as db_pkg
    from app.config import database_url_is_default_fallback

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app@localhost:5432/x")
    assert database_url_is_default_fallback() is False

    messages: list[str] = []
    monkeypatch.setattr(db_pkg._logger, "warning", lambda msg, *a, **k: messages.append(msg))
    db_pkg._warn_if_default_database_url()
    assert messages == []
