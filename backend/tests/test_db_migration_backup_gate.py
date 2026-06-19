"""Pre-migration backup gate (P1 model-invariant hardening).

An Alembic ``upgrade`` on an EXISTING tracked database is the one irreversible
startup step. ``_backup_before_upgrade`` snapshots the DB (``pg_dump -Fc``)
before the upgrade runs and fails CLOSED — a failed snapshot aborts the
migration rather than risk a corrupt/half-applied schema with no restore point
(data-correctness over availability, ADR-0049 §0). ``SKIP_PRE_MIGRATION_BACKUP``
is the escape hatch for when ``pg_dump`` itself is unavailable and the operator
backed up by hand.

The backup-gate tests stamp ``alembic_version`` below head via a separate
``engine.begin()`` connection (a real cross-connection commit) and then call
``_stamp_alembic_baseline_if_needed`` which opens its own connection, so they
need a real committed DB (``real_db``; the whole module is registered in
conftest ``_PG_REAL_DB_NODES``). After ``reset_db_state`` the DB is freshly
created and stamped to head, which is the substrate these tests mutate. The two
config-WARN tests don't touch the DB but ride the same module marker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text


def _stamp_below_head(db_pkg) -> None:
    """Force ``current_revision != head`` on the existing tracked DB so the
    upgrade block (and the pre-migration backup gate) runs."""
    with db_pkg.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '20260524_0002'"))


def test_pre_migration_backup_runs_before_upgrade(monkeypatch):
    """Wiring + ordering: a pre-existing tracked DB behind head must snapshot
    BEFORE ``command.upgrade`` runs. Deleting the backup call (or moving it after
    the upgrade) fails this — the snapshot is only a restore point if it predates
    the irreversible step."""
    import app.database as db_pkg
    from app.services import backup_service

    order: list[str] = []

    def _fake_backup():
        order.append("backup")
        return SimpleNamespace(file_name="ticketbox-pre-upgrade-test.dump")

    monkeypatch.setattr(backup_service, "create_pre_upgrade_backup", _fake_backup)
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: order.append("upgrade"))
    # Keep the test focused on the backup gate, not the owner-preflight guard.
    monkeypatch.setattr(db_pkg, "_assert_role_can_alter_existing_schema", lambda conn: None)

    _stamp_below_head(db_pkg)
    db_pkg._stamp_alembic_baseline_if_needed()

    assert order == ["backup", "upgrade"], "pre-migration backup must precede the upgrade"


def test_pre_migration_backup_failure_aborts_migration(monkeypatch):
    """Fail-CLOSED: a failed snapshot raises and the migration upgrade must NOT
    run (no migrating onto an existing DB without a restore point). Without the
    fail-closed gate the upgrade would proceed — exactly the silent-brick class
    this hardening prevents."""
    import app.database as db_pkg
    from app.services import backup_service

    ran_upgrade: list[bool] = []

    def _boom():
        raise RuntimeError("pg_dump exploded")

    monkeypatch.setattr(backup_service, "create_pre_upgrade_backup", _boom)
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: ran_upgrade.append(True))
    monkeypatch.setattr(db_pkg, "_assert_role_can_alter_existing_schema", lambda conn: None)

    _stamp_below_head(db_pkg)

    with pytest.raises(RuntimeError, match="迁移前自动备份失败"):
        db_pkg._stamp_alembic_baseline_if_needed()
    assert ran_upgrade == [], "upgrade must NOT run when the pre-migration backup fails"


def test_skip_pre_migration_backup_env_skips_snapshot(monkeypatch):
    """Escape hatch: ``SKIP_PRE_MIGRATION_BACKUP`` skips the snapshot but the
    upgrade still runs (for a hand-backed-up DB whose ``pg_dump`` is broken).
    Pins that the env var is honoured AND that skipping the backup does not also
    skip the migration."""
    import app.database as db_pkg
    from app.services import backup_service

    backup_calls: list[bool] = []
    upgrade_calls: list[bool] = []
    monkeypatch.setattr(
        backup_service, "create_pre_upgrade_backup", lambda: backup_calls.append(True)
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: upgrade_calls.append(True))
    monkeypatch.setattr(db_pkg, "_assert_role_can_alter_existing_schema", lambda conn: None)
    monkeypatch.setenv("SKIP_PRE_MIGRATION_BACKUP", "true")

    _stamp_below_head(db_pkg)
    db_pkg._stamp_alembic_baseline_if_needed()

    assert backup_calls == [], "SKIP_PRE_MIGRATION_BACKUP must skip the snapshot"
    assert upgrade_calls == [True], "upgrade must still run after an explicit skip"


def test_no_backup_taken_when_already_at_head(monkeypatch):
    """No pending migration → no snapshot. After ``reset_db_state`` the DB sits
    at head, so the upgrade block never runs and no backup is taken (a no-op
    restart must not shell out to ``pg_dump`` every time)."""
    import app.database as db_pkg
    from app.services import backup_service

    backup_calls: list[bool] = []
    upgrade_calls: list[bool] = []
    monkeypatch.setattr(
        backup_service, "create_pre_upgrade_backup", lambda: backup_calls.append(True)
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: upgrade_calls.append(True))

    # Pre-condition: the freshly reset DB is already at head.
    with db_pkg.engine.begin() as conn:
        current = conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(db_pkg.__file__).resolve().parents[2]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert current == head, "reset_db_state should leave the DB at head"

    db_pkg._stamp_alembic_baseline_if_needed()

    assert backup_calls == [], "no pending migration must take no pre-migration backup"
    assert upgrade_calls == [], "no pending migration must run no upgrade"


def test_fresh_db_without_version_table_takes_no_backup(monkeypatch):
    """The ``has_version_table`` gate — this PR's headline safety claim. A fresh DB
    with NO ``alembic_version`` table at entry (the ``create_all`` / first-start /
    every ``reset_db_state`` shape) runs its guarded no-op migrations WITHOUT a
    pre-backup. Dropping the version table reproduces that entry shape; ``_stamp``
    then synthesizes ``current_revision`` (below head) and runs the upgrade — but
    the gate must NOT back up, because the table was absent at entry. Otherwise
    every fresh start / test reset would shell out to ``pg_dump`` and a missing
    binary would fail-closed-brick a legitimate first start. Deleting the
    ``if has_version_table:`` guard makes this test fail (the other tests stay
    green under that deletion — this is the one that bites it)."""
    import app.database as db_pkg
    from app.services import backup_service

    backup_calls: list[bool] = []
    upgrade_calls: list[bool] = []
    monkeypatch.setattr(
        backup_service, "create_pre_upgrade_backup", lambda: backup_calls.append(True)
    )
    monkeypatch.setattr("alembic.command.upgrade", lambda *a, **k: upgrade_calls.append(True))
    monkeypatch.setattr(db_pkg, "_assert_role_can_alter_existing_schema", lambda conn: None)

    with db_pkg.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    db_pkg._stamp_alembic_baseline_if_needed()

    assert backup_calls == [], "fresh DB (no alembic_version at entry) must NOT take a pre-migration backup"
    assert upgrade_calls == [True], "fresh DB still runs the (guarded no-op) upgrade to head"


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
