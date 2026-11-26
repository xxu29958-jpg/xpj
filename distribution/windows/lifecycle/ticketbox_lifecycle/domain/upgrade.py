"""Managed existing-dataset upgrade coordinator with pre-DDL cold backup and attestation."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, replace
from typing import Literal

from ticketbox_lifecycle.adapters.ports import PlatformAdapter
from ticketbox_lifecycle.adapters.upgrade import UpgradePlatform
from ticketbox_lifecycle.domain.binding import require_binding_match, upgrade_binding
from ticketbox_lifecycle.domain.install import hash_request_payload
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.domain.planner import plan_managed_upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    UPGRADE_SEQUENCE,
    ActiveOperation,
    CommandResult,
    DurablePhase,
    InstallationBinding,
    InstallRequest,
    RestoreOperation,
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


def upgrade(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UpgradePlatform,
    *,
    rollback_on_failure: bool = False,
) -> CommandResult:
    stores.mutex.acquire()
    try:
        return _upgrade_locked(
            stores,
            request,
            platform,
            rollback_on_failure=rollback_on_failure,
        )
    finally:
        stores.mutex.release()


def rollback_upgrade(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UpgradePlatform,
) -> CommandResult:
    """Explicitly recover previous release when an active upgrade failed before business writes opened."""
    stores.mutex.acquire()
    try:
        return _rollback_upgrade_standalone_locked(stores, request, platform)
    finally:
        stores.mutex.release()


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


def _upgrade_locked(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UpgradePlatform,
    *,
    rollback_on_failure: bool = False,
) -> CommandResult:
    binding = stores.binding_read.read()
    existing = stores.operations_read.read_active()
    committed = (
        stores.operations_read.read_committed(request.operation_id)
        if existing is None
        else None
    )
    allowed_siblings = _known_sibling_releases(
        stores,
        binding,
        target_release_id=request.target_release_id,
    )
    binding_at_target = (
        committed is not None
        or (binding is not None and binding.active_release_id == request.target_release_id)
    )
    if binding_at_target:
        request = stores.shipment.bind_and_verify(
            request,
            allowed_sibling_releases=allowed_siblings,
        )
    else:
        request = platform.verify_staged_release(
            request,
            require_target_absent=existing is None,
        )
    if committed is not None:
        return _replay_committed_upgrade(stores, request, binding, committed, platform)

    observation = stores.observer.observe(request)
    plan_managed_upgrade(request, observation, binding, existing)
    assert binding is not None

    if existing is not None:
        assert isinstance(existing, UpgradeOperation)
        previous_release_id = existing.previous_release_id
        previous_release_manifest_sha256 = existing.previous_release_manifest_sha256
        source_schema_revision = existing.source_schema_revision
        request_hash = hash_upgrade_identity(
            request,
            install_id=binding.install_id,
            dataset_id=binding.dataset_id,
            expected_restore_epoch=binding.expected_restore_epoch,
            previous_release_id=previous_release_id,
            previous_release_manifest_sha256=previous_release_manifest_sha256,
            source_schema_revision=source_schema_revision,
        )
        if existing.request_hash != request_hash:
            raise LifecycleViolation(
                "request_mismatch",
                "upgrade resume requires the same immutable request hash",
            )
        if existing.phase == "committed":
            return _replay_committed_upgrade(stores, request, binding, existing, platform)
        active = existing
    else:
        previous_release_id = binding.active_release_id
        previous_release_manifest_sha256 = binding.release_manifest_sha256
        source_schema_revision = platform.read_source_schema_revision(request, binding)
        platform.check_backup_disk_space(request, binding)
        request_hash = hash_upgrade_identity(
            request,
            install_id=binding.install_id,
            dataset_id=binding.dataset_id,
            expected_restore_epoch=binding.expected_restore_epoch,
            previous_release_id=previous_release_id,
            previous_release_manifest_sha256=previous_release_manifest_sha256,
            source_schema_revision=source_schema_revision,
        )
        stores.operations_write.prepare(request)
        active = UpgradeOperation(
            schema=OPERATION_SCHEMA,
            operation_id=request.operation_id,
            kind="upgrade",
            request_hash=request_hash,
            target_release_id=request.target_release_id,
            data_root=binding.data_root,
            release_manifest_sha256=request.release_manifest_sha256,
            backend_port=binding.backend_port,
            phase="prepared",
            no_return_point=False,
            completed_step=None,
            install_id=binding.install_id,
            dataset_id=binding.dataset_id,
            schema_revision=request.schema_revision,
            health_attestation_key=secrets.token_hex(32),
            expected_restore_epoch=binding.expected_restore_epoch,
            previous_release_id=previous_release_id,
            previous_release_manifest_sha256=previous_release_manifest_sha256,
            source_schema_revision=source_schema_revision,
            backup_path="",
            backup_sha256="",
            business_writes_opened=False,
        )
        stores.operations_write.publish_active(active)

    bound = _bind_upgrade_request(request, active)
    is_published = _binding_matches_upgrade_target(binding, active)
    state = _UpgradeState(
        active=active,
        new_binding_published=is_published,
        published_binding=binding if is_published else None,
    )
    stores.operations_write.prepare(bound)
    if state.active.phase == "failed_recoverable":
        resume_phase = _canonical_phase_for_step(state.active.completed_step)
        state.active = replace(state.active, phase=resume_phase)  # type: ignore[arg-type]
        stores.operations_write.publish_active(state.active)

    try:
        _execute_upgrade_steps(
            stores,
            bound,
            binding,
            state,
            platform,
            allowed_siblings=allowed_siblings,
        )
    except Exception as exc:
        primary = (
            exc
            if isinstance(exc, (LifecycleError, OSError))
            else LifecycleError("upgrade_incomplete", "managed upgrade failed; keep backup and fenced candidate")
        )
        return _failed_upgrade_result(
            stores,
            request,
            state.active,
            bound,
            platform,
            new_binding_published=state.new_binding_published,
            commit_publish_attempted=state.commit_publish_attempted,
            target_materialized=state.target_materialized,
            services_stopped=state.services_stopped,
            primary=primary,
            rollback_on_failure=rollback_on_failure,
        )
    return _finish_committed_upgrade(stores, bound, state.active, platform)


def _execute_upgrade_steps(
    stores: LifecycleStores,
    bound: InstallRequest,
    binding: InstallationBinding,
    state: _UpgradeState,
    platform: UpgradePlatform,
    *,
    allowed_siblings: frozenset[str],
) -> None:
    has_backup = bool(state.active.backup_path and state.active.backup_sha256)
    if not has_backup:
        if state.active.no_return_point:
            raise LifecycleViolation(
                "upgrade_backup_missing",
                "cannot continue past no-return point without verified pre-upgrade backup",
            )
        platform.check_backup_disk_space(bound, binding)
        state.services_stopped = True
        platform.stop_services_for_backup(bound, binding)
        state.active = _advance(stores, state.active, phase="prepared", step="stop_services")
        backup = platform.create_verified_cold_backup(
            bound,
            binding,
            allowed_operation_id=state.active.operation_id,
        )
        if backup.schema_revision != state.active.source_schema_revision:
            raise LifecycleViolation(
                "upgrade_source_revision_drifted",
                "cold backup schema revision disagrees with upgrade source revision",
            )
        state.active = replace(
            state.active,
            phase=_monotonic_phase(state.active.phase, "prepared", _furthest_step(state.active.completed_step, "cold_backup")),  # type: ignore[arg-type]
            completed_step=_furthest_step(state.active.completed_step, "cold_backup"),
            backup_path=backup.path,
            backup_sha256=backup.sha256,
        )
        stores.operations_write.publish_active(state.active)
    else:
        state.services_stopped = True
        platform.fence_backend_for_upgrade(
            bound,
            expected_previous_release_id=state.active.previous_release_id,
        )
        platform.verify_existing_cold_backup(
            bound,
            state.active.backup_path,
            state.active.backup_sha256,
            binding,
            source_release_id=state.active.previous_release_id,
            source_schema_revision=state.active.source_schema_revision,
        )

    platform.verify_pg_service_for_upgrade(bound)
    stores.adapters.security.verify(bound, "acl")
    _ensure_postcondition(stores.adapters.postgres, bound, "start_postgres")
    stores.adapters.postgres.verify(bound, "roles_database")
    state.active = _advance(stores, state.active, phase="prepared", step="start_postgres")

    if not state.new_binding_published:
        state.target_materialized = True
        platform.materialize_target_release(bound, allowed_sibling_releases=allowed_siblings)

    if not state.active.no_return_point:
        state.active = replace(state.active, no_return_point=True)
        stores.operations_write.publish_active(state.active)
    migration = platform.run_offline_migration(
        bound,
        source_revision=state.active.source_schema_revision,
        target_revision=state.active.schema_revision,
        expected_restore_epoch=state.active.expected_restore_epoch,
        backup_path=state.active.backup_path,
        backup_sha256=state.active.backup_sha256,
    )
    if (
        migration.operation_id != state.active.operation_id
        or migration.source_revision != state.active.source_schema_revision
        or migration.target_revision != state.active.schema_revision
        or migration.outcome not in {"target_committed", "target_observed_after_interruption"}
    ):
        raise LifecycleViolation(
            "upgrade_migration_mismatch",
            "offline migration result does not match this upgrade operation",
        )
    stores.adapters.alembic.verify(bound, "alembic")
    state.active = _advance(stores, state.active, phase="prepared", step="alembic", no_return_point=True)

    if not state.new_binding_published:
        platform.rebind_backend_service(
            bound,
            expected_previous_release_id=state.active.previous_release_id,
        )
        if state.active.completed_step != "health":
            state.active = _advance(stores, state.active, phase="data_ready", step="scm", no_return_point=True)
            stores.adapters.scm.apply(bound, "start_services")
            stores.adapters.scm.verify(bound, "start_services")
            platform.verify_candidate_health(bound)
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=state.active.previous_release_id,
            )
            state.active = _advance(stores, state.active, phase="release_activated", step="health", no_return_point=True)
        else:
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=state.active.previous_release_id,
            )
            state.active = _advance(stores, state.active, phase="release_activated", step="health", no_return_point=True)
        platform.sync_shared_payload(bound, allowed_sibling_releases=allowed_siblings)
        published = upgrade_binding(binding, bound, previous_release_id=state.active.previous_release_id)
        stores.binding_write.publish(published)
        state.new_binding_published = True
        state.published_binding = published

    assert state.published_binding is not None
    platform.rebind_removed_connector_state(bound, state.published_binding)
    platform.update_start_menu_shortcut(bound)

    state.active = replace(
        state.active,
        phase="committed",
        completed_step="health",
        no_return_point=True,
        business_writes_opened=True,
    )
    state.commit_publish_attempted = True
    stores.operations_write.publish_active(state.active)


def _verify_live_normal_after_autostart(
    stores: LifecycleStores,
    bound: InstallRequest,
    platform: UpgradePlatform,
) -> None:
    stores.adapters.scm.enable_autostart(bound)
    stores.adapters.scm.verify(bound, "start_services")
    platform.verify_normal_health(bound)
    stores.adapters.scm.verify(bound, "start_services")


def _finish_committed_upgrade(
    stores: LifecycleStores,
    bound: InstallRequest,
    active: UpgradeOperation,
    platform: UpgradePlatform,
) -> CommandResult:
    try:
        if not active.business_writes_opened:
            active = replace(
                active,
                phase="committed",
                completed_step="health",
                no_return_point=True,
                business_writes_opened=True,
            )
            if stores.operations_read.read_active() is not None:
                stores.operations_write.publish_active(active)
        active_present = stores.operations_read.read_active() is not None
        ready = False
        if not active_present:
            try:
                stores.adapters.scm.verify(bound, "start_services")
                _verify_live_normal_after_autostart(stores, bound, platform)
                ready = True
            except LifecycleError:
                ready = False
        if not ready:
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=active.previous_release_id,
            )
            stores.adapters.scm.apply(bound, "start_services")
            stores.adapters.scm.verify(bound, "start_services")
            platform.verify_normal_health(bound)
            _verify_live_normal_after_autostart(stores, bound, platform)
        if stores.operations_read.read_active() is not None:
            stores.operations_write.archive_committed(active)
    except (LifecycleError, OSError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "upgrade_commit_finalize_failed"
        message = exc.message if isinstance(exc, LifecycleError) else "post-commit upgrade finalization failed"
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=bound.command,
            operation_id=bound.operation_id,
            phase="committed",
            code=code,
            message=message,
            installation_published=True,
        )
    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command=bound.command,
        operation_id=bound.operation_id,
        phase="committed",
        code="upgraded",
        message="Managed upgrade committed; existing installation identity and data preserved.",
        installation_published=True,
    )


def _replay_committed_upgrade(
    stores: LifecycleStores,
    request: InstallRequest,
    binding: InstallationBinding | None,
    operation: object,
    platform: UpgradePlatform,
) -> CommandResult:
    if not isinstance(operation, UpgradeOperation) or operation.kind != "upgrade":
        raise LifecycleViolation("operation_conflict", "committed operation is not an upgrade")
    if (
        operation.operation_id != request.operation_id
        or operation.target_release_id != request.target_release_id
        or operation.release_manifest_sha256 != request.release_manifest_sha256
    ):
        raise LifecycleViolation("release_mismatch", "committed upgrade does not match this request")
    if binding is None:
        raise LifecycleViolation("missing_binding", "committed upgrade has no installation.json")
    bound = _bind_upgrade_request(request, operation)
    expected = upgrade_binding(binding, bound, previous_release_id=operation.previous_release_id)
    require_binding_match(binding, expected)
    return _finish_committed_upgrade(stores, bound, operation, platform)


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


def _failed_upgrade_result(
    stores: LifecycleStores,
    request: InstallRequest,
    active: UpgradeOperation,
    bound: InstallRequest,
    platform: UpgradePlatform,
    *,
    new_binding_published: bool,
    commit_publish_attempted: bool,
    target_materialized: bool,
    services_stopped: bool = True,
    primary: LifecycleError | OSError,
    rollback_on_failure: bool = False,
) -> CommandResult:
    code = primary.code if isinstance(primary, LifecycleError) else "operation_io_failed"
    message = primary.message if isinstance(primary, LifecycleError) else "lifecycle operation I/O failed"
    should_fence = (
        services_stopped
        or active.no_return_point
        or bool(active.backup_path)
        or target_materialized
        or new_binding_published
        or commit_publish_attempted
    )
    if should_fence:
        try:
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=active.previous_release_id,
            )
        except (LifecycleError, OSError) as failure:
            f_code = failure.code if isinstance(failure, LifecycleError) else "operation_io_failed"
            f_msg = failure.message if isinstance(failure, LifecycleError) else "lifecycle operation I/O failed"
            message = f"{message}; backend fence failed ({f_code}): {f_msg}"

    published, commit_state, observed_phase = _durable_commit_state(
        stores,
        request,
        active,
        new_binding_published=new_binding_published,
        commit_publish_attempted=commit_publish_attempted,
    )
    if commit_state != "not_committed" or active.business_writes_opened or published is not False:
        if commit_state == "committed":
            phase: DurablePhase = "committed"
        elif observed_phase is not None:
            phase = observed_phase
        else:
            phase = "committed" if commit_publish_attempted else active.phase
        if rollback_on_failure:
            return CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command=request.command,
                operation_id=request.operation_id,
                phase=phase,
                code="upgrade_rollback_refused_writes_may_have_opened",
                message=f"{message}; rollback refused because normal business writes may have opened",
                installation_published=published,
            )
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase=phase,
            code=code,
            message=message,
            installation_published=published,
        )

    if rollback_on_failure and bool(active.backup_path and active.backup_sha256):
        return _execute_rollback_to_previous_locked(
            stores,
            request,
            bound,
            platform,
            primary_code=code,
            primary_message=message,
            new_binding_published=new_binding_published,
            commit_publish_attempted=commit_publish_attempted,
        )

    if not active.no_return_point and (target_materialized or bool(active.backup_path and active.backup_sha256)):
        try:
            platform.cleanup_uncommitted_target_release(bound)
        except (LifecycleError, OSError) as failure:
            f_code = failure.code if isinstance(failure, LifecycleError) else "operation_io_failed"
            f_msg = failure.message if isinstance(failure, LifecycleError) else "lifecycle operation I/O failed"
            message = f"{message}; target cleanup failed ({f_code}): {f_msg}"

    failed = replace(active, phase="failed_recoverable")
    try:
        stores.operations_write.publish_active(failed)
    except (LifecycleError, OSError) as failure:
        f_code = failure.code if isinstance(failure, LifecycleError) else "operation_io_failed"
        f_msg = failure.message if isinstance(failure, LifecycleError) else "lifecycle operation I/O failed"
        message = f"{message}; failed-state publication failed ({f_code}): {f_msg}"
    else:
        active = failed

    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=False,
        command=request.command,
        operation_id=request.operation_id,
        phase=active.phase,
        code="upgrade_failed_fenced" if rollback_on_failure else code,
        message=message,
        installation_published=published,
    )


def _require_rollback_eligible(
    stores: LifecycleStores,
    request: InstallRequest,
    *,
    new_binding_published: bool = False,
    commit_publish_attempted: bool = False,
) -> tuple[UpgradeOperation, InstallationBinding]:
    try:
        binding = stores.binding_read.read()
        persisted_active = stores.operations_read.read_active()
        persisted_history = (
            stores.operations_read.read_committed(request.operation_id)
            if request.operation_id
            else None
        )
    except (LifecycleError, OSError, ValueError) as exc:
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "cannot prove normal business writes never opened because durable state is unreadable",
        ) from exc

    if persisted_history is not None or new_binding_published or commit_publish_attempted:
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "refusing rollback because upgrade commit or normal business writes may have opened",
        )
    if persisted_active is None:
        if binding is not None and binding.previous_release_id is not None:
            raise LifecycleViolation(
                "upgrade_rollback_refused_writes_may_have_opened",
                "installation already reflects a committed release transition; refusing rollback",
            )
        raise LifecycleViolation(
            "upgrade_rollback_no_active_upgrade",
            "no active pre-write upgrade operation exists to roll back",
        )
    if not isinstance(persisted_active, UpgradeOperation) or persisted_active.kind != "upgrade":
        raise LifecycleViolation(
            "operation_conflict",
            "active operation is not a managed upgrade",
        )
    if persisted_active.operation_id != request.operation_id:
        raise LifecycleViolation(
            "operation_conflict",
            "rollback request operation_id does not match the active upgrade operation",
        )
    if persisted_active.business_writes_opened or persisted_active.phase == "committed":
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "refusing rollback because normal business writes opened for the target release",
        )
    if binding is None:
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "installation binding is missing; cannot verify pre-write lineage",
        )
    if (
        binding.install_id != persisted_active.install_id
        or binding.dataset_id != persisted_active.dataset_id
        or binding.expected_restore_epoch != persisted_active.expected_restore_epoch
        or binding.active_release_id != persisted_active.previous_release_id
        or binding.release_manifest_sha256 != persisted_active.previous_release_manifest_sha256
    ):
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "installation binding no longer proves pre-write previous-release lineage",
        )
    if (
        persisted_active.target_release_id != request.target_release_id
        or persisted_active.release_manifest_sha256 != request.release_manifest_sha256
    ):
        raise LifecycleViolation(
            "request_mismatch",
            "rollback request target release or manifest does not match the active upgrade",
        )
    effective_schema = request.schema_revision or persisted_active.schema_revision
    expected_request_hash = hash_upgrade_identity(
        replace(request, schema_revision=effective_schema),
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        expected_restore_epoch=binding.expected_restore_epoch,
        previous_release_id=persisted_active.previous_release_id,
        previous_release_manifest_sha256=persisted_active.previous_release_manifest_sha256,
        source_schema_revision=persisted_active.source_schema_revision,
    )
    if persisted_active.request_hash != expected_request_hash or (
        request.request_hash
        and request.request_hash != "pending"
        and request.request_hash != persisted_active.request_hash
    ):
        raise LifecycleViolation(
            "request_mismatch",
            "rollback request hash does not match the active upgrade operation",
        )
    if not persisted_active.backup_path or not persisted_active.backup_sha256:
        raise LifecycleViolation(
            "upgrade_backup_missing",
            "pre-upgrade cold backup evidence is missing; keeping fenced state",
        )
    return persisted_active, binding


def _rollback_upgrade_standalone_locked(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UpgradePlatform,
) -> CommandResult:
    try:
        active, _binding = _require_rollback_eligible(stores, request)
    except LifecycleError as exc:
        phase: DurablePhase = (
            "committed"
            if exc.code == "upgrade_rollback_refused_writes_may_have_opened"
            else "failed_recoverable"
        )
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase=phase,
            code=exc.code,
            message=exc.message,
            installation_published=None if phase == "committed" else False,
        )
    bound = _bind_upgrade_request(request, active)
    return _execute_rollback_to_previous_locked(
        stores,
        request,
        bound,
        platform,
        primary_code="explicit_rollback_requested",
        primary_message="explicit pre-write rollback requested for fenced upgrade candidate",
        new_binding_published=False,
        commit_publish_attempted=False,
    )


def _execute_rollback_to_previous_locked(
    stores: LifecycleStores,
    request: InstallRequest,
    bound: InstallRequest,
    platform: UpgradePlatform,
    *,
    primary_code: str,
    primary_message: str,
    new_binding_published: bool,
    commit_publish_attempted: bool,
) -> CommandResult:
    try:
        active, binding = _require_rollback_eligible(
            stores,
            request,
            new_binding_published=new_binding_published,
            commit_publish_attempted=commit_publish_attempted,
        )
    except LifecycleError as exc:
        if exc.code == "upgrade_rollback_refused_writes_may_have_opened":
            return CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command=request.command,
                operation_id=request.operation_id,
                phase="committed",
                code=exc.code,
                message=exc.message,
                installation_published=None,
            )
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="failed_recoverable",
            code="upgrade_failed_fenced",
            message=f"{primary_message}; rollback unavailable ({exc.code}): {exc.message}",
            installation_published=False,
        )

    rollback_active: RestoreOperation | None = None
    published_restored = False
    try:
        platform.verify_existing_cold_backup(
            bound,
            active.backup_path,
            active.backup_sha256,
            binding,
            source_release_id=active.previous_release_id,
            source_schema_revision=active.source_schema_revision,
        )
        platform.fence_backend_for_upgrade(
            bound,
            expected_previous_release_id=active.previous_release_id,
        )
        quarantine_path = platform.quarantine_failed_upgrade(
            bound,
            active,
            binding,
            primary_code=primary_code,
            primary_message=primary_message,
        )
        new_install_id = str(uuid.uuid4())
        new_health_key = secrets.token_hex(32)
        target_epoch = binding.expected_restore_epoch + 1
        rollback_op_id = f"restore-{active.previous_release_manifest_sha256}"
        restored = platform.restore_previous_from_backup(
            bound,
            active,
            binding,
            new_install_id=new_install_id,
            rollback_operation_id=rollback_op_id,
            new_health_key=new_health_key,
            target_restore_epoch=target_epoch,
        )
        prev_bound = restored.previous_request
        rollback_active = RestoreOperation(
            schema=OPERATION_SCHEMA,
            operation_id=rollback_op_id,
            kind="restore",
            request_hash=hashlib.sha256(
                (restored.backup_digest + "\0" + active.previous_release_manifest_sha256).encode()
            ).hexdigest(),
            target_release_id=active.previous_release_id,
            data_root=binding.data_root,
            release_manifest_sha256=active.previous_release_manifest_sha256,
            backend_port=binding.backend_port,
            phase="data_ready",
            no_return_point=True,
            completed_step="owner_claim",
            install_id=new_install_id,
            dataset_id=binding.dataset_id,
            schema_revision=active.source_schema_revision,
            health_attestation_key=new_health_key,
            expected_restore_epoch=target_epoch,
        )
        stores.operations_write.publish_active(rollback_active)
        stores.adapters.scm.apply(prev_bound, "start_services")
        stores.adapters.scm.verify(prev_bound, "start_services")
        platform.verify_previous_candidate_health(prev_bound, expected_restore_epoch=target_epoch)
        stores.adapters.scm.fence_backend(prev_bound)
        rollback_active = replace(rollback_active, phase="release_activated", completed_step="health")
        stores.operations_write.publish_active(rollback_active)
        stores.binding_write.publish(restored.restored_binding)
        published_restored = True
        platform.update_start_menu_shortcut(prev_bound)
        rollback_active = replace(rollback_active, phase="committed", completed_step="health")
        stores.operations_write.publish_active(rollback_active)
        stores.adapters.scm.apply(prev_bound, "start_services")
        stores.adapters.scm.verify(prev_bound, "start_services")
        platform.verify_previous_normal_health(prev_bound, expected_restore_epoch=target_epoch)
        stores.adapters.scm.enable_autostart(prev_bound)
        stores.operations_write.archive_committed(rollback_active)
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="rolled_back_to_previous",
            code="upgrade_failed_restored_previous",
            message=(
                f"Upgrade failed ({primary_code}) before normal business writes opened; "
                f"safely restored previous release {active.previous_release_id} from pre-upgrade backup "
                f"and reopened services."
            ),
            installation_published=True,
            pairing_code=restored.pairing.pairing_code,
            pairing_expires_at=restored.pairing.pairing_expires_at,
            client_generation=new_install_id,
            restore_epoch=target_epoch,
            revoked_credentials_summary=restored.pairing.revoked_credentials_summary,
            restored_release_id=active.previous_release_id,
            quarantine_path=quarantine_path,
            details={
                "primary_failure_code": primary_code,
                "backup_path": active.backup_path,
                "backup_sha256": active.backup_sha256,
                "previous_release_id": active.previous_release_id,
            },
        )
    except Exception as exc:
        rb_code = exc.code if isinstance(exc, LifecycleError) else "rollback_io_failed"
        rb_msg = exc.message if isinstance(exc, LifecycleError) else "previous-release recovery failed"
        try:
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=active.previous_release_id,
            )
        except (LifecycleError, OSError):
            pass
        failed_record = (
            replace(rollback_active, phase="failed_recoverable")
            if rollback_active is not None
            else replace(active, phase="failed_recoverable")
        )
        try:
            stores.operations_write.publish_active(failed_record)
        except (LifecycleError, OSError):
            pass
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="failed_recoverable",
            code="upgrade_failed_fenced",
            message=f"{primary_message}; rollback failed ({rb_code}): {rb_msg}; preserve backup and fenced candidate",
            installation_published=published_restored,
        )


def _canonical_phase_for_step(completed: str | None) -> str:
    if completed == "health":
        return "release_activated"
    if completed == "scm":
        return "data_ready"
    return "prepared"


def _monotonic_phase(current: str, requested: str, next_step: UpgradeStepName) -> str:
    floor = _canonical_phase_for_step(next_step)
    candidates = [requested, floor]
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
    phase: str,
    step: UpgradeStepName,
    no_return_point: bool | None = None,
) -> UpgradeOperation:
    next_step = _furthest_step(active.completed_step, step)
    next_phase = _monotonic_phase(active.phase, phase, next_step)
    candidate = replace(
        active,
        phase=next_phase,  # type: ignore[arg-type]
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
    return current  # type: ignore[return-value]


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
