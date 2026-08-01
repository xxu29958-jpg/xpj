"""Shared parsing plus isolated/process evidence helpers for C07."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.database._c07_contract import (
    MAX_FREEZE_WINDOW,
    RELEASE_IDENTITY_PATTERN,
    SHA256_PATTERN,
    C07CeremonyError,
    HostFreezeEvidence,
    canonical_json,
    canonical_uuid,
    parse_utc,
    sha256_bytes,
)
from app.services.secure_file import hold_protected_file_for_read

ISOLATED_FREEZE_SCHEMA = "ticketbox-c07-isolated-freeze-v1"
ISOLATED_FREEZE_FIELDS = frozenset(
    {
        "schema",
        "operation_id",
        "release_identity",
        "mode",
        "authority_digest",
        "lifecycle_lock_held",
        "backend_service_state",
        "runtime_process_count",
        "listener_pid_count",
        "coordinator_pid",
        "recorded_at_utc",
        "expires_at_utc",
    }
)
HOST_SHA256_PATTERN = re.compile(r"[0-9A-F]{64}\Z")


def _parse_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    import json

    try:
        parsed = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise C07CeremonyError(f"{label} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise C07CeremonyError(f"{label} must be a JSON object")
    return parsed


def _read_isolated_freeze_payload(
    path: Path,
) -> tuple[dict[str, object], bytes]:
    try:
        with hold_protected_file_for_read(path) as protected:
            raw = protected.read_bytes()
    except (OSError, PermissionError, ValueError) as exc:
        raise C07CeremonyError(
            "isolated writer-freeze proof is not a protected file"
        ) from exc
    payload = _parse_json_object(raw, label="isolated writer-freeze proof")
    if (
        set(payload) != ISOLATED_FREEZE_FIELDS
        or payload.get("schema") != ISOLATED_FREEZE_SCHEMA
        or payload.get("mode") != "isolated_test"
        or canonical_json(payload).encode("utf-8") != raw
    ):
        raise C07CeremonyError(
            "isolated writer-freeze proof schema or canonical encoding is invalid"
        )
    return payload, raw


def _required_int(
    payload: dict[str, object],
    field: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    value = payload.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise C07CeremonyError(f"writer-freeze {field} is invalid")
    return value


def _required_host_sha(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or HOST_SHA256_PATTERN.fullmatch(value) is None
    ):
        raise C07CeremonyError(f"writer-freeze {field} is invalid")
    return value


def _read_isolated_host_evidence(
    path: Path,
    *,
    expected_release_identity: str,
    expected_parent_pid: int | None,
) -> HostFreezeEvidence:
    payload, raw = _read_isolated_freeze_payload(path)
    release_identity = payload.get("release_identity")
    authority_digest = payload.get("authority_digest")
    coordinator_pid = _required_int(payload, "coordinator_pid", minimum=1)
    if (
        release_identity != expected_release_identity
        or not isinstance(release_identity, str)
        or RELEASE_IDENTITY_PATTERN.fullmatch(release_identity) is None
    ):
        raise C07CeremonyError(
            "writer-freeze proof release identity mismatch"
        )
    if (
        not isinstance(authority_digest, str)
        or SHA256_PATTERN.fullmatch(authority_digest) is None
    ):
        raise C07CeremonyError(
            "writer-freeze authority digest is invalid"
        )
    if expected_parent_pid is not None and coordinator_pid != expected_parent_pid:
        raise C07CeremonyError("writer-freeze coordinator process mismatch")
    if (
        payload.get("lifecycle_lock_held") is not True
        or payload.get("backend_service_state") != "stopped"
        or payload.get("runtime_process_count") != 0
        or payload.get("listener_pid_count") != 0
    ):
        raise C07CeremonyError(
            "writer-freeze proof does not show a stopped writer"
        )
    recorded_at = parse_utc(
        payload.get("recorded_at_utc"),
        label="recorded_at_utc",
    )
    expires_at = parse_utc(
        payload.get("expires_at_utc"),
        label="expires_at_utc",
    )
    now = datetime.now(UTC)
    if (
        recorded_at > now + timedelta(seconds=5)
        or expires_at <= now
        or expires_at - recorded_at > MAX_FREEZE_WINDOW
    ):
        raise C07CeremonyError(
            "writer-freeze proof is stale or has an excessive lifetime"
        )
    return HostFreezeEvidence(
        operation_id=canonical_uuid(
            payload.get("operation_id"),
            label="operation_id",
        ),
        release_identity=release_identity,
        mode="isolated_test",
        authority_digest=authority_digest,
        coordinator_pid=coordinator_pid,
        recorded_at_utc=recorded_at,
        expires_at_utc=expires_at,
        evidence_sha256=sha256_bytes(raw),
    )


def _read_windows_process_identity(
    payload: dict[str, object],
    *,
    expected_parent_pid: int,
    process_start_reader: Callable[[int], tuple[int, int]],
) -> tuple[int, int, int, int, int, int]:
    coordinator_pid = _required_int(payload, "coordinator_pid", minimum=1)
    coordinator_high = _required_int(
        payload,
        "coordinator_started_filetime_high",
        maximum=0xFFFFFFFF,
    )
    coordinator_low = _required_int(
        payload,
        "coordinator_started_filetime_low",
        maximum=0xFFFFFFFF,
    )
    owner_pid = _required_int(payload, "lifecycle_owner_pid", minimum=1)
    owner_high = _required_int(
        payload,
        "lifecycle_owner_started_filetime_high",
        maximum=0xFFFFFFFF,
    )
    owner_low = _required_int(
        payload,
        "lifecycle_owner_started_filetime_low",
        maximum=0xFFFFFFFF,
    )
    if (
        coordinator_pid != expected_parent_pid
        or process_start_reader(coordinator_pid)
        != (coordinator_high, coordinator_low)
        or process_start_reader(owner_pid) != (owner_high, owner_low)
    ):
        raise C07CeremonyError(
            "writer-freeze coordinator or lifecycle owner identity mismatch"
        )
    return (
        coordinator_pid,
        coordinator_high,
        coordinator_low,
        owner_pid,
        owner_high,
        owner_low,
    )
