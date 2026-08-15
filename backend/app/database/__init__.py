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
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database._c07_contract import (
    C07_SOURCE_REVISION,
    MIGRATION_LEASE_LABEL,
    C07CeremonyError,
    C07ReceiptRepairRequiredError,
)
from app.database._core import (
    BACKEND_ROOT,
    SessionLocal,
    engine,
    get_db,
    settings,
    wait_for_db,
)
from app.database._database_generation_program import (
    ALEMBIC_PROGRAM_ATTRIBUTE,
    DatabaseGenerationProgramError,
    database_generation_program_revision_includes_c07,
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
from app.errors import AppError
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
    _assert_revision_contains_c07(alembic.head_revision, alembic, label="release head")
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
    try:
        if plan.action is DatabaseLifecycleAction.MANAGED_UPGRADE:
            _apply_managed_schema_lifecycle(alembic)
        else:
            _apply_schema_lifecycle(plan, alembic)
    except C07ReceiptRepairRequiredError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝执行数据库迁移:C07 生命周期证明未能与 DDL 原子登记({exc})，事务已回滚。"
        ) from exc
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
        _assert_source_c07_receipt_ready(alembic)
        return
    assert_database_generation_startup_ready(engine, installed_program)


def _assert_source_c07_receipt_ready(alembic: AlembicContext) -> None:
    from app.database._c07_receipt import assert_c07_lifecycle_ready

    try:
        assert_c07_lifecycle_ready(engine, alembic_config=alembic.config)
    except C07ReceiptRepairRequiredError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放 source database writer:C07 migration receipt 未完成({exc})。"
        ) from exc


def _assert_revision_contains_c07(
    revision: str | None,
    alembic: AlembicContext,
    *,
    label: str,
) -> None:
    try:
        installed_program = alembic.config.attributes.get(ALEMBIC_PROGRAM_ATTRIBUTE)
        if installed_program is None:
            from app.database._c07_execution import _revision_includes_c07

            includes_c07 = _revision_includes_c07(
                revision,
                alembic_config=alembic.config,
            )
        else:
            includes_c07 = database_generation_program_revision_includes_c07(
                installed_program,
                revision,
            )
    except (C07CeremonyError, DatabaseGenerationProgramError) as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:{label} 的 C07 ancestry 无法验证({exc})；数据库未执行 backup/DDL/DML。"
        ) from exc
    if includes_c07:
        return
    raise DatabaseMigrationPreflightError(
        "拒绝由普通后端跨越 C07 迁移边界:"
        f"{label}={revision!r}；source={C07_SOURCE_REVISION!r} "
        "只能由 C07 发布迁移动作推进；更早、多头或未知 revision 同样 "
        "inspect-only REFUSED；数据库未执行 backup/DDL/DML。"
    )


def _apply_schema_lifecycle(plan: DatabaseLifecyclePlan, alembic: AlembicContext) -> None:
    from alembic import command

    if plan.action is DatabaseLifecycleAction.NOOP:
        return
    if plan.action is not DatabaseLifecycleAction.FRESH_UPGRADE:
        raise DatabaseMigrationPreflightError("拒绝执行非 fresh C07 普通启动迁移；数据库未执行 DDL/DML。")
    from app.database._c07_ceremony import (
        C07_CEREMONY_MODE_FRESH,
        C07_FRESH_CEREMONY_ID,
        set_c07_migration_context,
    )
    from app.database._c07_contract import MAINTENANCE_WINDOW_SECONDS
    from app.database._c07_transaction_timeout import c07_prearmed_transaction

    with (
        engine.connect() as connection,
        c07_prearmed_transaction(
            connection,
            timeout_ms=MAINTENANCE_WINDOW_SECONDS * 1000,
        ),
    ):
        alembic.config.attributes["connection"] = connection
        set_c07_migration_context(
            connection,
            mode=C07_CEREMONY_MODE_FRESH,
            ceremony_id=C07_FRESH_CEREMONY_ID,
        )
        if "alembic_version" in plan.state.table_names:
            command.stamp(alembic.config, "base", purge=True)
        command.upgrade(alembic.config, "head")


def _apply_managed_schema_lifecycle(alembic: AlembicContext) -> None:
    """Serialize reclassification, backup, and DDL for an existing database."""

    from alembic import command

    # Preflight reads may have returned idle connections to this process's
    # pool. Close those before proving that no older runtime remains connected;
    # checked-out connections survive dispose and are therefore still rejected.
    engine.dispose()
    with engine.begin() as connection:
        lease_acquired = connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(current_database()), hashtext(:label))"),
            {"label": MIGRATION_LEASE_LABEL},
        )
        if lease_acquired is not True:
            raise DatabaseMigrationPreflightError(
                "拒绝并发数据库迁移:schema migration lease 正由另一进程持有；"
                "本进程未执行 backup/DDL/DML。请在当前迁移结束后重启。"
            )
        # The plan observed before the lease is never a write authorization.
        # A competing process may have reached head between that read and this
        # transaction, so classify again while the lease is held.
        lifecycle = inspect_database_lifecycle(connection)
        plan = plan_database_lifecycle(lifecycle, alembic)
        if lifecycle.has_existing_schema:
            _assert_existing_schema_compatible(lifecycle, connection=connection)
        if plan.action is DatabaseLifecycleAction.NOOP:
            _assert_source_c07_receipt_ready(alembic)
            return
        if plan.action is DatabaseLifecycleAction.REFUSE:
            raise DatabaseMigrationPreflightError(
                f"拒绝自动变更数据库:{plan.refusal_reason}数据库未执行 backup/DDL/DML。"
            )
        if plan.action is not DatabaseLifecycleAction.MANAGED_UPGRADE:
            raise DatabaseMigrationPreflightError(
                "拒绝在 managed migration lease 内改变非托管数据库状态；数据库未执行 backup/DDL/DML。"
            )

        _assert_managed_upgrade_writer_quiescence(connection)
        _lock_managed_upgrade_tables(connection)
        _assert_revision_contains_c07(
            lifecycle.current_revision,
            alembic,
            label="installed revision",
        )
        _assert_source_c07_receipt_ready(alembic)
        _assert_existing_schema_owner_ready(connection)
        _backup_before_upgrade(lifecycle.current_revision, alembic.head_revision)
        # Alembic must use this exact connection: PostgreSQL transaction-level
        # advisory locks are scoped to it, keeping the lease through all DDL and
        # releasing it automatically on commit or rollback.
        alembic.config.attributes["connection"] = connection
        command.upgrade(alembic.config, "head")


def _assert_managed_upgrade_writer_quiescence(connection: Connection) -> None:
    connection.execute(text("SELECT pg_stat_clear_snapshot()"))
    other_clients = connection.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datid = (SELECT oid FROM pg_database "
            "WHERE datname = current_database()) "
            "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
        )
    )
    if int(other_clients or 0) != 0:
        raise DatabaseMigrationPreflightError(
            "拒绝在旧 runtime 仍连接时执行升级:发现 another client session；"
            "本进程未执行 backup/DDL/DML。请先停止所有旧后端。"
        )


def _lock_managed_upgrade_tables(connection: Connection) -> None:
    table_names = tuple(
        str(name)
        for name in connection.scalars(
            text(
                "SELECT c.relname FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                "ORDER BY c.relname"
            )
        )
    )
    if not table_names:
        raise DatabaseMigrationPreflightError("拒绝升级缺少可锁定关系的既有数据库；本进程未执行 backup/DDL/DML。")
    preparer = connection.dialect.identifier_preparer
    schema = preparer.quote_schema("public")
    relations = ", ".join(f"{schema}.{preparer.quote_identifier(name)}" for name in table_names)
    connection.execute(text("SET LOCAL lock_timeout = '15s'"))
    connection.execute(text(f"LOCK TABLE {relations} IN SHARE MODE"))


def _assert_existing_schema_compatible(
    lifecycle: DatabaseLifecycleState,
    *,
    connection: Connection | None = None,
) -> None:
    """Run the app_meta binary floor when that legacy schema exposes it."""

    if "app_meta" not in lifecycle.table_names:
        return
    from sqlalchemy import inspect, text

    from app.models.app_meta import SCHEMA_MIN_COMPATIBLE_KEY
    from app.services.app_meta_service import assert_binary_compatible_with_minimum

    if connection is None:
        with engine.connect() as owned_connection:
            return _assert_existing_schema_compatible(
                lifecycle,
                connection=owned_connection,
            )
    columns = {column["name"] for column in inspect(connection).get_columns("app_meta")}
    if not {"key", "value"}.issubset(columns):
        raise DatabaseMigrationPreflightError("拒绝启动数据库:app_meta 缺少 compatibility 所需的 key/value 列。")
    minimum = connection.scalar(
        text("SELECT value FROM app_meta WHERE key = :key LIMIT 1"),
        {"key": SCHEMA_MIN_COMPATIBLE_KEY},
    )
    assert_binary_compatible_with_minimum(minimum)


def _assert_existing_schema_owner_ready(connection: Connection) -> None:
    _assert_role_can_alter_existing_schema(connection)


def _assert_schema_at_head(expected_head: str) -> None:
    from sqlalchemy import text

    with engine.connect() as connection:
        revisions = tuple(connection.scalars(text("SELECT version_num FROM alembic_version ORDER BY version_num")))
    if revisions != (expected_head,):
        raise DatabaseMigrationPreflightError(
            f"数据库迁移后 revision 校验失败:expected={expected_head!r}, actual={revisions!r}。"
        )


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

    PostgreSQL's ``USAGE`` role test reflects whether ``current_user`` can
    actually exercise the owner role through inheritance. A bare membership is
    insufficient when the login is ``NOINHERIT``; accepting that shape would let
    the pre-flight pass and then fail at the first ALTER. A role has USAGE on
    itself and a superuser has USAGE on every role, so healthy owner and migrator
    configurations still yield zero flagged rows.
    """
    from sqlalchemy import text

    rows = connection.execute(
        text(
            """
            SELECT tablename, tableowner
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tableowner <> current_user
              AND NOT pg_has_role(current_user, tableowner, 'USAGE')
            ORDER BY tablename
            """
        )
    ).all()
    if not rows:
        return

    current = connection.scalar(text("SELECT current_user"))
    sample = ", ".join(f"{row.tablename}(属主={row.tableowner})" for row in rows[:8])
    suffix = "" if len(rows) <= 8 else f" 等共 {len(rows)} 张表"
    raise DatabaseMigrationPreflightError(
        f"拒绝执行数据库迁移:当前数据库角色 '{current}' 不是下列表的属主、"
        f"也不能继承属主角色权限,ALTER / ADD CONSTRAINT 迁移会失败"
        f"(历史 cut-over 表属主错位陷阱)。请先用超级用户归位表属主"
        f"(见 docs/runbook/POSTGRES_MIGRATION.md §3 与 "
        f"backend/scripts/fix_table_owners.sql),再重启服务。受影响表:{sample}{suffix}。"
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


def _backup_before_upgrade(current_revision: str | None, head: str) -> None:
    """Snapshot a supported behind schema immediately before Alembic writes.

    Fail-CLOSED: if pg_dump fails, startup performs no database mutation.
    Empty, at-head, and refused unknown-lineage plans never call this function.
    """
    from app.services.backup_service import create_pre_upgrade_backup

    try:
        entry = create_pre_upgrade_backup()
    except (AppError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝执行数据库迁移:迁移前自动备份失败({exc})。迁移是不可逆启动步骤,"
            f"未成功备份不迁移(数据安全优先)。请确认 pg_dump 可用、备份目录可写后重启;"
            "不得通过 unattended 环境变量跳过恢复点。"
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
