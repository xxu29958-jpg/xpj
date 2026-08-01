"""Canonical receipt parsing and live-database binding validation."""

from __future__ import annotations

import json
import re

from app.database._c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    RECEIPT_SCHEMA,
    C07CeremonyError,
    C07ReceiptRepairRequiredError,
    canonical_json,
    canonical_uuid,
    sha256_bytes,
)
from app.database._c07_execution import _money_shape
from app.database._c07_storage import _identity_evidence
from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_CONTRACT_PHASE_C07,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def parse_canonical_receipt(payload: bytes) -> dict[str, object]:
    try:
        raw = payload.decode("utf-8")
        parsed = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt is not canonical JSON"
        ) from exc
    if (
        not isinstance(parsed, dict)
        or canonical_json(parsed).encode("utf-8") != payload
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt is not canonical JSON"
        )
    return parsed


def _target_shape_parts(
    receipt: dict[str, object],
) -> tuple[dict, list, list, list]:
    shape = receipt.get("target_shape")
    if not isinstance(shape, dict):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt target shape is invalid"
        )
    columns = shape.get("columns")
    checks = shape.get("checks")
    absent_checks = shape.get("absent_checks")
    if (
        not isinstance(columns, list)
        or not isinstance(checks, list)
        or not isinstance(absent_checks, list)
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt target shape manifest is invalid"
        )
    return shape, columns, checks, absent_checks


def _validate_frozen_base_shape(receipt: dict[str, object]) -> None:
    shape, columns, checks, absent_checks = _target_shape_parts(receipt)
    expected_columns = {
        (
            contract.table,
            contract.column,
            contract.nullable,
            contract.server_default,
        )
        for contract in MONEY_COLUMNS_V1
    }
    actual_columns = {
        (
            item.get("table"),
            item.get("column"),
            item.get("nullable"),
            item.get("server_default"),
        )
        for item in columns
        if isinstance(item, dict)
        and item.get("type") == "int8"
        and item.get("identity") == ""
        and item.get("generated") == ""
        and item.get("type_kind") == "base"
    }
    expected_checks = {
        (contract.table, check.name)
        for contract in MONEY_COLUMNS_V1
        for check in contract.checks
    }
    actual_checks = {
        (item.get("table"), item.get("name"))
        for item in checks
        if isinstance(item, dict)
        and item.get("validated") is True
        and item.get("no_inherit") is False
        and isinstance(item.get("expression_sha256"), str)
        and _SHA256.fullmatch(str(item["expression_sha256"])) is not None
    }
    expected_absent_checks = {
        (check.table, check.name) for check in MONEY_REMOVED_LEGACY_CHECKS_V1
    }
    actual_absent_checks = {
        (item.get("table"), item.get("name"))
        for item in absent_checks
        if isinstance(item, dict) and item.get("absent") is True
    }
    payload = {
        "columns": columns,
        "checks": checks,
        "absent_checks": absent_checks,
        "phase": shape.get("phase"),
    }
    if (
        len(columns) != len(expected_columns)
        or len(checks) != len(expected_checks)
        or actual_columns != expected_columns
        or actual_checks != expected_checks
        or len(absent_checks) != len(expected_absent_checks)
        or actual_absent_checks != expected_absent_checks
        or shape.get("column_count") != len(expected_columns)
        or shape.get("check_count") != len(expected_checks)
        or shape.get("absent_check_count") != len(expected_absent_checks)
        or shape.get("phase") != MONEY_CONTRACT_PHASE_C07
        or shape.get("shape_sha256")
        != sha256_bytes(canonical_json(payload).encode("utf-8"))
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt frozen base shape is invalid"
        )


def validate_base_receipt_artifact(
    connection,
    *,
    payload: bytes,
    ceremony_id: str,
    receipt_sha256: str,
) -> None:
    if sha256_bytes(payload) != receipt_sha256:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt digest mismatch"
        )
    receipt = parse_canonical_receipt(payload)
    try:
        receipt_ceremony_id = canonical_uuid(
            receipt.get("ceremony_id"),
            label="receipt ceremony_id",
        )
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt ceremony identity is invalid"
        ) from exc
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt_ceremony_id != ceremony_id
        or receipt.get("source_revision") != C07_SOURCE_REVISION
        or receipt.get("target_revision") != C07_TARGET_REVISION
        or receipt.get("result") != "target_committed"
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt is not bound to the exact C07 target"
        )
    if receipt.get("database_identity") != _identity_evidence(connection):
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt database identity does not match the live database"
        )
    _validate_frozen_base_shape(receipt)


def validate_receipt_against_live_database(
    connection,
    *,
    payload: bytes,
    ceremony_id: str,
    receipt_sha256: str,
) -> None:
    validate_base_receipt_artifact(
        connection,
        payload=payload,
        ceremony_id=ceremony_id,
        receipt_sha256=receipt_sha256,
    )
    receipt = parse_canonical_receipt(payload)
    try:
        live_shape = _money_shape(
            connection,
            target_revision=C07_TARGET_REVISION,
        )
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 live money shape is invalid"
        ) from exc
    if receipt.get("target_shape") != live_shape:
        raise C07ReceiptRepairRequiredError(
            "C07 durable receipt target shape does not match the live database"
        )
