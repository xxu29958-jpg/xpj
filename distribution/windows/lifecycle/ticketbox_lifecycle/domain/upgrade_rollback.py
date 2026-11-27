"""Failure, quarantine, and pre-write rollback state machine for managed upgrades."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace

from ticketbox_lifecycle.adapters.upgrade import UpgradePlatform
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.domain.upgrade_state import (
    _append_failure_detail,
    _bind_upgrade_request,
    _CommitState,
    _durable_commit_state,
    _error_code_and_message,
    hash_upgrade_identity,
)
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    CommandResult,
    DurablePhase,
    InstallationBinding,
    InstallRequest,
    RestoreOperation,
    UpgradeOperation,
)


def _resolve_post_commit_failure_result(
    request: InstallRequest,
    active: UpgradeOperation,
    *,
    code: str,
    message: str,
    published: bool | None,
    commit_state: _CommitState,
    observed_phase: DurablePhase | None,
    commit_publish_attempted: bool,
    rollback_on_failure: bool,
) -> CommandResult:
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
    code, message = _error_code_and_message(primary)
    should_fence = any((
        services_stopped,
        active.no_return_point,
        bool(active.backup_path),
        target_materialized,
        new_binding_published,
        commit_publish_attempted,
    ))
    if should_fence:
        try:
            platform.fence_backend_for_upgrade(
                bound,
                expected_previous_release_id=active.previous_release_id,
            )
        except (LifecycleError, OSError) as failure:
            message = _append_failure_detail(message, "backend fence failed", failure)

    published, commit_state, observed_phase = _durable_commit_state(
        stores,
        request,
        active,
        new_binding_published=new_binding_published,
        commit_publish_attempted=commit_publish_attempted,
    )
    if commit_state != "not_committed" or active.business_writes_opened or published is not False:
        return _resolve_post_commit_failure_result(
            request,
            active,
            code=code,
            message=message,
            published=published,
            commit_state=commit_state,
            observed_phase=observed_phase,
            commit_publish_attempted=commit_publish_attempted,
            rollback_on_failure=rollback_on_failure,
        )

    has_backup = bool(active.backup_path and active.backup_sha256)
    if rollback_on_failure and has_backup:
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

    if not active.no_return_point and (target_materialized or has_backup):
        try:
            platform.cleanup_uncommitted_target_release(bound)
        except (LifecycleError, OSError) as failure:
            message = _append_failure_detail(message, "target cleanup failed", failure)

    failed = replace(active, phase="failed_recoverable")
    try:
        stores.operations_write.publish_active(failed)
    except (LifecycleError, OSError) as failure:
        message = _append_failure_detail(message, "failed-state publication failed", failure)
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


def _read_rollback_durable_state(
    stores: LifecycleStores,
    operation_id: str,
) -> tuple[InstallationBinding | None, object, object]:
    try:
        binding = stores.binding_read.read()
        persisted_active = stores.operations_read.read_active()
        persisted_history = stores.operations_read.read_committed(operation_id) if operation_id else None
    except (LifecycleError, OSError, ValueError) as exc:
        raise LifecycleViolation(
            "upgrade_rollback_refused_writes_may_have_opened",
            "cannot prove normal business writes never opened because durable state is unreadable",
        ) from exc
    return binding, persisted_active, persisted_history


def _validate_rollback_lineage(
    persisted_active: UpgradeOperation,
    binding: InstallationBinding | None,
) -> InstallationBinding:
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
    return binding


def _validate_rollback_request_match(
    request: InstallRequest,
    persisted_active: UpgradeOperation,
    binding: InstallationBinding,
) -> None:
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


def _require_rollback_eligible(
    stores: LifecycleStores,
    request: InstallRequest,
    *,
    new_binding_published: bool = False,
    commit_publish_attempted: bool = False,
) -> tuple[UpgradeOperation, InstallationBinding]:
    binding, persisted_active, persisted_history = _read_rollback_durable_state(stores, request.operation_id)
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
        raise LifecycleViolation("operation_conflict", "active operation is not a managed upgrade")
    if persisted_active.operation_id != request.operation_id:
        raise LifecycleViolation(
            "operation_conflict",
            "rollback request operation_id does not match the active upgrade operation",
        )
    verified_binding = _validate_rollback_lineage(persisted_active, binding)
    _validate_rollback_request_match(request, persisted_active, verified_binding)
    return persisted_active, verified_binding


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
