"""Managed existing-dataset upgrade coordinator with pre-DDL cold backup and attestation."""

from __future__ import annotations

import secrets
from dataclasses import replace

from ticketbox_lifecycle.adapters.upgrade import UpgradePlatform
from ticketbox_lifecycle.domain.binding import require_binding_match, upgrade_binding
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.domain.planner import plan_managed_upgrade
from ticketbox_lifecycle.domain.upgrade_rollback import (
    _failed_upgrade_result,
    _rollback_upgrade_standalone_locked,
)
from ticketbox_lifecycle.domain.upgrade_state import (
    _advance,
    _bind_upgrade_request,
    _binding_matches_upgrade_target,
    _canonical_phase_for_step,
    _ensure_postcondition,
    _furthest_step,
    _known_sibling_releases,
    _monotonic_phase,
    _UpgradeState,
    hash_upgrade_identity,
)
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    CommandResult,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)

__all__ = ["hash_upgrade_identity", "rollback_upgrade", "upgrade"]


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
        state.active = replace(state.active, phase=resume_phase)
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
            phase=_monotonic_phase(state.active.phase, "prepared", _furthest_step(state.active.completed_step, "cold_backup")),
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
