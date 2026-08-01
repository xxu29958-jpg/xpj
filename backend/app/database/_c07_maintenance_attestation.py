"""Source and target financial-fact attestation for C07 maintenance."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.c07_money_facts import canonical_money_facts_sha256
from app.database._c07_contract import C07CeremonyError
from app.database._c07_execution_shape import _money_shape
from app.database._c07_maintenance_plan import (
    C07_TARGET_REVISION,
    C07MaintenanceUpgradeError,
)
from app.money_contract import MONEY_COLUMNS_V1


def _assert_isolated_source_shape(connection: Connection) -> None:
    inspector = inspect(connection)
    for contract in MONEY_COLUMNS_V1:
        actual = {
            item["name"]: item
            for item in inspector.get_columns(contract.table)
        }.get(contract.column)
        if actual is None:
            raise C07MaintenanceUpgradeError(
                f"isolated replay is missing "
                f"{contract.table}.{contract.column}"
            )
        if (
            str(actual["type"]).lower() not in {"integer", "int", "int4"}
            or bool(actual["nullable"]) is not contract.nullable
            or actual.get("default") != contract.server_default
        ):
            raise C07MaintenanceUpgradeError(
                f"isolated replay source shape differs at "
                f"{contract.table}.{contract.column}"
            )


def _money_facts(connection: Connection) -> str:
    return canonical_money_facts_sha256(
        connection,
        error=C07MaintenanceUpgradeError,
    )


def _target_shape_sha256(connection: Connection) -> str:
    try:
        shape = _money_shape(
            connection,
            target_revision=C07_TARGET_REVISION,
        )
    except C07CeremonyError as exc:
        raise C07MaintenanceUpgradeError(
            "maintenance target money shape is invalid"
        ) from exc
    return str(shape["shape_sha256"])
