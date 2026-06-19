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

from app.database._core import (
    BACKEND_ROOT,
    Base,
    SessionLocal,
    engine,
    get_db,
    settings,
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
]


def init_db() -> None:
    from app import models  # noqa: F401

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


def _seed_fresh_schema_metadata_if_needed() -> None:
    from app.services.app_meta_service import seed_fresh_schema_metadata

    with SessionLocal() as db:
        seed_fresh_schema_metadata(db)
