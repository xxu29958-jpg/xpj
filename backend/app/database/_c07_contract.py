"""Shared fail-closed contracts for the ADR-0073 C07 ceremony."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.config import DATA_ROOT
from app.database._managed_postgres_contract import (
    MIGRATION_LEASE_LABEL as MIGRATION_LEASE_LABEL,
)
from app.money_contract import MONEY_COLUMNS_V1
from app.services.secure_file import windows_process_start_filetime

C07_SOURCE_REVISION = "20260722_0001"
C07_TARGET_REVISION = "20260729_0001"
C07_CEREMONY_ID_GUC = "ticketbox.c07_ceremony_id"
C07_CEREMONY_MODE_GUC = "ticketbox.c07_ceremony_mode"
C07_STATEMENT_TIMEOUT_GUC = "ticketbox.c07_statement_timeout_ms"
C07_CEREMONY_MODE_FRESH = "fresh_install"
C07_CEREMONY_MODE_MANAGED = "managed"
C07_FRESH_CEREMONY_ID = "fresh-install"

C07_CEREMONY_ID_KEY = "money_c07_ceremony_id"
C07_RECEIPT_SHA256_KEY = "money_c07_receipt_sha256"
C07_LIFECYCLE_STATE_KEY = "money_c07_lifecycle_state"
C07_LIFECYCLE_FRESH = "fresh_install"
C07_LIFECYCLE_PENDING = "target_committed_receipt_pending"
C07_LIFECYCLE_READY = "ready"

RECEIPT_SCHEMA = "ticketbox-c07-bigint-ceremony-receipt-v1"
RECEIPT_DIR = DATA_ROOT / "migration-receipts"
RELEASE_IDENTITY_PATTERN = re.compile(
    r"(?:[0-9a-f]{40}|[0-9A-F]{64})\Z"
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_FREEZE_WINDOW = timedelta(minutes=30)
PG_RESTORE_TIMEOUT_SECONDS = 20 * 60
MAINTENANCE_WINDOW_SECONDS = 20 * 60
SPACE_HEADROOM_FACTOR = 1.2
ANALYZE_TABLES = tuple(sorted({column.table for column in MONEY_COLUMNS_V1}))


class C07CeremonyError(RuntimeError):
    """The C07 ceremony cannot safely start or finish."""


class C07ReceiptRepairRequiredError(C07CeremonyError):
    """Schema committed but receipt publication/finalization is incomplete."""


class InjectedRollbackError(RuntimeError):
    """Expected isolated-drill failure used to prove transactional rollback."""


@dataclass(frozen=True)
class HostFreezeEvidence:
    operation_id: str
    release_identity: str
    mode: str
    authority_digest: str
    coordinator_pid: int
    recorded_at_utc: datetime
    expires_at_utc: datetime
    evidence_sha256: str
    database_binding_sha256: str = ""
    writer_fence_intent_sha256: str = ""
    coordinator_binding_sha256: str = ""
    coordinator_started_filetime_high: int = 0
    coordinator_started_filetime_low: int = 0
    lifecycle_owner_pid: int = 0
    lifecycle_owner_started_filetime_high: int = 0
    lifecycle_owner_started_filetime_low: int = 0
    heartbeat_sequence: int = 0


@dataclass(frozen=True)
class DiskBudget:
    database_size_bytes: int
    estimated_dump_bytes: int
    declared_scratch_bytes: int
    same_volume: bool
    backup_free_bytes: int
    backup_required_bytes: int
    data_free_bytes: int
    data_required_bytes: int
    backup_volume_digest: str
    data_volume_digest: str


@dataclass(frozen=True)
class BackupEvidence:
    file_name: str
    sha256: str
    size_bytes: int
    toc_sha256: str
    toc_entry_count: int
    elapsed_ms: int


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_uuid(value: object, *, label: str) -> str:
    try:
        parsed = UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise C07CeremonyError(f"{label} must be a canonical UUID") from exc
    canonical = str(parsed)
    if parsed.int == 0 or value != canonical:
        raise C07CeremonyError(f"{label} must be a canonical non-zero UUID")
    return canonical


def parse_utc(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise C07CeremonyError(f"{label} must use canonical UTC Z time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise C07CeremonyError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo != UTC:
        raise C07CeremonyError(f"{label} must be UTC")
    return parsed


def assert_host_freeze_still_valid(host: HostFreezeEvidence) -> None:
    if host.expires_at_utc <= datetime.now(UTC):
        raise C07CeremonyError(
            "writer-freeze authority expired before the C07 commit boundary"
        )
    if (
        host.mode == "windows_lifecycle_lock"
        and (
            os.getppid() != host.coordinator_pid
            or windows_process_start_filetime(host.coordinator_pid)
            != (
                host.coordinator_started_filetime_high,
                host.coordinator_started_filetime_low,
            )
            or windows_process_start_filetime(host.lifecycle_owner_pid)
            != (
                host.lifecycle_owner_started_filetime_high,
                host.lifecycle_owner_started_filetime_low,
            )
        )
    ):
        raise C07CeremonyError(
            "writer-freeze coordinator or lifecycle owner identity changed"
        )


def remaining_timeout_seconds(
    deadline: float,
    *,
    cap_seconds: int,
    phase: str,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise C07CeremonyError(
            f"C07 maintenance window expired before {phase}"
        )
    return max(1.0, min(float(cap_seconds), remaining))
