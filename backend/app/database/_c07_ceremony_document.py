"""Receipt document and isolated-asset facts for C07 orchestration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.database._c07_contract import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    MIGRATION_LEASE_LABEL,
    RECEIPT_SCHEMA,
    C07CeremonyError,
    HostFreezeEvidence,
)
from app.database._c07_storage import _backup_payload, _disk_budget_payload

_MIGRATION_LEASE_LABEL = MIGRATION_LEASE_LABEL
_RECEIPT_SCHEMA = RECEIPT_SCHEMA


def _host_payload(host: HostFreezeEvidence) -> dict[str, object]:
    return {
        "proof_sha256": host.evidence_sha256,
        "authority_digest": host.authority_digest,
        "mode": host.mode,
        "lifecycle_lock_held": True,
        "backend_service_state": "stopped",
        "runtime_process_count": 0,
        "listener_pid_count": 0,
        "coordinator_pid": host.coordinator_pid,
        "recorded_at_utc": host.recorded_at_utc.isoformat().replace(
            "+00:00",
            "Z",
        ),
        "expires_at_utc": host.expires_at_utc.isoformat().replace(
            "+00:00",
            "Z",
        ),
    }


def _assert_asset_recovery_contract(host: HostFreezeEvidence) -> None:
    if host.mode != "isolated_test":
        raise C07CeremonyError(
            "C07 is blocked before backup/DDL: ADR-0071 does not yet provide "
            "a host-authoritative PostgreSQL + asset/identity same-generation "
            "recovery manifest and isolated asset reconcile"
        )


def _isolated_test_asset_evidence(
    connection,
    *,
    source_identity: dict[str, str],
) -> dict[str, object]:
    referenced_paths = int(
        connection.scalar(
            text(
                "SELECT count(image_path) + count(thumbnail_path) "
                "FROM expenses"
            )
        )
        or 0
    )
    if referenced_paths != 0:
        raise C07CeremonyError(
            "isolated-test C07 asset fixture must have zero database references"
        )
    return {
        "result": "verified_empty_isolated_test_fixture",
        "production_authorized": False,
        "database_reference_count": 0,
        "logical_generation_digest": source_identity["logical_digest"],
    }


def _receipt_document(
    *,
    host_evidence: HostFreezeEvidence,
    evidence: Any,
    target_shape: dict[str, object],
    analyze_evidence: dict[str, object],
    live_elapsed_ms: int,
    ceremony_started: float,
) -> dict[str, object]:
    return {
        "schema": _RECEIPT_SCHEMA,
        "ceremony_id": host_evidence.operation_id,
        "release_identity": host_evidence.release_identity,
        "source_revision": C07_SOURCE_REVISION,
        "target_revision": C07_TARGET_REVISION,
        "database_identity": evidence.source_identity,
        "writer_freeze": _host_payload(host_evidence),
        "postgresql_barrier": {
            "advisory_lock_label": _MIGRATION_LEASE_LABEL,
            "advisory_lock_acquired": True,
            "public_table_lock_mode": "SHARE",
            "locked_table_count": len(evidence.tables),
            "other_client_session_count": 0,
            "lock_wait_ms": evidence.lock_wait_ms,
        },
        "capacity": _disk_budget_payload(evidence.disk_budget),
        "relations": evidence.relation_metrics,
        "backup": _backup_payload(evidence.backup),
        "isolated_recovery": evidence.isolated,
        "target_shape": target_shape,
        "statistics_refresh": analyze_evidence,
        "live_migration": {
            "transactional": True,
            "forward_only": True,
            "elapsed_ms": live_elapsed_ms,
            "result": "target_committed",
        },
        "assets": evidence.asset_evidence,
        "total_elapsed_ms": int(
            (time.perf_counter() - ceremony_started) * 1000
        ),
        "recorded_at_utc": datetime.now(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "result": "target_committed",
    }
