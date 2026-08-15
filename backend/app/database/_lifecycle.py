"""Read-only database lifecycle discovery for startup migrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.database._core import engine
from app.database._database_generation_program import (
    ALEMBIC_PROGRAM_ATTRIBUTE,
    DatabaseGenerationProgram,
)


class DatabaseMigrationPreflightError(RuntimeError):
    """Startup migration preflight failed before database mutation."""


class DatabaseLifecycleKind(Enum):
    EMPTY = "empty"
    LEGACY_UNVERSIONED = "legacy_unversioned"
    VERSIONED = "versioned"


class DatabaseLifecycleAction(Enum):
    FRESH_UPGRADE = "fresh_upgrade"
    MANAGED_UPGRADE = "managed_upgrade"
    NOOP = "noop"
    REFUSE = "refuse"


@dataclass(frozen=True)
class DatabaseLifecycleState:
    kind: DatabaseLifecycleKind
    table_names: frozenset[str]
    object_names: frozenset[str]
    current_revisions: tuple[str, ...] = ()

    @property
    def has_existing_schema(self) -> bool:
        return self.kind is not DatabaseLifecycleKind.EMPTY

    @property
    def current_revision(self) -> str | None:
        if len(self.current_revisions) != 1:
            return None
        return self.current_revisions[0]


@dataclass(frozen=True)
class AlembicContext:
    config: object
    head_revision: str
    known_revisions: frozenset[str]


@dataclass(frozen=True)
class DatabaseLifecyclePlan:
    state: DatabaseLifecycleState
    action: DatabaseLifecycleAction
    target_revision: str
    refusal_reason: str | None = None


def _inspect_database_lifecycle(connection: Connection) -> DatabaseLifecycleState:
    inspector = inspect(connection)
    table_names = frozenset(inspector.get_table_names())
    object_names = frozenset(
        connection.scalars(
            text(
                "SELECT c.relname FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
            )
        )
    )
    application_tables = table_names - {"alembic_version"}
    application_objects = object_names - {"alembic_version"}
    if not application_tables and not application_objects:
        return DatabaseLifecycleState(
            DatabaseLifecycleKind.EMPTY,
            table_names,
            object_names,
        )
    if "alembic_version" in table_names:
        current_revisions = tuple(
            connection.scalars(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
        )
        return DatabaseLifecycleState(
            DatabaseLifecycleKind.VERSIONED,
            table_names,
            object_names,
            current_revisions=current_revisions,
        )
    return DatabaseLifecycleState(
        DatabaseLifecycleKind.LEGACY_UNVERSIONED,
        table_names,
        object_names,
    )


def inspect_database_lifecycle(
    connection: Connection | None = None,
) -> DatabaseLifecycleState:
    """Classify the public schema without issuing DDL or DML."""

    if connection is not None:
        return _inspect_database_lifecycle(connection)
    with engine.connect() as owned_connection:
        return _inspect_database_lifecycle(owned_connection)


def load_alembic_context(
    *,
    installed_program: DatabaseGenerationProgram | None = None,
) -> AlembicContext:
    """Resolve the single Alembic head before startup is allowed to mutate."""

    try:
        from alembic.config import Config
    except ImportError as exc:
        raise DatabaseMigrationPreflightError(
            "拒绝初始化数据库:Alembic 不可用,无法建立可追踪的 PostgreSQL schema。"
        ) from exc

    if installed_program is not None:
        config = Config()
        config.attributes[ALEMBIC_PROGRAM_ATTRIBUTE] = installed_program
        return AlembicContext(
            config=config,
            head_revision=installed_program.target_revision,
            known_revisions=frozenset(
                revision.revision for revision in installed_program.revisions
            ),
        )

    from alembic.script import ScriptDirectory
    from alembic.util import CommandError

    backend_root = Path(__file__).resolve().parents[2]
    ini_path = backend_root / "alembic.ini"
    if not ini_path.is_file():
        raise DatabaseMigrationPreflightError(
            f"拒绝初始化数据库:Alembic 配置不存在({ini_path})。"
        )
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    try:
        head = ScriptDirectory.from_config(config).get_current_head()
    except (CommandError, OSError) as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝初始化数据库:无法解析 Alembic head({exc})。"
        ) from exc
    if head is None:
        raise DatabaseMigrationPreflightError("拒绝初始化数据库:Alembic head 为空。")
    revisions = frozenset(
        revision.revision for revision in ScriptDirectory.from_config(config).walk_revisions()
    )
    return AlembicContext(
        config=config,
        head_revision=head,
        known_revisions=revisions,
    )


def plan_database_lifecycle(
    state: DatabaseLifecycleState, alembic: AlembicContext
) -> DatabaseLifecyclePlan:
    """Build a mutation-free plan from the inspected schema and revision graph."""

    if state.kind is DatabaseLifecycleKind.EMPTY:
        return DatabaseLifecyclePlan(
            state,
            DatabaseLifecycleAction.FRESH_UPGRADE,
            alembic.head_revision,
        )
    if state.kind is DatabaseLifecycleKind.LEGACY_UNVERSIONED:
        return DatabaseLifecyclePlan(
            state,
            DatabaseLifecycleAction.REFUSE,
            alembic.head_revision,
            "检测到应用对象但缺少合法 alembic_version lineage;需要显式 adoption。",
        )
    if len(state.current_revisions) != 1:
        return DatabaseLifecyclePlan(
            state,
            DatabaseLifecycleAction.REFUSE,
            alembic.head_revision,
            "alembic_version 必须且只能包含一个 revision,"
            f"实际为 {list(state.current_revisions)!r}。",
        )
    current = state.current_revision
    if current not in alembic.known_revisions:
        return DatabaseLifecyclePlan(
            state,
            DatabaseLifecycleAction.REFUSE,
            alembic.head_revision,
            f"revision {current!r} 不属于当前 binary 的 Alembic graph。",
        )
    action = (
        DatabaseLifecycleAction.NOOP
        if current == alembic.head_revision
        else DatabaseLifecycleAction.MANAGED_UPGRADE
    )
    return DatabaseLifecyclePlan(state, action, alembic.head_revision)
