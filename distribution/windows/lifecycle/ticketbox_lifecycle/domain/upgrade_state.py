"""Phase, step, binding, and commit-state helpers for managed upgrades."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

from ticketbox_lifecycle.adapters.ports import PlatformAdapter
from ticketbox_lifecycle.domain.install import hash_request_payload
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import (
    UPGRADE_SEQUENCE,
    ActiveOperation,
    DurablePhase,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
    UpgradeStepName,
)

_PHASE_RANK = {
    "prepared": 0,
    "data_ready": 1,
    "release_activated": 2,
    "committed": 3,
}

_CommitState = Literal["committed", "not_committed", "unknown"]


@dataclass
class _UpgradeState:
    active: UpgradeOperation
    new_binding_published: bool
    published_binding: InstallationBinding | None = None
    commit_publish_attempted: bool = False
    target_materialized: bool = False
    services_stopped: bool = False


def _known_sibling_releases(
    stores: LifecycleStores,
    binding: InstallationBinding | None,
    *,
    target_release_id: str,
) -> frozenset[str]:
    if binding is None:
        return frozenset()
    releases: set[str] = set()
    for rid in (binding.active_release_id, binding.previous_release_id):
        if rid:
            releases.add(rid)
    for record in stores.operations_read.list_committed():
        if not isinstance(record, ActiveOperation):
            continue
        if record.install_id != binding.install_id or record.dataset_id != binding.dataset_id:
            continue
        if record.target_release_id:
            releases.add(record.target_release_id)
        if isinstance(record, UpgradeOperation) and record.previous_release_id:
            releases.add(record.previous_release_id)
    excluded = target_release_id.casefold()
    return frozenset(rid for rid in releases if rid.casefold() != excluded)


def _durable_commit_state(
    stores: LifecycleStores,
    request: InstallRequest,
    active: UpgradeOperation,
    *,
    new_binding_published: bool,
    commit_publish_attempted: bool,
) -> tuple[bool | None, _CommitState, DurablePhase | None]:
    published: bool | None = True if new_binding_published else False
    if not new_binding_published:
        try:
            current_binding = stores.binding_read.read()
        except (LifecycleError, OSError):
            published = None
            current_binding = None
        if current_binding is not None:
            published = _binding_matches_upgrade_target(current_binding, active)

    read_error = False
    try:
        persisted_history = stores.operations_read.read_committed(request.operation_id)
    except (LifecycleError, OSError):
        persisted_history = None
        read_error = True
    if persisted_history is not None:
        return published, "committed", "committed"

    try:
        persisted_active = stores.operations_read.read_active()
    except (LifecycleError, OSError):
        persisted_active = None
        read_error = True
    if persisted_active is not None and persisted_active.operation_id == active.operation_id:
        if persisted_active.phase == "committed":
            return published, "committed", "committed"
        if commit_publish_attempted or read_error:
            return published, "unknown", persisted_active.phase
        return published, "not_committed", persisted_active.phase
    if commit_publish_attempted or read_error:
        return published, "unknown", None
    return published, "not_committed", None


def _error_code_and_message(exc: LifecycleError | OSError) -> tuple[str, str]:
    if isinstance(exc, LifecycleError):
        return exc.code, exc.message
    return "operation_io_failed", "lifecycle operation I/O failed"


def _append_failure_detail(message: str, label: str, failure: LifecycleError | OSError) -> str:
    f_code, f_msg = _error_code_and_message(failure)
    return f"{message}; {label} ({f_code}): {f_msg}"


def _canonical_phase_for_step(completed: str | None) -> DurablePhase:
    if completed == "health":
        return "release_activated"
    if completed == "scm":
        return "data_ready"
    return "prepared"


def _monotonic_phase(current: DurablePhase, requested: DurablePhase, next_step: UpgradeStepName) -> DurablePhase:
    floor = _canonical_phase_for_step(next_step)
    candidates: list[DurablePhase] = [requested, floor]
    if current in _PHASE_RANK:
        candidates.append(current)
    return max(candidates, key=lambda name: _PHASE_RANK[name])


def _bind_upgrade_request(
    request: InstallRequest,
    active: UpgradeOperation,
) -> InstallRequest:
    return replace(
        request,
        install_id=active.install_id,
        dataset_id=active.dataset_id,
        schema_revision=active.schema_revision or request.schema_revision,
        health_attestation_key=active.health_attestation_key,
    )


def _binding_matches_upgrade_target(
    binding: InstallationBinding,
    active: UpgradeOperation,
) -> bool:
    return (
        binding.install_id == active.install_id
        and binding.dataset_id == active.dataset_id
        and binding.expected_restore_epoch == active.expected_restore_epoch
        and binding.active_release_id == active.target_release_id
        and binding.previous_release_id == active.previous_release_id
        and binding.release_manifest_sha256 == active.release_manifest_sha256
        and binding.health_attestation_key == active.health_attestation_key
    )


def _advance(
    stores: LifecycleStores,
    active: UpgradeOperation,
    *,
    phase: DurablePhase,
    step: UpgradeStepName,
    no_return_point: bool | None = None,
) -> UpgradeOperation:
    next_step = _furthest_step(active.completed_step, step)
    next_phase = _monotonic_phase(active.phase, phase, next_step)
    candidate = replace(
        active,
        phase=next_phase,
        completed_step=next_step,
        no_return_point=active.no_return_point if no_return_point is None else no_return_point,
    )
    if candidate == active:
        return active
    stores.operations_write.publish_active(candidate)
    return candidate


def _furthest_step(
    current: str | None,
    observed: UpgradeStepName,
) -> UpgradeStepName:
    if current not in UPGRADE_SEQUENCE:
        return observed
    if UPGRADE_SEQUENCE.index(observed) > UPGRADE_SEQUENCE.index(current):
        return observed
    return cast(UpgradeStepName, current)


def _ensure_postcondition(
    adapter: PlatformAdapter,
    request: InstallRequest,
    step: str,
) -> None:
    try:
        adapter.verify(request, step)
        return
    except LifecycleError as exc:
        if exc.code in {"command_outcome_unknown", "command_start_failed"}:
            raise
    adapter.apply(request, step)
    adapter.verify(request, step)


def hash_upgrade_identity(
    request: InstallRequest,
    *,
    install_id: str,
    dataset_id: str,
    expected_restore_epoch: int,
    previous_release_id: str,
    previous_release_manifest_sha256: str,
    source_schema_revision: str,
) -> str:
    return hash_request_payload(
        {
            "kind": "upgrade",
            "install_id": install_id,
            "dataset_id": dataset_id,
            "expected_restore_epoch": expected_restore_epoch,
            "previous_release_id": previous_release_id,
            "previous_release_manifest_sha256": previous_release_manifest_sha256,
            "source_schema_revision": source_schema_revision,
            "target_release_id": request.target_release_id,
            "target_schema_revision": request.schema_revision,
            "release_manifest_sha256": request.release_manifest_sha256,
            "app_dir": request.app_dir,
            "data_root": request.data_root,
            "program_data_root": request.program_data_root,
            "pg_service_name": request.pg_service_name,
            "backend_service_name": request.backend_service_name,
            "pg_port": request.pg_port,
            "backend_port": request.backend_port,
            "postgres_major": request.postgres_major,
        }
    )
