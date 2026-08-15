"""Connection, secret, and Alembic execution helpers for C07 production."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool

from app.database._c07_production_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    DATABASE_AUTHORITY_SCHEMA,
    DATABASE_NAME,
    MAINTENANCE_WINDOW_SECONDS,
    MAX_AUTHORITY_ARTIFACT_BYTES,
    MIGRATOR_ROLE,
    C07ProductionMigrationError,
)
from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
    execute_database_generation,
)
from app.database._database_generation_program import DatabaseGenerationProgram

_SERVER_TIMEOUT_NAMES = (
    "transaction_timeout",
    "statement_timeout",
    "lock_timeout",
)


def _database_binding_sha256(
    *,
    installation_id: str,
    cluster_system_identifier: str,
    database_oid: str,
    logical_server_id: str,
    logical_data_generation: str,
) -> str:
    text_value = "\n".join(
        (
            f"schema={DATABASE_AUTHORITY_SCHEMA}",
            f"installation_id={installation_id}",
            f"cluster_system_identifier={cluster_system_identifier}",
            f"database_name={DATABASE_NAME}",
            f"database_oid={database_oid}",
            f"logical_server_id={logical_server_id}",
            f"data_generation={logical_data_generation}",
            "",
        )
    )
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest().upper()


def _validated_migrator_url(database_url: str) -> URL:
    if not isinstance(database_url, str) or not database_url:
        raise C07ProductionMigrationError(
            "production database URL must be explicit"
        )
    try:
        parsed = make_url(database_url)
    except ArgumentError as exc:
        raise C07ProductionMigrationError(
            "production database URL is invalid"
        ) from exc
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise C07ProductionMigrationError(
            "production database URL must use PostgreSQL psycopg"
        )
    if (
        parsed.username != MIGRATOR_ROLE
        or parsed.password is not None
        or parsed.database != DATABASE_NAME
        or parsed.host is None
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or set(parsed.query) != {"require_auth"}
        or parsed.query.get("require_auth") != "scram-sha-256"
    ):
        raise C07ProductionMigrationError(
            "production database URL violates the migrator contract"
        )
    try:
        address = ipaddress.ip_address(parsed.host)
    except ValueError as exc:
        raise C07ProductionMigrationError(
            "production database URL host must be a loopback IP literal"
        ) from exc
    if not address.is_loopback:
        raise C07ProductionMigrationError(
            "production database URL host must be loopback"
        )
    return parsed.set(drivername="postgresql+psycopg")


def _validated_pgpass_path(path: Path) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.parent.name != "TicketboxInstallerSecrets"
        or re.fullmatch(
            r"\.ticketbox-pgpass-[1-9][0-9]*-[0-9a-f]{32}",
            path.name,
        )
        is None
    ):
        raise C07ProductionMigrationError(
            "production pgpass path is outside the protected temporary layout"
        )
    return path


@contextmanager
def _temporary_pgpass_environment(path: Path) -> Iterator[None]:
    if "PGPASSWORD" in os.environ:
        raise C07ProductionMigrationError(
            "PGPASSWORD is forbidden for the production migration action"
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


def _read_held_artifact(path: Path) -> bytes:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_AUTHORITY_ARTIFACT_BYTES + 1)
    except OSError as exc:
        raise C07ProductionMigrationError(
            "production authority artifact could not be read"
        ) from exc
    if len(raw) > MAX_AUTHORITY_ARTIFACT_BYTES:
        raise C07ProductionMigrationError(
            "production authority artifact exceeds its size bound"
        )
    return raw


def _create_production_engine(database_url: URL) -> Engine:
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": 10,
            "options": "-c timezone=utc",
        },
        poolclass=NullPool,
        future=True,
    )


def _revision(connection: Any) -> str | None:
    if not inspect(connection).has_table("alembic_version"):
        return None
    revisions = tuple(
        connection.scalars(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    )
    if len(revisions) > 1:
        raise C07ProductionMigrationError(
            "production database has multiple Alembic revisions"
        )
    return None if not revisions else str(revisions[0])


def _apply_server_deadline(
    connection: Any,
    *,
    timeout_ms: int,
) -> dict[str, int]:
    """Apply the production ceiling without widening tighter caller settings."""

    rows = connection.execute(
        text(
            "SELECT name, setting, unit "
            "FROM pg_catalog.pg_settings "
            "WHERE name IN ("
            "'transaction_timeout', 'statement_timeout', 'lock_timeout'"
            ") ORDER BY name"
        )
    ).all()
    settings: dict[str, int] = {}
    for name, setting, unit in rows:
        name_text = str(name)
        setting_text = str(setting)
        if (
            name_text not in _SERVER_TIMEOUT_NAMES
            or name_text in settings
            or str(unit) != "ms"
            or not setting_text.isascii()
            or not setting_text.isdecimal()
        ):
            raise C07ProductionMigrationError(
                "C07 production PostgreSQL timeout authority is invalid"
            )
        settings[name_text] = int(setting_text)
    if set(settings) != set(_SERVER_TIMEOUT_NAMES):
        raise C07ProductionMigrationError(
            "C07 production requires PostgreSQL transaction_timeout support"
        )

    transaction_timeout_ms = settings["transaction_timeout"]
    if (
        transaction_timeout_ms <= 0
        or transaction_timeout_ms > MAINTENANCE_WINDOW_SECONDS * 1000
    ):
        raise C07ProductionMigrationError(
            "C07 production transaction_timeout was not armed before BEGIN"
        )

    effective: dict[str, int] = {
        "transaction_timeout": transaction_timeout_ms,
    }
    for name in ("statement_timeout", "lock_timeout"):
        ceiling_ms = min(timeout_ms, 5000) if name == "lock_timeout" else timeout_ms
        configured_ms = settings[name]
        applied_ms = (
            ceiling_ms
            if configured_ms == 0
            else min(configured_ms, ceiling_ms)
        )
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": name, "value": f"{applied_ms}ms"},
        )
        effective[name] = applied_ms
    return effective


def _run_alembic_upgrade(
    connection: Any,
    *,
    program: DatabaseGenerationProgram,
    ceremony_id: str,
    deadline: float,
) -> None:
    if deadline <= time.monotonic():
        raise C07ProductionMigrationError(
            "C07 production maintenance window has expired"
        )
    remaining_ms = min(
        MAINTENANCE_WINDOW_SECONDS * 1000,
        max(1, int((deadline - time.monotonic()) * 1000)),
    )
    _apply_server_deadline(
        connection,
        timeout_ms=remaining_ms,
    )
    try:
        execute_database_generation(
            connection,
            program=program,
            source_revision=C07_SOURCE_REVISION,
            target_revision=C07_TARGET_REVISION,
            operation_id=ceremony_id,
        )
    except DatabaseGenerationExecutionError as exc:
        raise C07ProductionMigrationError(
            "C07 production generation execution failed"
        ) from exc
