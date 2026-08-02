"""Installed-host startup authority for the exact ADR-0073 C07 release."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database._c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    C07CeremonyError,
    C07ReceiptRepairRequiredError,
)
from app.database._c07_execution_shape import _money_shape
from app.database._c07_production_connection import (
    _database_binding_sha256,
)
from app.database._c07_runtime_projection import (
    RuntimeProjection as RuntimeProjection,
)
from app.database._c07_runtime_projection import (
    _canonical_uuid as _canonical_uuid,
)
from app.database._c07_runtime_projection import (
    _required_sha256 as _required_sha256,
)
from app.database._c07_runtime_projection import (
    c07_runtime_projection_path as c07_runtime_projection_path,
)
from app.database._c07_runtime_projection import (
    read_c07_runtime_projection as read_c07_runtime_projection,
)

_PRODUCTION_MARKER_SCHEMA = "ticketbox-c07-production-authority-v2"
_HOST_ENVELOPE_SCHEMA = "ticketbox-c07-host-envelope-v2"
_PROJECTION_SCHEMA = "ticketbox-c07-runtime-projection-v6"
_PROJECTION_FILE_NAME = "c07-lifecycle-projection.json"
_PROJECTION_DIRECTORY_NAME = "c07-runtime-projection"
_TICKETBOX_MACHINE_DIRECTORY_NAME = "Ticketbox"
_CSIDL_COMMON_PROGRAM_FILES = 0x002B
_OPERATION_KIND = "c07_money_minor_bigint_v1"
_MONEY_FACTS_SEAL_KEY = "c07_cutover_money_facts_sha256"
_SHA256_LOWER = re.compile(r"[0-9a-f]{64}\Z")
_SHA256_UPPER = re.compile(r"[0-9A-F]{64}\Z")
_CLUSTER_IDENTIFIER = re.compile(r"[0-9]{10,32}\Z")
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{7}Z\Z"
)
_ZERO_SHA256 = "0" * 64
_OUTER_FIELDS = frozenset(
    {"schema", "artifact_kind", "payload_sha256", "payload_json"}
)
_PROJECTION_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "installation_id",
        "stage",
        "terminal",
        "ready",
        "database_binding_sha256",
        "logical_server_id",
        "data_generation",
        "recovery_epoch_id",
        "operation_kind",
        "source_alembic_revision",
        "alembic_target",
        "recovery_manifest_sha256",
        "migration_evidence_sha256",
        "role_authority_sha256",
        "runtime_acl_sha256",
        "live_postconditions_sha256",
        "money_facts_sha256",
        "money_shape_sha256",
        "heartbeat_sequence_at_publish",
        "updated_at_utc",
    }
)


@dataclass(frozen=True)
class ProductionDatabaseMarker:
    operation_id: str
    mode: str
    cluster_system_identifier: str
    database_oid: int
    source_revision: str
    target_revision: str
    database_binding_sha256: str
    money_facts_sha256: str
    money_shape_sha256: str
    recovery_manifest_sha256: str
    migration_evidence_sha256: str
    role_authority_sha256: str
    runtime_acl_sha256: str
    live_postconditions_sha256: str


def _parse_production_marker(
    value: str,
) -> ProductionDatabaseMarker:
    parts = value.split("|")
    if len(parts) != 16 or parts[0] != _PRODUCTION_MARKER_SCHEMA:
        raise C07ReceiptRepairRequiredError(
            "C07 production database marker fields are invalid"
        )
    if (
        parts[2] not in {"fresh_install", "legacy_adoption"}
        or parts[3] != "production_ready"
        or _CLUSTER_IDENTIFIER.fullmatch(parts[4]) is None
        or parts[6] != C07_SOURCE_REVISION
        or parts[7] != C07_TARGET_REVISION
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 production database marker is not exact-target READY"
        )
    try:
        database_oid = int(parts[5])
    except ValueError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 production database OID is invalid"
        ) from exc
    if not 1 <= database_oid <= 0xFFFFFFFF:
        raise C07ReceiptRepairRequiredError(
            "C07 production database OID is invalid"
        )
    _required_sha256(
        parts[8],
        label="production marker database binding",
        uppercase=True,
    )
    for index, label in (
        (9, "money facts"),
        (10, "money shape"),
        (11, "recovery manifest"),
        (12, "migration evidence"),
        (13, "role authority"),
        (14, "runtime ACL"),
        (15, "live postconditions"),
    ):
        _required_sha256(
            parts[index],
            label=f"production marker {label}",
            uppercase=False,
        )
    return ProductionDatabaseMarker(
        operation_id=_canonical_uuid(
            parts[1],
            label="production marker operation_id",
        ),
        mode=parts[2],
        cluster_system_identifier=parts[4],
        database_oid=database_oid,
        source_revision=parts[6],
        target_revision=parts[7],
        database_binding_sha256=parts[8],
        money_facts_sha256=parts[9],
        money_shape_sha256=parts[10],
        recovery_manifest_sha256=parts[11],
        migration_evidence_sha256=parts[12],
        role_authority_sha256=parts[13],
        runtime_acl_sha256=parts[14],
        live_postconditions_sha256=parts[15],
    )


def read_c07_production_database_marker(
    connection,
) -> ProductionDatabaseMarker | None:
    try:
        row = connection.execute(
            text(
                "SELECT database.oid::text, "
                "pg_catalog.shobj_description(database.oid, 'pg_database'), "
                "control.system_identifier::text "
                "FROM pg_catalog.pg_database AS database "
                "CROSS JOIN pg_catalog.pg_control_system() AS control "
                "WHERE database.datname = current_database()"
            )
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 cannot read the current database authority marker"
        ) from exc
    if row is None:
        raise C07ReceiptRepairRequiredError(
            "C07 current database catalog identity is unavailable"
        )
    live_database_oid, value, live_cluster_identifier = row
    if not isinstance(value, str) or not value.startswith(
        f"{_PRODUCTION_MARKER_SCHEMA}|"
    ):
        return None
    marker = _parse_production_marker(value)
    if (
        str(marker.database_oid) != str(live_database_oid)
        or marker.cluster_system_identifier
        != str(live_cluster_identifier)
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 production marker physical database identity is stale"
        )
    return marker


def _read_live_logical_database_identity(
    connection,
) -> tuple[str, str]:
    try:
        row = connection.execute(
            text(
                "SELECT "
                "(SELECT value FROM public.app_meta WHERE key = 'server_id'), "
                "(SELECT value FROM public.app_meta "
                " WHERE key = 'data_generation')"
            )
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 cannot read the live logical database identity"
        ) from exc
    if row is None:
        raise C07ReceiptRepairRequiredError(
            "C07 live logical database identity is unavailable"
        )
    return (
        _canonical_uuid(row[0], label="live logical server_id"),
        _canonical_uuid(row[1], label="live data_generation"),
    )


def _read_live_alembic_revision(
    connection,
    *,
    expected_revision: str = C07_TARGET_REVISION,
) -> str:
    try:
        revisions = tuple(
            str(value)
            for value in connection.scalars(
                text(
                    "SELECT version_num FROM public.alembic_version "
                    "ORDER BY version_num"
                )
            )
        )
    except SQLAlchemyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 cannot read the live Alembic authority"
        ) from exc
    if revisions != (expected_revision,):
        raise C07ReceiptRepairRequiredError(
            "C07 live database does not match the expected managed revision"
        )
    return revisions[0]


def _read_money_facts_seal(connection) -> str:
    value = connection.scalar(
        text("SELECT value FROM app_meta WHERE key = :key"),
        {"key": _MONEY_FACTS_SEAL_KEY},
    )
    return _required_sha256(
        value,
        label="database money-facts seal",
        uppercase=False,
    )


def assert_c07_production_ready(
    connection,
    *,
    projection_path: Path | None = None,
    expected_revision: str = C07_TARGET_REVISION,
) -> bool:
    marker = read_c07_production_database_marker(connection)
    if marker is None:
        return False
    projection = read_c07_runtime_projection(projection_path)
    live_server_id, live_data_generation = (
        _read_live_logical_database_identity(connection)
    )
    _read_live_alembic_revision(
        connection,
        expected_revision=expected_revision,
    )
    expected_binding = _database_binding_sha256(
        installation_id=projection.installation_id,
        cluster_system_identifier=marker.cluster_system_identifier,
        database_oid=str(marker.database_oid),
        logical_server_id=live_server_id,
        logical_data_generation=live_data_generation,
    )
    try:
        live_shape = _money_shape(
            connection,
            target_revision=C07_TARGET_REVISION,
        )
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 live money-contract shape is invalid"
        ) from exc
    live_shape_sha256 = str(live_shape["shape_sha256"])
    cutover_money_facts_seal = _read_money_facts_seal(connection)
    if (
        marker.operation_id != projection.operation_id
        or marker.source_revision != projection.source_revision
        or marker.target_revision != projection.target_revision
        or projection.database_binding_sha256 != expected_binding
        or marker.database_binding_sha256 != expected_binding
        or projection.logical_server_id != live_server_id
        or projection.data_generation != live_data_generation
        or projection.money_facts_sha256.lower()
        != cutover_money_facts_seal
        or marker.money_facts_sha256 != cutover_money_facts_seal
        or projection.money_shape_sha256.lower()
        != live_shape_sha256
        or marker.money_shape_sha256 != live_shape_sha256
        or projection.recovery_manifest_sha256.lower()
        != marker.recovery_manifest_sha256
        or projection.migration_evidence_sha256.lower()
        != marker.migration_evidence_sha256
        or projection.role_authority_sha256.lower()
        != marker.role_authority_sha256
        or projection.runtime_acl_sha256.lower()
        != marker.runtime_acl_sha256
        or projection.live_postconditions_sha256.lower()
        != marker.live_postconditions_sha256
    ):
        raise C07ReceiptRepairRequiredError(
            "C07 marker, SYSTEM READY projection, live identity, "
            "money-contract shape, and money facts do not share one authority"
        )
    return True
