"""Admit the installed backend from explicit instance identity and live PostgreSQL authority."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database._database_generation_runtime_queries import (
    RUNTIME_AUTHORITY_FIELDS,
    RUNTIME_AUTHORITY_QUERY,
)
from app.database._lifecycle import DatabaseMigrationPreflightError
from app.database._managed_postgres_contract import DATABASE_NAME, RUNTIME_ROLE

_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_PRODUCT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_SEMANTIC_REVISION = "ticketbox-dataset-semantics-v1"


class DatabaseGenerationAdmissionError(RuntimeError):
    """The live dataset does not exactly match this installed instance."""


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DatabaseGenerationAdmissionError(f"{label} is not a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError(f"{label} is not a canonical UUID") from exc
    if canonical != value:
        raise DatabaseGenerationAdmissionError(f"{label} is not a canonical UUID")
    return canonical


def _explicit_identity() -> tuple[str, str]:
    installation_id = os.environ.get("TICKETBOX_INSTALLATION_ID")
    dataset_id = os.environ.get("TICKETBOX_DATASET_ID")
    if not installation_id or not dataset_id:
        raise DatabaseGenerationAdmissionError("explicit runtime identity is incomplete")
    return (
        _canonical_uuid(installation_id, "installation_id"),
        _canonical_uuid(dataset_id, "dataset_id"),
    )


def _target_revision(program: object) -> str:
    target = getattr(program, "target_revision", None)
    if not isinstance(target, str) or _REVISION.fullmatch(target) is None:
        raise DatabaseGenerationAdmissionError("installed program target_revision is invalid")
    return target


def _observe(engine: object) -> tuple[tuple[str, ...], dict[str, object]]:
    try:
        with engine.connect() as connection:  # type: ignore[union-attr]
            revisions = tuple(
                str(value)
                for value in connection.scalars(
                    text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                )
            )
            row = connection.execute(RUNTIME_AUTHORITY_QUERY).mappings().first()
    except (OSError, RuntimeError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live dataset_authority is unavailable") from exc
    if row is None:
        raise DatabaseGenerationAdmissionError("live dataset_authority is unavailable")
    values = dict(row)
    if set(values) != set(RUNTIME_AUTHORITY_FIELDS):
        raise DatabaseGenerationAdmissionError("live dataset_authority is incomplete")
    return revisions, values


def _assert_exact_authority(
    values: Mapping[str, object],
    *,
    installation_id: str,
    dataset_id: str,
    target_revision: str,
    revisions: tuple[str, ...],
) -> None:
    if values["session_user"] != RUNTIME_ROLE or values["current_user"] != RUNTIME_ROLE:
        raise DatabaseGenerationAdmissionError("live connection is not the exact runtime role")
    if values["current_database"] != DATABASE_NAME:
        raise DatabaseGenerationAdmissionError("live connection is not the runtime database")
    capability_failures = (
        ("runtime_role_ready", "runtime role policy"),
        ("runtime_role_isolated", "runtime role isolation"),
        ("runtime_database_ready", "runtime database privileges"),
        ("runtime_schema_ready", "runtime schema privileges"),
        ("runtime_tables_ready", "runtime table privileges"),
        ("runtime_sequences_ready", "runtime sequence privileges"),
    )
    for field, label in capability_failures:
        if values[field] is not True:
            raise DatabaseGenerationAdmissionError(f"live {label} is not exact")
    live_dataset_id = values["dataset_id"]
    client_generation = values["client_generation"]
    restore_epoch = values["restore_epoch"]
    schema_revision = values["schema_revision"]
    schema_min_compatible = values["schema_min_compatible"]
    semantic_revision = values["semantic_revision"]
    restored_from_backup_id = values["restored_from_backup_id"]
    if _canonical_uuid(live_dataset_id, "live dataset_id") != dataset_id:
        raise DatabaseGenerationAdmissionError("live dataset_id does not match the installed instance")
    if _canonical_uuid(client_generation, "live installation_id") != installation_id:
        raise DatabaseGenerationAdmissionError("live installation_id does not match the installed instance")
    if type(restore_epoch) is not int or restore_epoch != 0 or restored_from_backup_id is not None:
        raise DatabaseGenerationAdmissionError("live authority is not a fresh dataset")
    if schema_revision != target_revision or revisions != (target_revision,):
        raise DatabaseGenerationAdmissionError("live schema is not the installed program target")
    if not isinstance(schema_min_compatible, str) or _PRODUCT_VERSION.fullmatch(schema_min_compatible) is None:
        raise DatabaseGenerationAdmissionError("schema_min_compatible is not a product version")
    if semantic_revision != _SEMANTIC_REVISION:
        raise DatabaseGenerationAdmissionError("live dataset semantics are not the closed contract")


def assert_database_generation_startup_ready(engine: object, program: object) -> None:
    """Fail closed unless the one live dataset belongs to this fresh installation."""

    try:
        installation_id, dataset_id = _explicit_identity()
        target_revision = _target_revision(program)
        revisions, values = _observe(engine)
        _assert_exact_authority(
            values,
            installation_id=installation_id,
            dataset_id=dataset_id,
            target_revision=target_revision,
            revisions=revisions,
        )
    except DatabaseGenerationAdmissionError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:live dataset_authority 未完成 exact binding({exc})。"
        ) from exc


__all__ = ["DatabaseGenerationAdmissionError", "assert_database_generation_startup_ready"]
