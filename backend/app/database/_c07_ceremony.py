"""C07 BIGINT expansion orchestration and compatibility facade.
The detailed contracts, PostgreSQL evidence collection, Alembic execution,
and durable receipt state machine live in focused sibling modules.  This
module deliberately retains the original import surface for startup, CLI,
and tests while keeping the live transaction order visible in one place.
"""

from __future__ import annotations

import shutil as shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import _c07_ceremony_document as _ceremony_document
from app.database import _c07_commit_reconciliation as _commit_reconciliation
from app.database import _c07_contract as _contract
from app.database import _c07_execution as _execution
from app.database import _c07_receipt as _receipt
from app.database import _c07_storage as _storage
from app.database._c07_host_freeze_evidence import read_host_freeze_evidence as read_host_freeze_evidence
from app.database._c07_transaction_timeout import c07_prearmed_transaction
from app.errors import AppError
from app.services import backup_service

_assert_asset_recovery_contract = _ceremony_document._assert_asset_recovery_contract
_isolated_test_asset_evidence = _ceremony_document._isolated_test_asset_evidence
_receipt_document = _ceremony_document._receipt_document

_COMMIT_AMBIGUOUS = _commit_reconciliation._COMMIT_AMBIGUOUS
_COMMIT_CONFIRMED = _commit_reconciliation._COMMIT_CONFIRMED
_ROLLBACK_CONFIRMED = _commit_reconciliation._ROLLBACK_CONFIRMED
_classify_staged_receipt_commit = _commit_reconciliation._classify_staged_receipt_commit
_remove_confirmed_rollback_receipt = _commit_reconciliation._remove_confirmed_rollback_receipt

_alembic_config = _execution._alembic_config
_analyze_affected_tables = _execution._analyze_affected_tables
_isolated_restore_and_forward_drill = _execution._isolated_restore_and_forward_drill
_migration_module = _execution._migration_module
_money_shape = _execution._money_shape
_revision = _execution._revision
_revision_includes_c07 = _execution._revision_includes_c07
_run_alembic_upgrade = _execution._run_alembic_upgrade
c07_managed_upgrade_required = _execution.c07_managed_upgrade_required
set_c07_migration_context = _execution.set_c07_migration_context

_finalize_ready_marker = _receipt._finalize_ready_marker
_publish_receipt = _receipt._publish_receipt
_receipt_paths = _receipt._receipt_paths
_upsert_meta = _receipt._upsert_meta
_write_receipt_pending = _receipt._write_receipt_pending
assert_c07_lifecycle_ready = _receipt.assert_c07_lifecycle_ready
c07_receipt_directory = _receipt.c07_receipt_directory
repair_c07_receipt_publication = _receipt.repair_c07_receipt_publication

_acquire_writer_barrier = _storage._acquire_writer_barrier
_active_client_sessions = _storage._active_client_sessions
_backup_evidence = _storage._backup_evidence
_backup_payload = _storage._backup_payload
_disk_budget = _storage._disk_budget
_disk_budget_payload = _storage._disk_budget_payload
_identity_evidence = _storage._identity_evidence
_public_tables = _storage._public_tables
_relation_metrics = _storage._relation_metrics
_source_and_restore_urls_are_distinct = _storage._source_and_restore_urls_are_distinct
_table_counts = _storage._table_counts

C07_SOURCE_REVISION = _contract.C07_SOURCE_REVISION
C07_TARGET_REVISION = _contract.C07_TARGET_REVISION
C07_CEREMONY_ID_GUC = _contract.C07_CEREMONY_ID_GUC
C07_CEREMONY_MODE_GUC = _contract.C07_CEREMONY_MODE_GUC
C07_STATEMENT_TIMEOUT_GUC = _contract.C07_STATEMENT_TIMEOUT_GUC
C07_CEREMONY_MODE_FRESH = _contract.C07_CEREMONY_MODE_FRESH
C07_CEREMONY_MODE_MANAGED = _contract.C07_CEREMONY_MODE_MANAGED
C07_FRESH_CEREMONY_ID = _contract.C07_FRESH_CEREMONY_ID
C07_CEREMONY_ID_KEY = _contract.C07_CEREMONY_ID_KEY
C07_RECEIPT_SHA256_KEY = _contract.C07_RECEIPT_SHA256_KEY
C07_LIFECYCLE_STATE_KEY = _contract.C07_LIFECYCLE_STATE_KEY
C07_LIFECYCLE_FRESH = _contract.C07_LIFECYCLE_FRESH
C07_LIFECYCLE_PENDING = _contract.C07_LIFECYCLE_PENDING
C07_LIFECYCLE_READY = _contract.C07_LIFECYCLE_READY

C07CeremonyError = _contract.C07CeremonyError
C07ReceiptRepairRequiredError = _contract.C07ReceiptRepairRequiredError
HostFreezeEvidence = _contract.HostFreezeEvidence
DiskBudget = _contract.DiskBudget
BackupEvidence = _contract.BackupEvidence

_RECEIPT_SCHEMA = _contract.RECEIPT_SCHEMA
_RECEIPT_DIR = _contract.RECEIPT_DIR
_RELEASE_IDENTITY = _contract.RELEASE_IDENTITY_PATTERN
_SHA256 = _contract.SHA256_PATTERN
_MAX_FREEZE_WINDOW = _contract.MAX_FREEZE_WINDOW
_PG_RESTORE_TIMEOUT_SECONDS = _contract.PG_RESTORE_TIMEOUT_SECONDS
_MAINTENANCE_WINDOW_SECONDS = _contract.MAINTENANCE_WINDOW_SECONDS
_SPACE_HEADROOM_FACTOR = _contract.SPACE_HEADROOM_FACTOR
_MIGRATION_LEASE_LABEL = _contract.MIGRATION_LEASE_LABEL
_ANALYZE_TABLES = _contract.ANALYZE_TABLES
_InjectedRollbackError = _contract.InjectedRollbackError
_canonical_json = _contract.canonical_json
_sha256_bytes = _contract.sha256_bytes
_sha256_file = _contract.sha256_file
_canonical_uuid = _contract.canonical_uuid
_parse_utc = _contract.parse_utc
_assert_host_freeze_still_valid = _contract.assert_host_freeze_still_valid
_remaining_timeout_seconds = _contract.remaining_timeout_seconds


@dataclass(frozen=True)
class _CeremonyEvidence:
    source_identity: dict[str, str]
    asset_evidence: dict[str, object]
    tables: tuple[str, ...]
    relation_metrics: list[dict[str, int | str]]
    disk_budget: DiskBudget
    lock_wait_ms: int
    backup: BackupEvidence
    isolated: dict[str, object]


@dataclass
class _StagedReceiptState:
    receipt_sha256: str | None = None
    receipt_payload: bytes | None = None

    def record(self, receipt_sha256: str, receipt_payload: bytes) -> None:
        if (
            self.receipt_sha256 is not None
            or self.receipt_payload is not None
        ):
            raise C07CeremonyError(
                "C07 receipt staging identity was recorded more than once"
            )
        self.receipt_sha256 = receipt_sha256
        self.receipt_payload = receipt_payload

    def value(self) -> tuple[str, bytes] | None:
        if self.receipt_sha256 is None and self.receipt_payload is None:
            return None
        if self.receipt_sha256 is None or self.receipt_payload is None:
            raise C07ReceiptRepairRequiredError(
                "C07 receipt staging identity is incomplete; keep writers "
                "frozen"
            )
        return self.receipt_sha256, self.receipt_payload


def _collect_ceremony_evidence(
    connection,
    *,
    source_url: str,
    restore_engine: Engine,
    restore_url: str,
    host_evidence: HostFreezeEvidence,
    postgres_data_directory: Path,
    deadline: float,
) -> _CeremonyEvidence:
    tables, lock_wait_ms = _acquire_writer_barrier(
        connection,
        deadline=deadline,
    )
    if _revision(connection) != C07_SOURCE_REVISION:
        raise C07CeremonyError(
            "C07 source revision mismatch; no migration was attempted"
        )
    source_identity = _identity_evidence(connection)
    asset_evidence = _isolated_test_asset_evidence(
        connection,
        source_identity=source_identity,
    )
    relation_metrics = _relation_metrics(connection)
    disk_budget = _disk_budget(
        connection,
        backup_service._backup_dir(),  # noqa: SLF001
        postgres_data_directory=postgres_data_directory,
    )
    source_counts = _table_counts(connection, tables)
    exported_snapshot = str(
        connection.scalar(text("SELECT pg_export_snapshot()"))
    )
    backup, dump_path = _backup_evidence(
        source_url=source_url,
        exported_snapshot=exported_snapshot,
        deadline=deadline,
    )
    if _active_client_sessions(connection):
        raise C07CeremonyError(
            "another client session appeared after the C07 snapshot"
        )
    isolated = _isolated_restore_and_forward_drill(
        restore_engine=restore_engine,
        restore_url=restore_url,
        dump_path=dump_path,
        source_identity=source_identity,
        source_counts=source_counts,
        ceremony_id=host_evidence.operation_id,
        deadline=deadline,
    )
    _assert_host_freeze_still_valid(host_evidence)
    if _active_client_sessions(connection):
        raise C07CeremonyError(
            "another client session appeared during the C07 recovery drill"
        )
    return _CeremonyEvidence(
        source_identity=source_identity,
        asset_evidence=asset_evidence,
        tables=tables,
        relation_metrics=relation_metrics,
        disk_budget=disk_budget,
        lock_wait_ms=lock_wait_ms,
        backup=backup,
        isolated=isolated,
    )


def _migrate_and_stage_receipt(
    connection,
    *,
    host_evidence: HostFreezeEvidence,
    evidence: _CeremonyEvidence,
    temporary: Path,
    deadline: float,
    ceremony_started: float,
    staged_receipt: _StagedReceiptState,
) -> tuple[str, bytes]:
    live_started = time.perf_counter()
    _run_alembic_upgrade(
        connection,
        ceremony_id=host_evidence.operation_id,
        deadline=deadline,
    )
    if _revision(connection) != C07_TARGET_REVISION:
        raise C07CeremonyError("live C07 migration did not reach target")
    target_shape = _money_shape(
        connection,
        target_revision=C07_TARGET_REVISION,
    )
    _assert_host_freeze_still_valid(host_evidence)
    analyze_evidence = _analyze_affected_tables(connection)
    _upsert_meta(
        connection,
        C07_CEREMONY_ID_KEY,
        host_evidence.operation_id,
    )
    _upsert_meta(
        connection,
        C07_LIFECYCLE_STATE_KEY,
        C07_LIFECYCLE_PENDING,
    )
    receipt = _receipt_document(
        host_evidence=host_evidence,
        evidence=evidence,
        target_shape=target_shape,
        analyze_evidence=analyze_evidence,
        live_elapsed_ms=int(
            (time.perf_counter() - live_started) * 1000
        ),
        ceremony_started=ceremony_started,
    )
    receipt_sha256, receipt_payload = _write_receipt_pending(
        temporary=temporary,
        receipt=receipt,
        record_identity=staged_receipt.record,
    )
    _upsert_meta(
        connection,
        C07_RECEIPT_SHA256_KEY,
        receipt_sha256,
    )
    _assert_host_freeze_still_valid(host_evidence)
    return receipt_sha256, receipt_payload


def _acquire_c07_backup_lease():
    try:
        return backup_service.acquire_backup_job_lock()
    except (AppError, OSError) as exc:
        raise C07CeremonyError(
            "C07 backup lock is unavailable; no backup or migration was "
            "attempted"
        ) from exc


def _publish_ready_receipt(
    source_engine: Engine,
    *,
    host_evidence: HostFreezeEvidence,
    temporary: Path,
    final: Path,
    receipt_sha256: str,
    receipt_payload: bytes,
) -> None:
    try:
        _assert_host_freeze_still_valid(host_evidence)
    except C07CeremonyError as exc:
        raise C07ReceiptRepairRequiredError(
            "C07 schema committed after host authority expired; keep "
            "writers frozen and repair the receipt"
        ) from exc
    _publish_receipt(temporary, final, receipt_payload)
    _finalize_ready_marker(
        source_engine,
        ceremony_id=host_evidence.operation_id,
        receipt_sha256=receipt_sha256,
        receipt_payload=receipt_payload,
    )
    assert_c07_lifecycle_ready(
        source_engine,
        receipt_dir=final.parent,
    )


def _reconcile_staged_receipt_after_transaction_error(
    source_engine: Engine,
    *,
    ceremony_id: str,
    temporary: Path,
    receipt_sha256: str,
    receipt_payload: bytes,
) -> None:
    outcome = _classify_staged_receipt_commit(
        source_engine,
        ceremony_id=ceremony_id,
        receipt_sha256=receipt_sha256,
        receipt_payload=receipt_payload,
    )
    if outcome == _ROLLBACK_CONFIRMED:
        _remove_confirmed_rollback_receipt(
            temporary=temporary,
            receipt_payload=receipt_payload,
        )
        return
    if outcome == _COMMIT_CONFIRMED:
        raise C07ReceiptRepairRequiredError(
            "C07 COMMIT succeeded but its response was lost; the durable "
            "pending receipt was preserved. Keep writers frozen and run "
            "publication repair"
        )
    raise C07ReceiptRepairRequiredError(
        "C07 COMMIT outcome cannot be proven through a fresh connection; "
        "the durable pending receipt was preserved. Keep writers frozen and "
        "resolve or run publication repair only after database verification"
    )


def _ceremony_deadline(host_evidence: HostFreezeEvidence) -> float:
    remaining = max(
        0.0,
        (host_evidence.expires_at_utc - datetime.now(UTC)).total_seconds(),
    )
    return time.monotonic() + min(float(_MAINTENANCE_WINDOW_SECONDS), remaining)


def _run_c07_live_transaction(
    *,
    source_engine: Engine,
    source_url: str,
    restore_engine: Engine,
    restore_url: str,
    host_evidence: HostFreezeEvidence,
    postgres_data_directory: Path,
    temporary: Path,
    deadline: float,
    ceremony_started: float,
    staged_receipt: _StagedReceiptState,
) -> tuple[str, bytes]:
    timeout_ms = int(
        _remaining_timeout_seconds(
            deadline,
            cap_seconds=_MAINTENANCE_WINDOW_SECONDS,
            phase="C07 live ceremony",
        )
        * 1000
    )
    with source_engine.connect().execution_options(
        isolation_level="READ COMMITTED"
    ) as connection, c07_prearmed_transaction(
        connection,
        timeout_ms=timeout_ms,
    ):
        evidence = _collect_ceremony_evidence(
            connection,
            source_url=source_url,
            restore_engine=restore_engine,
            restore_url=restore_url,
            host_evidence=host_evidence,
            postgres_data_directory=postgres_data_directory,
            deadline=deadline,
        )
        return _migrate_and_stage_receipt(
            connection,
            host_evidence=host_evidence,
            evidence=evidence,
            temporary=temporary,
            deadline=deadline,
            ceremony_started=ceremony_started,
            staged_receipt=staged_receipt,
        )


def _reconcile_live_transaction_error(
    source_engine: Engine,
    *,
    host_evidence: HostFreezeEvidence,
    temporary: Path,
    staged_receipt: _StagedReceiptState,
    cause: Exception,
) -> None:
    staged_value = staged_receipt.value()
    if staged_value is None:
        return
    receipt_sha256, receipt_payload = staged_value
    try:
        _reconcile_staged_receipt_after_transaction_error(
            source_engine,
            ceremony_id=host_evidence.operation_id,
            temporary=temporary,
            receipt_sha256=receipt_sha256,
            receipt_payload=receipt_payload,
        )
    except C07ReceiptRepairRequiredError as repair_error:
        raise repair_error from cause


def run_c07_bigint_ceremony(
    *,
    source_engine: Engine,
    source_url: str,
    restore_engine: Engine,
    restore_url: str,
    host_evidence: HostFreezeEvidence,
    postgres_data_directory: Path,
    receipt_dir: Path | None = None,
) -> Path:
    """Run the isolated-test C07 evidence path and publish its receipt."""

    if host_evidence.release_identity == "":
        raise C07CeremonyError("release identity is required")
    _assert_host_freeze_still_valid(host_evidence)
    _assert_asset_recovery_contract(host_evidence)
    _source_and_restore_urls_are_distinct(source_url, restore_url)
    directory = c07_receipt_directory(receipt_dir)
    ceremony_started = time.perf_counter()
    deadline = _ceremony_deadline(host_evidence)
    temporary, final = _receipt_paths(
        host_evidence.operation_id,
        directory=directory,
    )
    staged_receipt = _StagedReceiptState()
    backup_lease = _acquire_c07_backup_lease()
    try:
        try:
            receipt_sha256, receipt_payload = _run_c07_live_transaction(
                source_engine=source_engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host_evidence,
                postgres_data_directory=postgres_data_directory,
                temporary=temporary,
                deadline=deadline,
                ceremony_started=ceremony_started,
                staged_receipt=staged_receipt,
            )
        except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
            _reconcile_live_transaction_error(
                source_engine,
                host_evidence=host_evidence,
                temporary=temporary,
                staged_receipt=staged_receipt,
                cause=exc,
            )
            raise
        _publish_ready_receipt(
            source_engine,
            host_evidence=host_evidence,
            temporary=temporary,
            final=final,
            receipt_sha256=receipt_sha256,
            receipt_payload=receipt_payload,
        )
        return final
    finally:
        backup_lease.release()
