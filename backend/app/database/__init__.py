"""Database package facade.

Public API is unchanged from the pre-split monolithic ``app.database`` module:
external callers still import ``Base``, ``SessionLocal``, ``engine``,
``get_db``, ``init_db`` (and a few legacy re-exports like ``BACKEND_ROOT``)
from ``app.database``. Internals are split across private submodules by
responsibility — see each ``_*.py`` for what lives where.

Nothing here does work at import time except materialising the engine via
``_core``. ``init_db`` is the only function that coordinates startup; the
other public symbols are direct re-exports.
"""

from __future__ import annotations

import logging

from app.database._core import (
    BACKEND_ROOT,
    Base,
    SessionLocal,
    engine,
    get_db,
    settings,
    wait_for_db,
)
from app.database._seed import (
    BASELINE_MIGRATION_NAME,
    reconcile_expense_tag_mirror_once,
    record_schema_migration,
    seed_identity_data,
    seed_runtime_data,
)
from app.database._uploads import migrate_upload_paths_to_tenant_dirs
from app.version import BACKEND_VERSION

_logger = logging.getLogger(__name__)

__all__ = [
    "BACKEND_ROOT",
    "BASELINE_MIGRATION_NAME",
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "migrate_upload_paths_to_tenant_dirs",
    "reconcile_expense_tag_mirror_once",
    "record_schema_migration",
    "seed_identity_data",
    "seed_runtime_data",
    "settings",
    "wait_for_db",
]


def init_db() -> None:
    from app import models  # noqa: F401

    _warn_if_default_database_url()
    Base.metadata.create_all(bind=engine)
    record_schema_migration(
        BASELINE_MIGRATION_NAME,
        backend_version=BACKEND_VERSION,
        note="schema baseline marker",
    )
    _stamp_alembic_baseline_if_needed()
    _seed_fresh_schema_metadata_if_needed()
    seed_identity_data()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/runbook/ROLLBACK.md.
    seed_runtime_data()
    # ADR-0043 slice A: one-time expense_tags ↔ tags string mirror reconcile
    # (after seed_runtime_data's backfill_expense_tags; marker-gated run-once).
    reconcile_expense_tag_mirror_once()


def _stamp_alembic_baseline_if_needed() -> None:
    """Bring Alembic's version table in line with the runtime schema.

    Fresh databases are created from current ``Base.metadata`` and can be
    stamped directly to head. Existing v1.1 databases are first stamped to
    the baseline revision, then upgraded to head so real Alembic revisions
    (starting with 20260524_0002) actually run.
    """
    from pathlib import Path

    from sqlalchemy import inspect, text

    try:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError:
        return

    backend_root = Path(__file__).resolve().parents[2]
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        return

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    try:
        head = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return
    if head is None:
        return

    current_revision: str | None = None
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        has_version_table = "alembic_version" in table_names
        if has_version_table:
            current_revision = connection.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
        else:
            has_retention_column = False
            if "budget_advisor_audit_logs" in table_names:
                has_retention_column = any(
                    column["name"] == "retention_days"
                    for column in inspector.get_columns("budget_advisor_audit_logs")
                )
            # Existing pre-Alembic databases may have this column because
            # create_all() just created the current ORM table, but they still
            # need later data migrations (for example OCR raw_text backfills).
            current_revision = (
                "20260524_0002" if has_retention_column else "20260524_0001"
            )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    "(version_num VARCHAR(32) PRIMARY KEY)"
                )
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": current_revision},
            )
    if current_revision != head:
        # A pre-existing Alembic-tracked DB behind head (``alembic_version`` row
        # present at entry) is the production restart / upgrade path the
        # pre-migration snapshot protects. A fresh ``create_all``'d DB has no
        # ``alembic_version`` table at entry and runs the same guarded migrations
        # as no-ops with no data to lose — skip the backup there, otherwise every
        # fresh start / test reset would needlessly shell out to ``pg_dump`` (and
        # a missing binary would fail-closed-brick a legitimate fresh start).
        if has_version_table:
            _backup_before_upgrade(current_revision, head)
        with engine.begin() as connection:
            _assert_role_can_alter_existing_schema(connection)
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")


def _assert_role_can_alter_existing_schema(connection) -> None:
    """Pre-flight before Alembic ``upgrade`` on an EXISTING schema: the connected
    role must be able to ALTER the public tables, or the migration half-fails
    cryptically mid-run.

    The 2026-06-04 PostgreSQL cut-over loaded data as the ``postgres`` superuser,
    leaving most tables owned by ``postgres`` while the app role had only DML; the
    first ALTER migration was rejected ("must be owner") and startup silently
    bricked for ~4 days (see docs/runbook/POSTGRES_MIGRATION.md §3 and the
    table-owner trap). This turns that failure mode into a clear, actionable
    pre-flight error listing the mis-owned tables.

    Conservative by design: a table is flagged only when the connected role has
    NO membership relationship to the owning role (``pg_has_role(... 'MEMBER')``
    is false) — exactly the trap. A role is always a member of itself and a
    superuser is a member of every role, so a freshly ``create_all``'d database
    (every table owned by the current role) and the healthy production setup both
    yield zero flagged rows; this never blocks a legitimate start. A
    member-without-inherit edge case (rare, not the cut-over trap) is left to fail
    naturally at the ALTER, same as today — fail-open there beats false-positive
    bricking a legitimate startup.
    """
    from sqlalchemy import text

    rows = connection.execute(
        text(
            """
            SELECT tablename, tableowner
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tableowner <> current_user
              AND NOT pg_has_role(current_user, tableowner, 'MEMBER')
            ORDER BY tablename
            """
        )
    ).all()
    if not rows:
        return

    current = connection.scalar(text("SELECT current_user"))
    sample = ", ".join(f"{row.tablename}(属主={row.tableowner})" for row in rows[:8])
    suffix = "" if len(rows) <= 8 else f" 等共 {len(rows)} 张表"
    raise RuntimeError(
        f"拒绝执行数据库迁移:当前数据库角色 '{current}' 不是下列表的属主、"
        f"也不是属主角色的成员或超级用户,ALTER / ADD CONSTRAINT 迁移会失败"
        f"(历史 cut-over 表属主错位陷阱)。请先用超级用户归位表属主"
        f"(见 docs/runbook/POSTGRES_MIGRATION.md §3 与 "
        f"backend/scripts/fix_table_owners.sql),再重启服务。受影响表:{sample}{suffix}。"
    )


def _warn_if_default_database_url() -> None:
    """WARN at startup when DATABASE_URL is unset and the superuser@localhost fallback
    is in use (model-invariant hardening P1). Running create_all / migrations as the
    default ``postgres`` superuser is the 2026-06-04 cut-over setup that left tables
    owned by ``postgres`` and bricked startup for ~4 days (the table-owner trap). Real
    deployments must set DATABASE_URL to the app role; this surfaces the risk early.
    """
    from app.config import database_url_is_default_fallback

    if database_url_is_default_fallback():
        _logger.warning(
            "DATABASE_URL 未设置,正使用默认的 postgres 超级用户@localhost:5432 回落。"
            "以超级用户跑 create_all / 迁移会让表属主=postgres,埋下表属主错位陷阱"
            "(2026-06-04 静默停机根因)。生产请将 DATABASE_URL 指向应用角色。"
        )


def _backup_before_upgrade(current_revision: str | None, head: str) -> None:
    """Snapshot the EXISTING database BEFORE running pending Alembic migrations
    (model-invariant hardening P1). An Alembic upgrade on an existing DB is the one
    irreversible startup step; take a pg_dump restore point first so a migration that
    corrupts or half-applies can be recovered. Fail-CLOSED: if the backup fails the
    upgrade does NOT run (data-correctness over availability, ADR-0049 §0).

    Escape hatch: ``SKIP_PRE_MIGRATION_BACKUP=true`` skips the snapshot with a loud
    WARN — for the case where pg_dump itself is broken/unavailable and the operator
    has backed up by hand; without it a broken backup tool would permanently brick a
    legitimate migration (the very silent-brick class this hardening prevents).

    Only reached for a pre-existing Alembic-tracked DB behind head (caller gates on
    ``has_version_table``); a fresh ``create_all``'d DB runs its guarded no-op
    migrations without a pre-backup (nothing to lose, and no ``pg_dump`` dependency
    on the first-start / test-reset path). Residual by design: a true pre-Alembic
    v1.1 DB (real data but no ``alembic_version`` row at entry) also skips this
    backup; that path is vestigial post-2026-06-04 cut-over (any prior startup
    created the version table), and such an operator must back up by hand first.
    """
    import os

    if os.getenv("SKIP_PRE_MIGRATION_BACKUP", "").strip().lower() in {"1", "true", "yes"}:
        _logger.warning(
            "SKIP_PRE_MIGRATION_BACKUP 已设置——跳过迁移前自动备份(%s -> %s)。"
            "请确认已手动备份数据库。",
            current_revision,
            head,
        )
        return

    from app.services.backup_service import create_pre_upgrade_backup

    try:
        entry = create_pre_upgrade_backup()
    except Exception as exc:
        raise RuntimeError(
            f"拒绝执行数据库迁移:迁移前自动备份失败({exc})。迁移是不可逆启动步骤,"
            f"未成功备份不迁移(数据安全优先)。请确认 pg_dump 可用、备份目录可写后重启;"
            f"若已手动备份且确需跳过,设 SKIP_PRE_MIGRATION_BACKUP=true 再重启。"
        ) from exc
    _logger.info(
        "迁移前已写入数据库快照(%s),准备从 %s 迁移到 %s。",
        entry.file_name,
        current_revision,
        head,
    )


def _seed_fresh_schema_metadata_if_needed() -> None:
    from app.services.app_meta_service import seed_fresh_schema_metadata

    with SessionLocal() as db:
        seed_fresh_schema_metadata(db)
