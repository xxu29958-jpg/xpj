"""Reusable isolated/Windows authority fixtures for C07 contract tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import app.database._c07_host_freeze_evidence as host_freeze_evidence
from app.database import _c07_ceremony as c07

_CEREMONY_ID = "66d65d05-c93a-4fde-b544-5578b6bfa18f"


def _role_capabilities() -> list[dict[str, object]]:
    return [
        {
            "name": "postgres",
            "oid": 10,
            "disposition": "database_authority",
            "can_login": True,
            "connection_limit": -1,
            "is_superuser": True,
            "can_create_db": True,
            "can_create_role": True,
            "can_replicate": True,
            "can_bypass_rls": True,
            "is_database_owner": False,
            "owns_public_schema": False,
            "owns_user_relations": False,
            "direct_connect": False,
            "effective_connect": True,
            "can_database_create": True,
            "can_public_schema_create": True,
            "can_table_write": True,
            "can_sequence_write": True,
            "can_assume_write_owner": True,
        },
        {
            "name": "ticketbox_runtime",
            "oid": 11,
            "disposition": "fenced_runtime",
            "can_login": False,
            "connection_limit": 0,
            "is_superuser": False,
            "can_create_db": False,
            "can_create_role": False,
            "can_replicate": False,
            "can_bypass_rls": False,
            "is_database_owner": False,
            "owns_public_schema": False,
            "owns_user_relations": False,
            "direct_connect": False,
            "effective_connect": False,
            "can_database_create": False,
            "can_public_schema_create": False,
            "can_table_write": True,
            "can_sequence_write": True,
            "can_assume_write_owner": False,
        },
    ]


def windows_freeze_envelope() -> tuple[str, str]:
    now = datetime.now(UTC)
    release_identity = "A" * 64
    payload = {
        "schema": host_freeze_evidence.WINDOWS_FREEZE_SCHEMA,
        "operation_id": _CEREMONY_ID,
        "descriptor_sha256": "B" * 64,
        "operation_kind": "c07_money_minor_bigint_v1",
        "target_alembic_revision": "20260729_0001",
        "revision_manifest_sha256": "F" * 64,
        "release_fingerprint": release_identity,
        "database_binding_sha256": "C" * 64,
        "recovery_epoch_id": "123e4567-e89b-42d3-a456-426614174001",
        "writer_fence_intent_sha256": "D" * 64,
        "coordinator_binding_sha256": "E" * 64,
        "coordinator_pid": 4242,
        "coordinator_started_filetime_high": 10,
        "coordinator_started_filetime_low": 20,
        "lifecycle_owner_pid": 4243,
        "lifecycle_owner_started_filetime_high": 30,
        "lifecycle_owner_started_filetime_low": 40,
        "heartbeat_sequence": 7,
        "backend_service_state": "stopped",
        "backend_service_start_policy": "disabled",
        "backend_service_pid": 0,
        "backend_listener_pid_count": 0,
        "runtime_process_count": 0,
        "database_client_session_count": 0,
        "database_client_sessions": [],
        "database_public_connect": False,
        "database_role_capability_count": 2,
        "database_role_capabilities": _role_capabilities(),
        "database_authority_role": "postgres",
        "database_authority_scope": (
            "process_local_secret_same_session_advisory_cut"
        ),
        "database_max_prepared_transactions": 0,
        "database_prepared_transaction_count": 0,
        "database_logical_subscription_count": 0,
        "database_logical_apply_worker_count": 0,
        "database_unexpected_worker_count": 0,
        "database_advisory_fence_available": True,
        "writers_frozen_at_utc": now.isoformat().replace("+00:00", "Z"),
    }
    payload_json = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    envelope = {
        "schema": host_freeze_evidence.HOST_ENVELOPE_SCHEMA,
        "artifact_kind": "freeze_proof",
        "payload_sha256": hashlib.sha256(
            payload_json.encode("utf-8")
        ).hexdigest().upper(),
        "payload_json": payload_json,
    }
    return release_identity, c07._canonical_json(envelope)  # noqa: SLF001
