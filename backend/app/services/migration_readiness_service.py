"""v1.0 migration preflight helpers.

The service is intentionally local/backend-only. It inspects the current SQLite
schema, verifies that v0.9 baseline tables and indexes are present, and can
create a named pre-v1.0 backup. It does not mutate business data or run schema
migrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect

from app.config import get_settings
from app.database import engine
from app.errors import AppError
from app.services import backup_service
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION


V1_TARGET_VERSION = "1.0"

REQUIRED_V09_TABLES = {
    "accounts",
    "ledgers",
    "ledger_members",
    "devices",
    "auth_tokens",
    "upload_links",
    "pairing_codes",
    "invitations",
    "ledger_audit_logs",
    "expenses",
    "category_rules",
    "duplicate_ignores",
    "recurring_items",
    "budgets",
    "budget_categories",
    "goals",
    "dashboard_card_preferences",
    "merchant_aliases",
    "tags",
    "expense_tags",
    "rule_application_batches",
    "rule_application_changes",
}

REQUIRED_V09_INDEXES = {
    "expenses": {
        "ix_expenses_tenant_status_created_at",
        "ix_expenses_tenant_status_expense_time",
        "ix_expenses_tenant_status_confirmed_at",
        "ix_expenses_tenant_image_hash",
    },
    "goals": {
        "ix_goals_tenant_month_status",
        "ix_goals_tenant_public_id",
    },
    "dashboard_card_preferences": {
        "ix_dashboard_cards_tenant_surface_position",
        "ix_dashboard_cards_tenant_surface_key",
    },
    "budgets": {
        "ix_budgets_tenant_month",
    },
    "recurring_items": {
        "ix_recurring_items_tenant_status_next",
    },
}


@dataclass(frozen=True)
class MigrationCheck:
    code: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class MigrationReadinessReport:
    target_version: str
    backend_version: str
    identity_schema: str
    database_kind: str
    backup_created: str | None
    latest_backup: str | None
    latest_backup_kind: str | None
    checks: list[MigrationCheck]

    @property
    def ready(self) -> bool:
        return all(check.status != "error" for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "target_version": self.target_version,
            "backend_version": self.backend_version,
            "identity_schema": self.identity_schema,
            "database_kind": self.database_kind,
            "ready": self.ready,
            "backup_created": self.backup_created,
            "latest_backup": self.latest_backup,
            "latest_backup_kind": self.latest_backup_kind,
            "checks": [check.to_dict() for check in self.checks],
        }


def _check(code: str, status: str, message: str) -> MigrationCheck:
    return MigrationCheck(code=code, status=status, message=message)


def _database_path_exists() -> bool:
    cfg = get_settings()
    if not cfg.database_url.startswith("sqlite:///"):
        return False
    raw_path = cfg.database_url[len("sqlite:///") :].strip()
    if raw_path in {"", ":memory:"}:
        return False
    return Path(raw_path).is_file()


def build_v1_migration_readiness_report(*, create_backup: bool = False) -> MigrationReadinessReport:
    cfg = get_settings()
    checks: list[MigrationCheck] = []
    database_kind = "sqlite" if cfg.database_url.startswith("sqlite:///") else "other"
    backup_created: str | None = None

    if database_kind != "sqlite":
        checks.append(_check("database_kind", "error", "v1.0 迁移预检当前只支持 SQLite。"))
        return _report(checks, database_kind, backup_created)

    checks.append(_check("database_kind", "ok", "当前数据库是 SQLite。"))

    if not _database_path_exists():
        checks.append(_check("database_file", "error", "未配置可检查的 SQLite 数据库文件。"))
        return _report(checks, database_kind, backup_created)
    checks.append(_check("database_file", "ok", "SQLite 数据库文件已存在。"))

    if create_backup:
        try:
            backup_created = backup_service.create_pre_v1_backup().file_name
            checks.append(_check("pre_v1_backup", "ok", "已创建 pre-v1.0 数据库备份。"))
        except AppError as exc:
            checks.append(_check("pre_v1_backup", "error", exc.message))

    latest_backup = backup_service.latest_backup()
    if latest_backup is None:
        checks.append(_check("backup_available", "error", "迁移前必须先创建 pre-v1.0 数据库备份。"))
    elif not backup_service.is_backup_valid(latest_backup.file_name):
        checks.append(
            _check(
                "backup_available",
                "error",
                "最新数据库备份未通过 SQLite 完整性校验；请重新运行 --create-backup。",
            )
        )
    elif latest_backup.kind != "pre-v1.0":
        checks.append(
            _check(
                "backup_available",
                "error",
                "最新数据库备份必须是 pre-v1.0 类型；请重新运行 --create-backup。",
            )
        )
    else:
        checks.append(_check("backup_available", "ok", "已找到最新的 pre-v1.0 回滚备份。"))

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing_tables = sorted(REQUIRED_V09_TABLES - table_names)
    if missing_tables:
        checks.append(
            _check(
                "v09_tables",
                "error",
                "缺少 v0.9 基线表：" + ", ".join(missing_tables),
            )
        )
    else:
        checks.append(_check("v09_tables", "ok", "v0.9 基线表已就绪。"))

    missing_indexes: list[str] = []
    for table_name, required_indexes in REQUIRED_V09_INDEXES.items():
        if table_name not in table_names:
            continue
        existing = {item["name"] for item in inspector.get_indexes(table_name)}
        for index_name in sorted(required_indexes - existing):
            missing_indexes.append(f"{table_name}.{index_name}")
    if missing_indexes:
        checks.append(
            _check(
                "v09_indexes",
                "error",
                "缺少 v0.9 基线索引：" + ", ".join(missing_indexes),
            )
        )
    else:
        checks.append(_check("v09_indexes", "ok", "v0.9 查询索引已就绪。"))

    checks.append(_check("identity_schema", "ok", f"身份契约保持 {IDENTITY_SCHEMA_VERSION}。"))
    return _report(checks, database_kind, backup_created)


def _report(
    checks: list[MigrationCheck],
    database_kind: str,
    backup_created: str | None,
) -> MigrationReadinessReport:
    latest_backup = backup_service.latest_backup()
    return MigrationReadinessReport(
        target_version=V1_TARGET_VERSION,
        backend_version=BACKEND_VERSION,
        identity_schema=IDENTITY_SCHEMA_VERSION,
        database_kind=database_kind,
        backup_created=backup_created,
        latest_backup=latest_backup.file_name if latest_backup else None,
        latest_backup_kind=latest_backup.kind if latest_backup else None,
        checks=checks,
    )
