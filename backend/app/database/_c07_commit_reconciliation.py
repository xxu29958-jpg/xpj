"""Fresh-connection reconciliation for a staged C07 receipt."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.database._c07_contract import (
    C07_CEREMONY_ID_KEY,
    C07_LIFECYCLE_PENDING,
    C07_LIFECYCLE_STATE_KEY,
    C07_RECEIPT_SHA256_KEY,
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    C07CeremonyError,
    C07ReceiptRepairRequiredError,
)
from app.database._c07_execution import _revision
from app.database._c07_receipt_validation import validate_receipt_against_live_database
from app.money_contract import MONEY_COLUMNS_V1
from app.services.secure_file import hold_protected_file_for_read

_COMMIT_CONFIRMED = "commit_confirmed"
_ROLLBACK_CONFIRMED = "rollback_confirmed"
_COMMIT_AMBIGUOUS = "commit_ambiguous"


def _money_storage_kind(connection) -> str:
    """Return ``int4``/``int8`` only when every C07 money root agrees."""

    kinds: set[str] = set()
    for contract in MONEY_COLUMNS_V1:
        kind = connection.scalar(
            text(
                "SELECT CASE "
                "WHEN attribute.atttypid = 'pg_catalog.int4'::regtype "
                "THEN 'int4' "
                "WHEN attribute.atttypid = 'pg_catalog.int8'::regtype "
                "THEN 'int8' "
                "ELSE 'other' END "
                "FROM pg_catalog.pg_attribute AS attribute "
                "WHERE attribute.attrelid = "
                "pg_catalog.to_regclass(:table) "
                "AND attribute.attname = :column "
                "AND attribute.attnum > 0 "
                "AND NOT attribute.attisdropped"
            ),
            {
                "table": f"public.{contract.table}",
                "column": contract.column,
            },
        )
        if kind is None:
            return "mixed_or_missing"
        kinds.add(str(kind))
    if kinds == {"int4"}:
        return "int4"
    if kinds == {"int8"}:
        return "int8"
    return "mixed_or_missing"


def _classify_staged_receipt_commit(
    source_engine: Engine,
    *,
    ceremony_id: str,
    receipt_sha256: str,
    receipt_payload: bytes,
) -> str:
    """Re-observe a lost COMMIT response through a new connection.

    ``COMMIT`` errors are not rollback evidence: the server may have durably
    committed and only the response was lost.  Confirmation therefore binds
    the exact revision, all money storage types, the PENDING lifecycle tuple,
    and the staged receipt digest/content.  Only the exact old revision with
    every money column still ``int4`` proves rollback.  Connection failures,
    partial DDL, marker drift, and every other shape remain ambiguous.
    """

    try:
        with source_engine.connect() as connection:
            current_revision = _revision(connection)
            storage_kind = _money_storage_kind(connection)
            if (
                current_revision == C07_SOURCE_REVISION
                and storage_kind == "int4"
            ):
                return _ROLLBACK_CONFIRMED
            if (
                current_revision != C07_TARGET_REVISION
                or storage_kind != "int8"
            ):
                return _COMMIT_AMBIGUOUS
            stored = dict(
                connection.execute(
                    text(
                        "SELECT key, value FROM app_meta "
                        "WHERE key IN "
                        "(:ceremony_key, :sha_key, :state_key)"
                    ),
                    {
                        "ceremony_key": C07_CEREMONY_ID_KEY,
                        "sha_key": C07_RECEIPT_SHA256_KEY,
                        "state_key": C07_LIFECYCLE_STATE_KEY,
                    },
                ).all()
            )
            if (
                stored.get(C07_CEREMONY_ID_KEY) != ceremony_id
                or stored.get(C07_RECEIPT_SHA256_KEY) != receipt_sha256
                or stored.get(C07_LIFECYCLE_STATE_KEY)
                != C07_LIFECYCLE_PENDING
            ):
                return _COMMIT_AMBIGUOUS
            validate_receipt_against_live_database(
                connection,
                payload=receipt_payload,
                ceremony_id=ceremony_id,
                receipt_sha256=receipt_sha256,
            )
            return _COMMIT_CONFIRMED
    except (C07CeremonyError, OSError, SQLAlchemyError, ValueError):
        # The original transaction connection is not evidence after a COMMIT
        # error.  Failure to obtain or validate a fresh observation must keep
        # the only durable repair payload.
        return _COMMIT_AMBIGUOUS


def _remove_confirmed_rollback_receipt(
    *,
    temporary: Path,
    receipt_payload: bytes,
) -> None:
    """Delete only this invocation's byte-identical, rolled-back artifact."""

    try:
        with hold_protected_file_for_read(temporary) as protected:
            persisted = protected.read_bytes()
    except FileNotFoundError:
        return
    except (OSError, PermissionError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 rollback was confirmed but the pending receipt cannot be "
            "verified; keep writers frozen"
        ) from exc
    if persisted != receipt_payload:
        raise C07ReceiptRepairRequiredError(
            "C07 rollback was confirmed but the pending receipt conflicts "
            "with this invocation; refusing to overwrite or delete it"
        )
    try:
        temporary.unlink()
    except OSError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 rollback was confirmed but its matching pending receipt "
            "could not be removed"
        ) from exc
