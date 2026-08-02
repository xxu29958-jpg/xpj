"""Connection, authority, and deadline primitives for C07 maintenance actions."""

from __future__ import annotations

import ipaddress
import math
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.database._c07_maintenance_plan import C07MaintenanceUpgradeError

DATABASE_NAME = "ticketbox"
MIGRATOR_ROLE = "ticketbox_migrator"
SCHEMA_OWNER_ROLE = "ticketbox_owner"
_PGPASS_NAME = re.compile(r"\.ticketbox-pgpass-[1-9][0-9]*-[0-9a-f]{32}\Z")
_RESTORE_DATABASE = re.compile(r"ticketbox_c07_restore_[0-9a-f]{32}\Z")
_SHA256_LOWER = re.compile(r"[0-9a-f]{64}\Z")
_MAINTENANCE_DEADLINE_UTC = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):"
    r"(?P<second>[0-9]{2})\.(?P<fraction>[0-9]{7})Z\Z"
)
_ZERO_SHA256 = "0" * 64
_MAXIMUM_MAINTENANCE_MILLISECONDS = 20 * 60 * 1000


def _canonical_operation_id(value: object) -> str:
    try:
        operation = UUID(str(value))
    except (AttributeError, ValueError):
        raise C07MaintenanceUpgradeError(
            "maintenance operation id is invalid"
        ) from None
    canonical = str(operation)
    if (
        operation.int == 0
        or canonical != value
        or operation.version not in {1, 2, 3, 4, 5}
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance operation id is not canonical"
        )
    return canonical


def _restore_database_name(operation_id: str) -> str:
    operation = UUID(_canonical_operation_id(operation_id))
    database = f"ticketbox_c07_restore_{operation.hex}"
    if _RESTORE_DATABASE.fullmatch(database) is None:
        raise AssertionError("C07 restore database naming drifted")
    return database


def _validated_database(
    value: object,
    *,
    operation_id: str,
    isolated_only: bool = False,
) -> str:
    allowed = {_restore_database_name(operation_id)}
    if not isolated_only:
        allowed.add(DATABASE_NAME)
    if not isinstance(value, str) or value not in allowed:
        raise C07MaintenanceUpgradeError(
            "maintenance database is outside the exact C07 operation"
        )
    return value


def _validated_migrator_url(database_url: str, *, database: str) -> URL:
    if not isinstance(database_url, str) or not database_url:
        raise C07MaintenanceUpgradeError(
            "maintenance database URL must be explicit"
        )
    try:
        parsed = make_url(database_url)
    except (SQLAlchemyError, ValueError):
        raise C07MaintenanceUpgradeError(
            "maintenance database URL is invalid"
        ) from None
    if (
        parsed.drivername not in {"postgresql", "postgresql+psycopg"}
        or parsed.username != MIGRATOR_ROLE
        or parsed.password is not None
        or parsed.database != database
        or parsed.host is None
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or set(parsed.query) != {"require_auth"}
        or parsed.query.get("require_auth") != "scram-sha-256"
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance database URL violates the migrator contract"
        )
    try:
        address = ipaddress.ip_address(parsed.host)
    except ValueError:
        raise C07MaintenanceUpgradeError(
            "maintenance database host must be a loopback IP literal"
        ) from None
    if not address.is_loopback:
        raise C07MaintenanceUpgradeError(
            "maintenance database host must be loopback"
        )
    return parsed.set(drivername="postgresql+psycopg")


def _validated_pgpass_path(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.parent.name != "TicketboxInstallerSecrets"
        or _PGPASS_NAME.fullmatch(path.name) is None
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance pgpass path is outside the protected layout"
        )
    return path


@contextmanager
def _temporary_pgpass_environment(path: Path) -> Iterator[None]:
    if "PGPASSWORD" in os.environ:
        raise C07MaintenanceUpgradeError(
            "PGPASSWORD is forbidden for maintenance actions"
        )
    previous = os.environ.get("PGPASSFILE")
    os.environ["PGPASSFILE"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PGPASSFILE", None)
        else:
            os.environ["PGPASSFILE"] = previous


def _create_engine(database_url: URL) -> Engine:
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=utc",
        },
        poolclass=NullPool,
        future=True,
    )


def _maintenance_deadline(value: object) -> datetime:
    if not isinstance(value, str):
        raise C07MaintenanceUpgradeError(
            "maintenance deadline must be canonical UTC"
        )
    match = _MAINTENANCE_DEADLINE_UTC.fullmatch(value)
    if match is None:
        raise C07MaintenanceUpgradeError(
            "maintenance deadline must be canonical UTC"
        )
    fields = {
        key: int(item)
        for key, item in match.groupdict().items()
        if key != "fraction"
    }
    try:
        return datetime(
            **fields,
            microsecond=int(match.group("fraction")[:6]),
            tzinfo=UTC,
        )
    except ValueError:
        raise C07MaintenanceUpgradeError(
            "maintenance deadline must be canonical UTC"
        ) from None


def _remaining_ceiling(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAXIMUM_MAINTENANCE_MILLISECONDS
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance remaining ceiling is invalid"
        )
    return value


def _remaining_milliseconds(
    deadline: datetime,
    *,
    ceiling_ms: int,
) -> int:
    wall_remaining = math.floor(
        (deadline - datetime.now(UTC)).total_seconds() * 1000
    )
    if wall_remaining < 1:
        raise C07MaintenanceUpgradeError("maintenance deadline is stale")
    if wall_remaining > _MAXIMUM_MAINTENANCE_MILLISECONDS:
        raise C07MaintenanceUpgradeError(
            "maintenance deadline exceeds the immutable window"
        )
    return min(wall_remaining, _remaining_ceiling(ceiling_ms))


def _required_lower_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_LOWER.fullmatch(value) is None
        or value == _ZERO_SHA256
    ):
        raise C07MaintenanceUpgradeError(f"{label} hash is invalid")
    return value


def _current_revision(connection: Connection) -> str:
    revisions = tuple(
        str(value)
        for value in connection.scalars(
            text(
                "SELECT version_num FROM public.alembic_version "
                "ORDER BY version_num"
            )
        )
    )
    if len(revisions) != 1:
        raise C07MaintenanceUpgradeError(
            "maintenance database does not have one Alembic revision"
        )
    return revisions[0]


def _assert_migrator_authority(
    connection: Connection,
    *,
    database: str,
) -> None:
    principal = connection.execute(
        text("SELECT session_user, current_user, current_database()")
    ).one()
    if tuple(str(value) for value in principal) != (
        MIGRATOR_ROLE,
        MIGRATOR_ROLE,
        database,
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance connection is not the dedicated migrator"
        )
    roles = connection.execute(
        text(
            "SELECT rolname, rolcanlogin, rolinherit, rolsuper, "
            "rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_catalog.pg_roles WHERE rolname IN "
            "('ticketbox_owner', 'ticketbox_migrator') ORDER BY rolname"
        )
    ).all()
    if tuple(roles) != (
        (SCHEMA_OWNER_ROLE, False, False, False, False, False, False, False),
        (MIGRATOR_ROLE, True, False, False, False, False, False, False),
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance owner/migrator role attributes are not exact"
        )
    membership = connection.execute(
        text(
            "SELECT granted.rolname, member.rolname, membership.admin_option, "
            "membership.inherit_option, membership.set_option "
            "FROM pg_catalog.pg_auth_members AS membership "
            "JOIN pg_catalog.pg_roles AS granted "
            "ON granted.oid = membership.roleid "
            "JOIN pg_catalog.pg_roles AS member "
            "ON member.oid = membership.member "
            "WHERE granted.rolname IN "
            "('ticketbox_owner', 'ticketbox_migrator') "
            "OR member.rolname IN "
            "('ticketbox_owner', 'ticketbox_migrator')"
        )
    ).all()
    if tuple(membership) != (
        (SCHEMA_OWNER_ROLE, MIGRATOR_ROLE, False, False, True),
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance owner/migrator membership is not exact"
        )
    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    effective = connection.execute(
        text("SELECT session_user, current_user")
    ).one()
    if tuple(str(value) for value in effective) != (
        MIGRATOR_ROLE,
        SCHEMA_OWNER_ROLE,
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance migrator could not assume the schema owner"
        )
    owners = connection.execute(
        text(
            "SELECT pg_get_userbyid(database_record.datdba), "
            "pg_get_userbyid(namespace_record.nspowner) "
            "FROM pg_catalog.pg_database AS database_record "
            "JOIN pg_catalog.pg_namespace AS namespace_record "
            "ON namespace_record.nspname = 'public' "
            "WHERE database_record.datname = current_database()"
        )
    ).one_or_none()
    if owners is None or tuple(str(value) for value in owners) != (
        SCHEMA_OWNER_ROLE,
        SCHEMA_OWNER_ROLE,
    ):
        raise C07MaintenanceUpgradeError(
            "maintenance database/schema ownership is not exact"
        )


def _acquire_isolated_writer_fence(connection: Connection) -> None:
    held = connection.scalar(
        text(
            "SELECT pg_try_advisory_lock("
            "hashtext(current_database()), "
            "hashtext('xiaopiaojia:schema'))"
        )
    )
    if held is not True:
        raise C07MaintenanceUpgradeError(
            "maintenance session advisory fence is busy"
        )
    connection.execute(text("SELECT pg_stat_clear_snapshot()"))
    row = connection.execute(
        text(
            "SELECT NOT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_stat_activity "
            "WHERE datid = (SELECT oid FROM pg_catalog.pg_database "
            "WHERE datname = current_database()) "
            "AND pid <> pg_backend_pid() "
            "AND backend_type = 'client backend'), "
            "NOT EXISTS (SELECT 1 FROM pg_catalog.pg_prepared_xacts "
            "WHERE database = current_database()), "
            "NOT EXISTS (SELECT 1 FROM pg_catalog.pg_stat_activity "
            "WHERE pid <> pg_backend_pid() "
            "AND backend_type LIKE 'logical replication%')"
        )
    ).one()
    if tuple(row) != (True, True, True):
        raise C07MaintenanceUpgradeError(
            "isolated replay writer/session fence is not intact"
        )


def _release_session_fence(connection: Connection) -> None:
    if connection.in_transaction():
        connection.rollback()
    released = connection.scalar(
        text(
            "SELECT pg_advisory_unlock("
            "hashtext(current_database()), "
            "hashtext('xiaopiaojia:schema'))"
        )
    )
    connection.commit()
    if released is not True:
        connection.invalidate()
        raise C07MaintenanceUpgradeError(
            "maintenance session advisory fence was not released"
        )


def _apply_local_deadlines(
    connection: Connection,
    *,
    remaining_ms: int,
) -> None:
    rows = connection.execute(
        text(
            "SELECT name, setting, unit FROM pg_catalog.pg_settings "
            "WHERE name IN "
            "('transaction_timeout', 'statement_timeout', 'lock_timeout')"
        )
    ).all()
    settings = {
        str(name): int(str(setting))
        for name, setting, unit in rows
        if str(unit) == "ms"
        and str(setting).isascii()
        and str(setting).isdecimal()
    }
    if set(settings) != {
        "transaction_timeout",
        "statement_timeout",
        "lock_timeout",
    }:
        raise C07MaintenanceUpgradeError(
            "maintenance requires PostgreSQL transaction_timeout support"
        )
    transaction_timeout = settings["transaction_timeout"]
    if not 1 <= transaction_timeout <= remaining_ms:
        raise C07MaintenanceUpgradeError(
            "maintenance transaction_timeout was not armed before BEGIN"
        )
    statement_timeout = settings["statement_timeout"]
    statement_timeout = (
        remaining_ms
        if statement_timeout == 0
        else min(statement_timeout, remaining_ms)
    )
    lock_timeout = settings["lock_timeout"]
    lock_timeout = (
        min(remaining_ms, 5000)
        if lock_timeout == 0
        else min(lock_timeout, remaining_ms, 5000)
    )
    connection.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": f"{statement_timeout}ms"},
    )
    connection.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": f"{lock_timeout}ms"},
    )
