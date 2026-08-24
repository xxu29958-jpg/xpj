"""Fresh-install Alembic upgrade on a caller-owned connection.

This path does not load DATABASE_GENERATION_PROGRAM.json. The lifecycle
coordinator supplies the exact target revision and dataset identity. Alembic
remains the only alembic_version writer.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

from app.database._managed_postgres_contract import DATABASE_NAME, MIGRATOR_ROLE, SCHEMA_OWNER_ROLE
from app.database._managed_postgres_migration_runtime import _prearmed_transaction
from app.database._managed_postgres_role_authority import (
    ManagedPostgresRoleAuthorityError,
    assume_managed_postgres_schema_owner,
)
from app.database._managed_postgres_url import ManagedPostgresUrlError, validated_local_role_url
from app.database._postgres_operation_failures import (
    close_postgres_owner_resources,
    raise_postgres_operation_failures,
)
from app.services.secure_file import hold_protected_file_for_read

RESULT_SCHEMA = "ticketbox-fresh-schema-upgrade-result-v1"
_MANAGED_JSON_PROTOCOL_ATTRIBUTE = "ticketbox_managed_migration_json_protocol_v1"
_ALEMBIC_REVISION = r"^[0-9]{8}_[0-9]{4}$"
_SEMANTIC_REVISION = r"^ticketbox-dataset-semantics-v[1-9][0-9]*$"
_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000


class FreshSchemaUpgradeError(RuntimeError):
    """The fresh-install schema upgrade could not be proven."""


class _FreshRoleContract:
    database_name = DATABASE_NAME
    migrator_role = MIGRATOR_ROLE
    schema_owner_role = SCHEMA_OWNER_ROLE


def _backend_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        if isinstance(bundle, str) and bundle:
            return Path(bundle)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise FreshSchemaUpgradeError(f"{label} is not a UUID") from exc
    if value != canonical:
        raise FreshSchemaUpgradeError(f"{label} is not canonical")
    return canonical


def _require_revision(value: str, *, label: str) -> str:
    import re

    if re.fullmatch(_ALEMBIC_REVISION, value) is None:
        raise FreshSchemaUpgradeError(f"{label} is not an Alembic revision")
    return value


def _alembic_config(connection: Connection) -> Config:
    root = _backend_root()
    try:
        ini_path = (root / "alembic.ini").resolve(strict=True)
        script_path = (root / "migrations").resolve(strict=True)
    except OSError as exc:
        raise FreshSchemaUpgradeError("fresh-install Alembic environment is unavailable") from exc
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(script_path))
    config.attributes["connection"] = connection
    config.attributes[_MANAGED_JSON_PROTOCOL_ATTRIBUTE] = True
    return config


def _current_revision(connection: Connection) -> str | None:
    heads = tuple(
        str(value)
        for value in MigrationContext.configure(
            connection, opts={"version_table_schema": "public"}
        ).get_current_heads()
    )
    if len(heads) > 1:
        raise FreshSchemaUpgradeError("database has multiple Alembic heads")
    return heads[0] if heads else None


@contextmanager
def _temporary_pgpass_environment(path: Path) -> Iterator[None]:
    if "PGPASSWORD" in os.environ:
        raise FreshSchemaUpgradeError("PGPASSWORD is forbidden for fresh schema upgrade")
    previous = os.environ.get("PGPASSFILE")
    os.environ["PGPASSFILE"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("PGPASSFILE", None)
        else:
            os.environ["PGPASSFILE"] = previous


def _bind_dataset_authority(
    connection: Connection,
    *,
    dataset_id: str,
    client_generation: str,
    target_revision: str,
    schema_min_compatible: str,
    semantic_revision: str,
) -> None:
    import re

    if not schema_min_compatible or len(schema_min_compatible) > 64:
        raise FreshSchemaUpgradeError("schema_min_compatible is invalid")
    if re.fullmatch(_SEMANTIC_REVISION, semantic_revision) is None:
        raise FreshSchemaUpgradeError("semantic_revision is invalid")
    row = connection.execute(
        text(
            "SELECT dataset_id, client_generation, restore_epoch, restored_from_backup_id "
            "FROM dataset_authority WHERE singleton_id = 1"
        )
    ).mappings().first()
    if row is None:
        connection.execute(
            text(
                "INSERT INTO dataset_authority ("
                "singleton_id, dataset_id, client_generation, restore_epoch, "
                "schema_revision, schema_min_compatible, semantic_revision, "
                "created_at, restored_from_backup_id"
                ") VALUES ("
                "1, :dataset_id, :client_generation, 0, :schema_revision, "
                ":schema_min_compatible, :semantic_revision, :created_at, NULL)"
            ),
            {
                "dataset_id": dataset_id,
                "client_generation": client_generation,
                "schema_revision": target_revision,
                "schema_min_compatible": schema_min_compatible,
                "semantic_revision": semantic_revision,
                "created_at": datetime.now(UTC),
            },
        )
        return
    if int(row["restore_epoch"]) != 0 or row["restored_from_backup_id"] is not None:
        raise FreshSchemaUpgradeError("dataset_authority is not a fresh empty seed")
    if row["dataset_id"] not in {dataset_id} or row["client_generation"] not in {client_generation}:
        business = int(
            connection.execute(
                text("SELECT count(*) FROM accounts")
            ).scalar_one()
        )
        if business:
            raise FreshSchemaUpgradeError("existing business rows refuse identity replacement")
    updated = connection.execute(
        text(
            "UPDATE dataset_authority SET "
            "dataset_id = :dataset_id, client_generation = :client_generation, "
            "schema_revision = :schema_revision, "
            "schema_min_compatible = :schema_min_compatible, "
            "semantic_revision = :semantic_revision "
            "WHERE singleton_id = 1 AND restore_epoch = 0 "
            "AND restored_from_backup_id IS NULL"
        ),
        {
            "dataset_id": dataset_id,
            "client_generation": client_generation,
            "schema_revision": target_revision,
            "schema_min_compatible": schema_min_compatible,
            "semantic_revision": semantic_revision,
        },
    )
    if updated.rowcount != 1:
        raise FreshSchemaUpgradeError("dataset_authority bind did not update the singleton row")


def _run_on_connection(
    connection: Connection,
    *,
    target_revision: str,
    dataset_id: str,
    client_generation: str,
    schema_min_compatible: str,
    semantic_revision: str,
) -> str:
    if not connection.in_transaction():
        raise FreshSchemaUpgradeError("fresh schema upgrade requires an active caller transaction")
    try:
        assume_managed_postgres_schema_owner(
            connection,
            contract=_FreshRoleContract(),
        )
    except ManagedPostgresRoleAuthorityError as exc:
        raise FreshSchemaUpgradeError(str(exc)) from exc
    current = _current_revision(connection)
    if current != target_revision:
        try:
            command.upgrade(_alembic_config(connection), target_revision)
        except CommandError as exc:
            raise FreshSchemaUpgradeError("Alembic did not reach the exact target") from exc
        if _current_revision(connection) != target_revision:
            raise FreshSchemaUpgradeError("alembic_version is not the exact target")
        result = "upgraded"
    else:
        result = "already-at-target"
    _bind_dataset_authority(
        connection,
        dataset_id=dataset_id,
        client_generation=client_generation,
        target_revision=target_revision,
        schema_min_compatible=schema_min_compatible,
        semantic_revision=semantic_revision,
    )
    return result


def _validated_fresh_url(database_url: str):
    try:
        parsed_url = validated_local_role_url(
            database_url,
            database_name=DATABASE_NAME,
            role=MIGRATOR_ROLE,
            purpose="fresh schema upgrade",
        )
    except ManagedPostgresUrlError as exc:
        raise FreshSchemaUpgradeError(str(exc)) from exc
    if make_url(database_url).password is not None:
        raise FreshSchemaUpgradeError("fresh schema upgrade URL must not carry a password")
    return parsed_url


def _execute_fresh_upgrade(
    *,
    parsed_url,
    pgpassfile: Path,
    target: str,
    dataset_id: str,
    client_generation: str,
    schema_min_compatible: str,
    semantic_revision: str,
) -> str:
    engine: Engine | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    result: str | None = None
    entered_contexts: list[AbstractContextManager[Any]] = []
    try:
        protected_context = hold_protected_file_for_read(pgpassfile)
        protected_pgpass = protected_context.__enter__()
        entered_contexts.append(protected_context)
        environment_context = _temporary_pgpass_environment(protected_pgpass)
        environment_context.__enter__()
        entered_contexts.append(environment_context)
        engine = create_engine(
            parsed_url,
            connect_args={"connect_timeout": 10, "options": "-c timezone=utc"},
            poolclass=NullPool,
            future=True,
        )
        connection_context = engine.connect()
        connection = connection_context.__enter__()
        entered_contexts.append(connection_context)
        with _prearmed_transaction(
            connection,
            timeout_ms=_TRANSACTION_TIMEOUT_MS,
            access_mode="read_write",
        ):
            result = _run_on_connection(
                connection,
                target_revision=target,
                dataset_id=dataset_id,
                client_generation=client_generation,
                schema_min_compatible=schema_min_compatible,
                semantic_revision=semantic_revision,
            )
    except BaseException as exc:  # noqa: BLE001 - explicit owner boundary
        primary = exc
    finally:
        primary = close_postgres_owner_resources(
            contexts=entered_contexts,
            engine=engine,
            primary=primary,
            cleanup=cleanup,
        )
    raise_postgres_operation_failures(
        primary=primary,
        cleanup=cleanup,
        message="fresh schema upgrade and cleanup failed",
    )
    if result is None:
        raise FreshSchemaUpgradeError("fresh schema upgrade produced no result")
    return result


def run_fresh_schema_upgrade_action(
    *,
    database_url: str,
    pgpassfile: Path,
    target_revision: str,
    dataset_id: str,
    client_generation: str,
    schema_min_compatible: str,
    semantic_revision: str,
    operation_id: str,
) -> dict[str, object]:
    _canonical_uuid(dataset_id, label="dataset_id")
    _canonical_uuid(client_generation, label="client_generation")
    if not operation_id or "\x00" in operation_id:
        raise FreshSchemaUpgradeError("operation_id is invalid")
    target = _require_revision(target_revision, label="target_revision")
    if not isinstance(pgpassfile, Path) or not pgpassfile.is_absolute():
        raise FreshSchemaUpgradeError("pgpass path must be absolute")
    result = _execute_fresh_upgrade(
        parsed_url=_validated_fresh_url(database_url),
        pgpassfile=pgpassfile,
        target=target,
        dataset_id=dataset_id,
        client_generation=client_generation,
        schema_min_compatible=schema_min_compatible,
        semantic_revision=semantic_revision,
    )
    return {
        "schema": RESULT_SCHEMA,
        "target_revision": target,
        "alembic_revision": target,
        "dataset_id": dataset_id,
        "client_generation": client_generation,
        "result": result,
    }


__all__ = [
    "FreshSchemaUpgradeError",
    "RESULT_SCHEMA",
    "run_fresh_schema_upgrade_action",
]
