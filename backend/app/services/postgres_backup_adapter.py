"""Bounded PostgreSQL custom-archive mechanism for dataset backup generations.

The caller owns writer quiescence, generation staging, and publication. This
adapter only creates and validates one archive at an explicit target path.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.errors import AppError
from app.services.postgres_backup_validation_service import (
    PostgresBackupValidationError,
    validate_postgres_backup_file_with_tool,
)
from app.services.secure_file import hold_protected_file_for_read

_PG_DUMP_TIMEOUT_SECONDS = 5 * 60
_PG_RESTORE_TIMEOUT_SECONDS = 20 * 60
_PG_DUMP_LOCK_WAIT_MILLISECONDS = 30_000
_PG_TOOL_QUERY_KEYS = frozenset({"connect_timeout", "hostaddr", "options", "require_auth", "sslmode"})
_PG_TOOL_SSL_MODES = frozenset({"allow", "disable", "prefer", "require", "verify-ca", "verify-full"})
_DATABASE_URL_ENVIRONMENT = frozenset(
    {
        "DATABASE_URL",
        "DRILL_RESTORE_URL",
        "DRILL_SOURCE_URL",
        "SMOKE_DATABASE_URL",
        "XPJ_TEST_ADMIN_URL",
        "XPJ_TEST_DATABASE_URL",
    }
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PgToolConnection:
    database_url: str
    username: str
    host: str
    port: int
    database: str


def write_postgres_archive(
    *,
    database_url: str,
    passfile: Path,
    pg_dump_binary: Path,
    pg_restore_binary: Path,
    target: Path,
) -> None:
    connection = _pg_tool_connection(database_url)
    if target.exists() or not target.parent.is_dir():
        raise AppError("backup_incomplete", status_code=500)
    temporary = target.with_name(f".{target.name}.partial")
    try:
        try:
            with _pg_tool_environment(connection, passfile) as environment:
                arguments = [
                    str(pg_dump_binary.resolve(strict=True)),
                    "--no-password",
                    f"--lock-wait-timeout={_PG_DUMP_LOCK_WAIT_MILLISECONDS}",
                    "--format=custom",
                    "--file",
                    str(temporary),
                    "--dbname",
                    connection.database_url,
                ]
                result = subprocess.run(  # noqa: S603 (resolved binary, fixed args)
                    arguments,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    timeout=_PG_DUMP_TIMEOUT_SECONDS,
                )
        except (OSError, subprocess.TimeoutExpired):
            _logger.warning("pg_dump could not complete; diagnostic output omitted")
            raise AppError("server_error", "数据库备份未在安全时限内完成。", status_code=500) from None
        if result.returncode != 0:
            # Native diagnostics may repeat connection material. Keep them out of
            # logs entirely; the return code is enough for the operator-facing gate.
            _logger.warning("pg_dump failed (rc=%s); diagnostic output omitted", result.returncode)
            raise AppError("server_error", "数据库备份失败，请查看后端日志。", status_code=500)
        try:
            validate_postgres_backup_file_with_tool(
                temporary,
                pg_restore_binary=pg_restore_binary,
            )
        except PostgresBackupValidationError:
            raise AppError("server_error", "数据库备份校验失败，未写入最终备份文件。", status_code=500) from None
        temporary.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def restore_postgres_archive(
    *,
    database_url: str,
    passfile: Path,
    pg_restore_binary: Path,
    archive: Path,
    restore_role: str,
) -> None:
    """Restore one verified archive into a caller-proven empty target database."""

    connection = _pg_tool_connection(database_url)
    try:
        validate_postgres_backup_file_with_tool(
            archive,
            pg_restore_binary=pg_restore_binary,
        )
        with _pg_tool_environment(connection, passfile) as environment:
            result = subprocess.run(  # noqa: S603 (resolved binary, fixed args)
                [
                    str(pg_restore_binary.resolve(strict=True)),
                    "--no-password",
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--role",
                    _pg_identifier(restore_role),
                    "--dbname",
                    connection.database_url,
                    str(archive.resolve(strict=True)),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
                stdin=subprocess.DEVNULL,
                timeout=_PG_RESTORE_TIMEOUT_SECONDS,
            )
    except (OSError, PostgresBackupValidationError, subprocess.TimeoutExpired):
        _logger.warning("pg_restore could not complete; diagnostic output omitted")
        raise AppError("backup_incomplete", status_code=500) from None
    if result.returncode != 0:
        _logger.warning("pg_restore failed (rc=%s); diagnostic output omitted", result.returncode)
        raise AppError("backup_incomplete", status_code=500)


def _pg_identifier(value: str) -> str:
    if not value or len(value) > 63 or not value.replace("_", "a").isalnum() or not value[0].isalpha():
        raise AppError("backup_incomplete", status_code=500)
    return value


def _pg_tool_connection(database_url: str) -> _PgToolConnection:
    """Validate and normalize a passwordless libpq URL."""
    try:
        parsed = make_url(database_url)
        backend_name = parsed.get_backend_name()
    except (ArgumentError, TypeError, ValueError):
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    if backend_name != "postgresql":
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)

    if parsed.password is not None:
        raise AppError("server_error", "数据库备份配置不得内嵌口令。", status_code=500)
    query = _validated_query(parsed.query)
    if query.get("require_auth") != "scram-sha-256":
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)
    if not parsed.username or not parsed.host or not parsed.database:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)
    query.setdefault("connect_timeout", "5")
    query.setdefault("sslmode", "prefer")
    try:
        if not 1 <= int(query["connect_timeout"]) <= 30:
            raise ValueError
        if "hostaddr" in query:
            host_address = ipaddress.ip_address(query["hostaddr"])
            host = parsed.host.casefold()
            if host == "localhost":
                if host_address not in {
                    ipaddress.ip_address("127.0.0.1"),
                    ipaddress.ip_address("::1"),
                }:
                    raise ValueError
            elif host_address != ipaddress.ip_address(host):
                raise ValueError
    except ValueError:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    if query.get("sslmode", "prefer") not in _PG_TOOL_SSL_MODES:
        raise AppError("server_error", "数据库备份配置无效。", status_code=500)

    try:
        passwordless = URL.create(
            drivername="postgresql",
            username=parsed.username,
            host=parsed.host,
            port=parsed.port or 5432,
            database=parsed.database,
            query=query,
        )
        rendered_url = passwordless.render_as_string(hide_password=False)
    except (TypeError, ValueError):
        raise AppError("server_error", "数据库备份配置无效。", status_code=500) from None
    return _PgToolConnection(
        database_url=rendered_url,
        username=parsed.username,
        host=parsed.host,
        port=parsed.port or 5432,
        database=parsed.database,
    )


def _validated_query(raw_query: object) -> dict[str, str]:
    query: dict[str, str] = {}
    for raw_key, raw_value in dict(raw_query).items():
        key = str(raw_key).casefold()
        if (
            key in query
            or key not in _PG_TOOL_QUERY_KEYS
            or not isinstance(raw_value, str)
            or any(character in raw_value for character in "\x00\r\n")
        ):
            raise AppError("server_error", "数据库备份配置无效。", status_code=500)
        query[key] = raw_value
    return query


@contextlib.contextmanager
def _pg_tool_environment(
    connection: _PgToolConnection,
    passfile: Path,
) -> Iterator[dict[str, str]]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PG") and key.upper() not in _DATABASE_URL_ENVIRONMENT
    }
    try:
        with hold_protected_file_for_read(passfile) as protected_passfile:
            environment["PGPASSFILE"] = str(protected_passfile)
            yield environment
    except (OSError, ValueError):
        raise AppError("server_error", "数据库备份凭据不可用。", status_code=500) from None
