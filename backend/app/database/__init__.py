"""Database package facade.

Runtime database callers import ``SessionLocal``, ``engine``, ``get_db``,
``init_db`` (and a few legacy re-exports like ``BACKEND_ROOT``) from this
facade. Declarative model registration is deliberately owned by
``app.database_model_registry`` so importing models does not initialize the
runtime database.

Nothing here does work at import time except materialising the engine via
``_core``. ``init_db`` is the only function that coordinates startup; the
other public symbols are direct re-exports.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy.engine import Connection

from app.database._core import (
    BACKEND_ROOT,
    SessionLocal,
    engine,
    get_db,
    settings,
    wait_for_db,
)
from app.database._database_generation_runtime_admission import (
    assert_database_generation_startup_ready,
)
from app.database._lifecycle import (
    AlembicContext,
    DatabaseLifecycleAction,
    DatabaseLifecyclePlan,
    DatabaseLifecycleState,
    DatabaseMigrationPreflightError,
    inspect_database_lifecycle,
    load_alembic_context,
    plan_database_lifecycle,
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
    "DatabaseMigrationPreflightError",
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
    from app.database._database_generation_program import (
        load_installed_database_generation_program,
    )

    _warn_if_default_database_url()
    lifecycle = inspect_database_lifecycle()
    installed_program = load_installed_database_generation_program() if bool(getattr(sys, "frozen", False)) else None
    installed_runtime = installed_program is not None
    alembic = load_alembic_context(installed_program=installed_program)
    plan = plan_database_lifecycle(lifecycle, alembic)
    if lifecycle.has_existing_schema:
        _assert_existing_schema_compatible(lifecycle)
    if plan.action is DatabaseLifecycleAction.REFUSE:
        raise DatabaseMigrationPreflightError(f"拒绝自动变更数据库:{plan.refusal_reason}数据库未执行 backup/DDL/DML。")
    if plan.action is DatabaseLifecycleAction.FRESH_UPGRADE:
        if installed_runtime:
            raise DatabaseMigrationPreflightError(
                "拒绝由安装版普通后端初始化空数据库:空库必须交由安装器的 "
                "Generation Owner 建立 exact target、isolated restore proof、"
                "database binding 与 CURRENT；数据库未执行 backup/DDL/DML。"
            )
    elif plan.action is DatabaseLifecycleAction.NOOP:
        _assert_database_generation_startup_ready(
            alembic,
            installed_program=installed_program,
        )
    elif plan.action is DatabaseLifecycleAction.MANAGED_UPGRADE and installed_runtime:
        raise DatabaseMigrationPreflightError(
            "拒绝由安装版 runtime 执行 schema DDL:升级必须由安装器在后端停止、"
            "恢复点已验证且短命 migrator 获得 exact-head 计划后执行；"
            "数据库未执行 backup/DDL/DML。"
        )
    elif plan.action is not DatabaseLifecycleAction.MANAGED_UPGRADE:
        raise DatabaseMigrationPreflightError(
            "拒绝由普通后端改变未知数据库状态:"
            f"current={lifecycle.current_revision!r}, head={alembic.head_revision!r}；"
            "数据库未执行 backup/DDL/DML。"
        )
    # Development/operator MANAGED_UPGRADE preflights, backup, and Alembic DDL
    # are repeated under a database-scoped lease below. Installed hosts are
    # fenced above; their long-lived runtime role intentionally has no DDL.
    if plan.action is DatabaseLifecycleAction.MANAGED_UPGRADE:
        raise DatabaseMigrationPreflightError(
            "拒绝由普通后端启动执行既有数据集升级:必须先由离线维护 owner "
            "发布完整数据库+原图 backup generation，再执行受管迁移；"
            "本进程未执行 backup/DDL/DML。"
        )
    _apply_schema_lifecycle(plan, alembic)
    _assert_schema_at_head(alembic.head_revision)
    _assert_database_generation_startup_ready(
        alembic,
        installed_program=installed_program,
    )
    record_schema_migration(
        BASELINE_MIGRATION_NAME,
        backend_version=BACKEND_VERSION,
        note="schema baseline marker",
    )
    seed_identity_data()
    # v0.3.1-alpha2: do NOT auto-migrate legacy uploads on startup. Old image
    # paths remain readable through resolve_protected_image() after the route
    # has verified expense ownership. See docs/runbook/ROLLBACK.md.
    seed_runtime_data()
    # ADR-0043 slice A: one-time expense_tags ↔ tags string mirror reconcile
    # (after seed_runtime_data's backfill_expense_tags; marker-gated run-once).
    reconcile_expense_tag_mirror_once()


def _assert_database_generation_startup_ready(
    alembic: AlembicContext,
    *,
    installed_program: object | None,
) -> None:
    if installed_program is None:
        return
    assert_database_generation_startup_ready(engine, installed_program)


def _apply_schema_lifecycle(plan: DatabaseLifecyclePlan, alembic: AlembicContext) -> None:
    from alembic import command

    if plan.action is DatabaseLifecycleAction.NOOP:
        return
    if plan.action is not DatabaseLifecycleAction.FRESH_UPGRADE:
        raise DatabaseMigrationPreflightError("拒绝执行非 fresh 普通启动迁移；数据库未执行 DDL/DML。")
    from app.database._managed_postgres_migration_runtime import _prearmed_transaction

    with (
        engine.connect() as connection,
        _prearmed_transaction(
            connection,
            timeout_ms=20 * 60 * 1000,
            access_mode="read_write",
        ),
    ):
        alembic.config.attributes["connection"] = connection
        if "alembic_version" in plan.state.table_names:
            command.stamp(alembic.config, "base", purge=True)
        command.upgrade(alembic.config, "head")


def _assert_existing_schema_compatible(
    lifecycle: DatabaseLifecycleState,
    *,
    connection: Connection | None = None,
) -> None:
    """Run the compatibility floor from the sole dataset authority."""

    if "dataset_authority" not in lifecycle.table_names:
        raise DatabaseMigrationPreflightError("拒绝启动数据库:现有 schema 缺少 dataset_authority。")
    from sqlalchemy import inspect, text

    from app.services.app_meta_service import assert_binary_compatible_with_minimum

    if connection is None:
        with engine.connect() as owned_connection:
            return _assert_existing_schema_compatible(
                lifecycle,
                connection=owned_connection,
            )
    columns = {column["name"] for column in inspect(connection).get_columns("dataset_authority")}
    if "schema_min_compatible" not in columns:
        raise DatabaseMigrationPreflightError("拒绝启动数据库:dataset_authority 缺少 schema_min_compatible。")
    minimum = connection.scalar(text("SELECT schema_min_compatible FROM dataset_authority WHERE singleton_id = 1"))
    assert_binary_compatible_with_minimum(minimum)


def _assert_schema_at_head(expected_head: str) -> None:
    from sqlalchemy import text

    with engine.connect() as connection:
        revisions = tuple(connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY version_num")))
    if revisions != (expected_head,):
        raise DatabaseMigrationPreflightError(
            f"数据库迁移后 revision 校验失败:expected={expected_head!r}, actual={revisions!r}。"
        )


def _warn_if_default_database_url() -> None:
    """WARN at startup when DATABASE_URL is unset and the superuser@localhost fallback
    is in use (model-invariant hardening P1). Running Alembic as the
    default ``postgres`` superuser is the 2026-06-04 cut-over setup that left tables
    owned by ``postgres`` and bricked startup for ~4 days (the table-owner trap). Real
    deployments must set DATABASE_URL to the app role; this surfaces the risk early.
    """
    from app.config import database_url_is_default_fallback

    if database_url_is_default_fallback():
        _logger.warning(
            "DATABASE_URL 未设置,正使用默认的 postgres 超级用户@localhost:5432 回落。"
            "以超级用户跑 Alembic 会让表属主=postgres,埋下表属主错位陷阱"
            "(2026-06-04 静默停机根因)。生产请将 DATABASE_URL 指向应用角色。"
        )
