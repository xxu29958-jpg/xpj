"""PostgreSQL execution boundary for installer-owned schema migrations.

The host owns service lifecycle, credentials, recovery points, and role
retirement. This runtime owns one PostgreSQL transaction: authenticate as the
short-lived migrator, acquire the shared migration lease, assume the schema
owner, execute Alembic on that exact connection, and prove the requested
revision plus its release-specific postcondition before commit.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from psycopg import Error as PsycopgError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.database._release_schema_readiness import (
    ReleaseHeadVerificationError,
    assert_release_head,
)
from app.services.secure_file import hold_protected_file_for_read

_ROLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_MISSING = object()


class ManagedPostgresMigrationRuntimeError(RuntimeError):
    """The managed migration transaction could not be proven safe."""


@dataclass(frozen=True)
class ManagedPostgresRuntimeContractV1:
    database_name: str
    migrator_role: str
    schema_owner_role: str
    lease_label: str
    transaction_timeout_ms: int

    def __post_init__(self) -> None:
        for label, value in (
            ("database", self.database_name),
            ("migrator role", self.migrator_role),
            ("schema owner role", self.schema_owner_role),
        ):
            if _ROLE_NAME.fullmatch(value) is None:
                raise ValueError(f"managed PostgreSQL {label} is invalid")
        if not self.lease_label or "\x00" in self.lease_label:
            raise ValueError("managed PostgreSQL lease label is invalid")
        if (
            isinstance(self.transaction_timeout_ms, bool)
            or not isinstance(self.transaction_timeout_ms, int)
            or self.transaction_timeout_ms <= 0
        ):
            raise ValueError("managed PostgreSQL transaction timeout must be positive")


def _timeout_setting(cursor: Any) -> int:
    cursor.execute("SELECT setting, unit FROM pg_catalog.pg_settings WHERE name = 'transaction_timeout'")
    row = cursor.fetchone()
    if row is None or len(row) != 2 or str(row[1]) != "ms" or not str(row[0]).isascii() or not str(row[0]).isdecimal():
        raise ManagedPostgresMigrationRuntimeError(
            "managed migration requires PostgreSQL transaction_timeout in milliseconds"
        )
    return int(str(row[0]))


def _set_idle_session_timeout(connection: Connection, timeout_ms: int) -> int:
    if connection.in_transaction():
        raise ManagedPostgresMigrationRuntimeError("managed migration timeout must be armed before BEGIN")
    driver_connection = connection.connection.driver_connection
    original_autocommit = bool(driver_connection.autocommit)
    try:
        driver_connection.autocommit = True
        with driver_connection.cursor() as cursor:
            previous_ms = _timeout_setting(cursor)
            effective_ms = timeout_ms if previous_ms == 0 else min(previous_ms, timeout_ms)
            cursor.execute(
                "SELECT set_config('transaction_timeout', %s, false)",
                (f"{effective_ms}ms",),
            )
            if _timeout_setting(cursor) != effective_ms:
                raise ManagedPostgresMigrationRuntimeError("managed migration pre-BEGIN timeout was not effective")
            return previous_ms
    finally:
        driver_connection.autocommit = original_autocommit


def _restore_idle_session_timeout(connection: Connection, previous_ms: int) -> None:
    if connection.in_transaction():
        connection.rollback()
    driver_connection = connection.connection.driver_connection
    original_autocommit = bool(driver_connection.autocommit)
    try:
        driver_connection.autocommit = True
        with driver_connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('transaction_timeout', %s, false)",
                (f"{previous_ms}ms",),
            )
            if _timeout_setting(cursor) != previous_ms:
                raise ManagedPostgresMigrationRuntimeError("managed migration timeout was not restored")
    finally:
        driver_connection.autocommit = original_autocommit


@contextmanager
def _prearmed_transaction(
    connection: Connection,
    *,
    timeout_ms: int,
) -> Iterator[Connection]:
    previous_ms = _set_idle_session_timeout(connection, timeout_ms)
    committed = False
    try:
        with connection.begin():
            yield connection
        committed = True
    finally:
        if not connection.invalidated and not connection.closed:
            try:
                _restore_idle_session_timeout(connection, previous_ms)
            except (ManagedPostgresMigrationRuntimeError, PsycopgError, SQLAlchemyError):
                connection.invalidate()
                if committed:
                    raise


@contextmanager
def _temporary_pgpass_environment(path: Path) -> Iterator[None]:
    if "PGPASSWORD" in os.environ:
        raise ManagedPostgresMigrationRuntimeError("PGPASSWORD is forbidden for a managed migration")
    previous = os.environ.get("PGPASSFILE")
    os.environ["PGPASSFILE"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PGPASSFILE", None)
        else:
            os.environ["PGPASSFILE"] = previous


def _validated_migrator_url(
    database_url: str,
    *,
    contract: ManagedPostgresRuntimeContractV1,
) -> URL:
    if not isinstance(database_url, str) or not database_url:
        raise ManagedPostgresMigrationRuntimeError("managed migration database URL must be explicit")
    try:
        parsed = make_url(database_url)
    except ArgumentError as exc:
        raise ManagedPostgresMigrationRuntimeError("managed migration database URL is invalid") from exc
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ManagedPostgresMigrationRuntimeError("managed migration requires PostgreSQL psycopg")
    if (
        parsed.username != contract.migrator_role
        or parsed.password is not None
        or parsed.database != contract.database_name
        or parsed.host is None
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or set(parsed.query) != {"require_auth"}
        or parsed.query.get("require_auth") != "scram-sha-256"
    ):
        raise ManagedPostgresMigrationRuntimeError("managed migration database URL violates the migrator contract")
    try:
        address = ipaddress.ip_address(parsed.host)
    except ValueError as exc:
        raise ManagedPostgresMigrationRuntimeError("managed migration host must be a loopback IP literal") from exc
    if not address.is_loopback:
        raise ManagedPostgresMigrationRuntimeError("managed migration host must be loopback")
    return parsed.set(drivername="postgresql+psycopg")


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


class ManagedPostgresMigrationRuntimeV1:
    """Execute one release migration without owning its host lifecycle."""

    def __init__(self, contract: ManagedPostgresRuntimeContractV1) -> None:
        self._contract = contract

    def run(
        self,
        *,
        database_url: str,
        pgpassfile: Path,
        alembic_config: Config,
        source_revision: str,
        target_revision: str,
        verify_postcondition: Callable[[Connection], None],
    ) -> str:
        parsed_url = _validated_migrator_url(database_url, contract=self._contract)
        if not isinstance(pgpassfile, Path) or not pgpassfile.is_absolute():
            raise ManagedPostgresMigrationRuntimeError("managed migration pgpass path must be absolute")
        engine: Engine | None = None
        try:
            with (
                hold_protected_file_for_read(pgpassfile) as protected_pgpass,
                _temporary_pgpass_environment(protected_pgpass),
            ):
                engine = _create_engine(parsed_url)
                with (
                    engine.connect() as connection,
                    _prearmed_transaction(
                        connection,
                        timeout_ms=self._contract.transaction_timeout_ms,
                    ),
                ):
                    result = self._run_transaction(
                        connection,
                        alembic_config=alembic_config,
                        source_revision=source_revision,
                        target_revision=target_revision,
                        verify_postcondition=verify_postcondition,
                    )
            return result
        except ManagedPostgresMigrationRuntimeError:
            raise
        except (CommandError, OSError, PsycopgError, RuntimeError, SQLAlchemyError) as exc:
            raise ManagedPostgresMigrationRuntimeError("managed PostgreSQL migration failed") from exc
        finally:
            if engine is not None:
                engine.dispose()

    def _run_transaction(
        self,
        connection: Connection,
        *,
        alembic_config: Config,
        source_revision: str,
        target_revision: str,
        verify_postcondition: Callable[[Connection], None],
    ) -> str:
        self._assert_migrator_context(connection)
        self._assume_schema_owner(connection)

        if self._is_target_revision(connection, target_revision=target_revision):
            verify_postcondition(connection)
            return "target_observed_after_interruption"

        self._assert_source_revision(connection, source_revision=source_revision)
        self._run_alembic_upgrade(
            connection,
            alembic_config=alembic_config,
            target_revision=target_revision,
        )
        try:
            assert_release_head(connection, expected_revision=target_revision)
            verify_postcondition(connection)
        except ReleaseHeadVerificationError as exc:
            raise ManagedPostgresMigrationRuntimeError("managed migration did not reach the release head") from exc
        return "target_committed"

    def _assert_migrator_context(self, connection: Connection) -> None:
        principal = tuple(
            str(value)
            for value in connection.execute(text("SELECT session_user, current_user, current_database()")).one()
        )
        expected_principal = (
            self._contract.migrator_role,
            self._contract.migrator_role,
            self._contract.database_name,
        )
        if principal != expected_principal:
            raise ManagedPostgresMigrationRuntimeError("managed migration connection is not the dedicated migrator")
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(current_database()), hashtext(:label))"),
            {"label": self._contract.lease_label},
        )
        if acquired is not True:
            raise ManagedPostgresMigrationRuntimeError("managed schema migration lease is busy")
        other_clients = connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datid = (SELECT oid FROM pg_database "
                "WHERE datname = current_database()) "
                "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )
        )
        if int(other_clients or 0) != 0:
            raise ManagedPostgresMigrationRuntimeError("managed migration observed another client session")

    def _assume_schema_owner(self, connection: Connection) -> None:
        owner = connection.dialect.identifier_preparer.quote_identifier(self._contract.schema_owner_role)
        connection.execute(text(f"SET LOCAL ROLE {owner}"))
        effective = tuple(str(value) for value in connection.execute(text("SELECT session_user, current_user")).one())
        if effective != (
            self._contract.migrator_role,
            self._contract.schema_owner_role,
        ):
            raise ManagedPostgresMigrationRuntimeError("managed migrator cannot assume the schema owner")

    @staticmethod
    def _is_target_revision(
        connection: Connection,
        *,
        target_revision: str,
    ) -> bool:
        try:
            assert_release_head(connection, expected_revision=target_revision)
        except ReleaseHeadVerificationError:
            return False
        return True

    @staticmethod
    def _assert_source_revision(
        connection: Connection,
        *,
        source_revision: str,
    ) -> None:
        try:
            assert_release_head(connection, expected_revision=source_revision)
        except ReleaseHeadVerificationError as exc:
            raise ManagedPostgresMigrationRuntimeError(
                "managed migration live revision is outside the release path"
            ) from exc

    @staticmethod
    def _run_alembic_upgrade(
        connection: Connection,
        *,
        alembic_config: Config,
        target_revision: str,
    ) -> None:
        previous_connection = alembic_config.attributes.get("connection", _MISSING)
        try:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, target_revision)
        finally:
            if previous_connection is _MISSING:
                alembic_config.attributes.pop("connection", None)
            else:
                alembic_config.attributes["connection"] = previous_connection


__all__ = [
    "ManagedPostgresMigrationRuntimeError",
    "ManagedPostgresMigrationRuntimeV1",
    "ManagedPostgresRuntimeContractV1",
]
