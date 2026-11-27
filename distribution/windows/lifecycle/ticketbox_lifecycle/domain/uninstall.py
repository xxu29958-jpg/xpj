"""Controlled default uninstall: remove owned services/projections while preserving data and identity."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol

from ticketbox_lifecycle.connector_schema import ConnectorOperation
from ticketbox_lifecycle.domain.install import hash_request_payload
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    ActiveOperation,
    CommandResult,
    InstallationBinding,
    InstallRequest,
    ReinstallOperation,
    UninstallOperation,
    UpgradeOperation,
)


class UninstallPlatform(Protocol):
    def verify_owned_services(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None: ...

    def verify_registered_release_manifests(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        release_ids: tuple[str, ...],
        expected_manifests: Mapping[str, str],
        resuming_cleanup: bool = False,
    ) -> None: ...

    def stop_and_unregister_services(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> list[str]: ...

    def remove_start_menu_shortcut(self, request: InstallRequest) -> bool: ...

    def cleanup_registered_release_payloads(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        release_ids: tuple[str, ...],
        expected_manifests: Mapping[str, str] | None = None,
        resuming_cleanup: bool = False,
    ) -> list[str]: ...


def _is_sha256_hex(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def _registered_releases(
    stores: LifecycleStores,
    binding: InstallationBinding,
) -> tuple[tuple[str, ...], dict[str, str]]:
    ordered: list[str] = []
    seen: dict[str, str] = {}
    manifests: dict[str, str] = {}

    def _add(rid: str | None, manifest_sha: str | None = None) -> None:
        if not rid:
            return
        key = rid.casefold()
        canonical = seen.get(key)
        if canonical is None:
            canonical = rid
            seen[key] = canonical
            ordered.append(canonical)
        if _is_sha256_hex(manifest_sha) and manifest_sha is not None:
            normalized = manifest_sha.lower()
            existing = manifests.get(canonical)
            if existing is not None and existing != normalized:
                raise LifecycleViolation(
                    "uninstall_release_manifest_mismatch",
                    f"conflicting manifest digests recorded in installation history for release {canonical}",
                )
            manifests[canonical] = normalized

    _add(binding.active_release_id, binding.release_manifest_sha256)
    _add(binding.previous_release_id)
    for record in stores.operations_read.list_committed():
        if not isinstance(record, ActiveOperation):
            continue
        if record.install_id != binding.install_id or record.dataset_id != binding.dataset_id:
            continue
        _add(record.target_release_id, record.release_manifest_sha256)
        if isinstance(record, UpgradeOperation):
            _add(record.previous_release_id, record.previous_release_manifest_sha256)
    return tuple(ordered), manifests


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _require_uninstall_binding_match(
    request: InstallRequest,
    binding: InstallationBinding,
) -> None:
    if (
        _norm_path(binding.data_root) != _norm_path(request.data_root)
        or binding.pg_service_name != request.pg_service_name
        or binding.backend_service_name != request.backend_service_name
        or binding.pg_port != request.pg_port
        or binding.backend_port != request.backend_port
        or binding.postgres_major != request.postgres_major
        or not _is_sha256_hex(binding.release_manifest_sha256)
        or not _is_sha256_hex(request.release_manifest_sha256)
        or request.target_release_id != binding.active_release_id
        or request.release_manifest_sha256.lower() != binding.release_manifest_sha256.lower()
        or (request.install_id and request.install_id != binding.install_id)
        or (request.dataset_id and request.dataset_id != binding.dataset_id)
    ):
        raise LifecycleViolation(
            "uninstall_identity_mismatch",
            "uninstall request does not match the verified installation binding",
        )


def _uninstall_request_hash(binding: InstallationBinding) -> str:
    return hash_request_payload(
        {
            "kind": "uninstall",
            "install_id": binding.install_id,
            "dataset_id": binding.dataset_id,
            "expected_restore_epoch": binding.expected_restore_epoch,
            "active_release_id": binding.active_release_id,
            "release_manifest_sha256": binding.release_manifest_sha256.lower(),
            "data_root": _norm_path(binding.data_root),
            "health_attestation_key": binding.health_attestation_key,
        }
    )


def _legacy_uninstall_request_hash(binding: InstallationBinding) -> str:
    return hash_request_payload(
        {
            "kind": "uninstall",
            "install_id": binding.install_id,
            "dataset_id": binding.dataset_id,
            "expected_restore_epoch": binding.expected_restore_epoch,
            "active_release_id": binding.active_release_id,
            "release_manifest_sha256": binding.release_manifest_sha256,
            "data_root": binding.data_root,
        }
    )


def _is_legacy_uninstall_predated_by_incarnation(
    stores: LifecycleStores,
    binding: InstallationBinding,
    uninstall_op: UninstallOperation,
    *,
    uninstall_is_active: bool = False,
) -> bool:
    binding_checker = getattr(stores.operations_read, "written_strictly_after_binding", None)
    if not callable(binding_checker) or not binding_checker(
        uninstall_op.operation_id,
        is_active=uninstall_is_active,
    ):
        return True
    checker = getattr(stores.operations_read, "committed_strictly_after", None)
    for record in stores.operations_read.list_committed():
        if not (
            isinstance(record, ReinstallOperation)
            and record.kind == "reinstall"
            and record.phase == "committed"
            and record.install_id == binding.install_id
            and record.dataset_id == binding.dataset_id
            and record.expected_restore_epoch == binding.expected_restore_epoch
            and _is_sha256_hex(record.health_attestation_key)
            and record.health_attestation_key == binding.health_attestation_key
        ):
            continue
        if callable(checker) and checker(
            record.operation_id,
            uninstall_op.operation_id,
            later_is_active=uninstall_is_active,
        ):
            continue
        return True
    return False


def _matches_uninstall_identity(
    op: ActiveOperation | ConnectorOperation | None,
    binding: InstallationBinding,
    *,
    expected_operation_id: str,
) -> bool:
    return (
        isinstance(op, UninstallOperation)
        and op.kind == "uninstall"
        and op.operation_id == expected_operation_id
        and op.install_id == binding.install_id
        and op.dataset_id == binding.dataset_id
        and op.target_release_id == binding.active_release_id
        and op.backend_port == binding.backend_port
        and _norm_path(op.data_root) == _norm_path(binding.data_root)
        and _is_sha256_hex(op.release_manifest_sha256)
        and _is_sha256_hex(binding.release_manifest_sha256)
        and op.release_manifest_sha256.lower() == binding.release_manifest_sha256.lower()
        and _is_sha256_hex(op.health_attestation_key)
    )


def _is_committed_uninstall_complete(op: UninstallOperation) -> bool:
    return (
        op.phase == "committed"
        and op.no_return_point is True
        and op.completed_step == "remove_shortcut"
    )


def _matches_strict_current_incarnation(
    op: UninstallOperation,
    binding: InstallationBinding,
    *,
    expected_request_hash: str,
) -> bool:
    return (
        op.expected_restore_epoch == binding.expected_restore_epoch
        and op.health_attestation_key == binding.health_attestation_key
        and op.request_hash == expected_request_hash
    )


def _is_same_incarnation_hash_conflict(
    op: UninstallOperation,
    binding: InstallationBinding,
    *,
    expected_request_hash: str,
) -> bool:
    return (
        op.expected_restore_epoch == binding.expected_restore_epoch
        and op.health_attestation_key == binding.health_attestation_key
        and op.request_hash != expected_request_hash
    )


def _matches_legacy_committed_incarnation(
    op: UninstallOperation,
    binding: InstallationBinding,
    stores: LifecycleStores,
    *,
    legacy_request_hash: str,
    from_active: bool = False,
) -> bool:
    return (
        _is_committed_uninstall_complete(op)
        and op.expected_restore_epoch == binding.expected_restore_epoch
        and op.health_attestation_key != binding.health_attestation_key
        and op.request_hash == legacy_request_hash
        and not _is_legacy_uninstall_predated_by_incarnation(
            stores,
            binding,
            op,
            uninstall_is_active=from_active,
        )
    )


def _is_prior_committed_uninstall(
    op: UninstallOperation,
    binding: InstallationBinding,
    stores: LifecycleStores,
) -> bool:
    epoch_advanced = op.expected_restore_epoch < binding.expected_restore_epoch
    key_rotated = (
        op.expected_restore_epoch == binding.expected_restore_epoch
        and op.health_attestation_key != binding.health_attestation_key
    )
    if not epoch_advanced and not key_rotated:
        return False
    prior_binding = replace(
        binding,
        expected_restore_epoch=op.expected_restore_epoch,
        health_attestation_key=op.health_attestation_key,
    )
    if op.request_hash == _uninstall_request_hash(prior_binding):
        return True
    return op.request_hash == _legacy_uninstall_request_hash(prior_binding) and (
        epoch_advanced
        or _is_legacy_uninstall_predated_by_incarnation(stores, binding, op, uninstall_is_active=False)
    )


def _resolve_committed_uninstall(
    stores: LifecycleStores,
    committed: ActiveOperation | ConnectorOperation | None,
    binding: InstallationBinding,
    *,
    expected_operation_id: str,
    expected_request_hash: str,
    legacy_request_hash: str,
) -> UninstallOperation | None:
    if committed is None:
        return None
    if not _matches_uninstall_identity(
        committed,
        binding,
        expected_operation_id=expected_operation_id,
    ) or not isinstance(committed, UninstallOperation) or not _is_committed_uninstall_complete(committed):
        raise LifecycleViolation(
            "uninstall_operation_conflict",
            "committed lifecycle history for this operation_id does not match the installation binding",
        )
    if _matches_strict_current_incarnation(
        committed,
        binding,
        expected_request_hash=expected_request_hash,
    ):
        return committed
    if _is_same_incarnation_hash_conflict(
        committed,
        binding,
        expected_request_hash=expected_request_hash,
    ):
        raise LifecycleViolation(
            "uninstall_operation_conflict",
            "committed uninstall history conflicts with the current installation incarnation",
        )
    if _matches_legacy_committed_incarnation(
        committed,
        binding,
        stores,
        legacy_request_hash=legacy_request_hash,
        from_active=False,
    ):
        return committed
    if _is_prior_committed_uninstall(committed, binding, stores):
        return None
    raise LifecycleViolation(
        "uninstall_operation_conflict",
        "committed uninstall history conflicts with the current installation incarnation",
    )


def _validate_existing_uninstall_operation(
    stores: LifecycleStores,
    existing: ActiveOperation | ConnectorOperation | None,
    binding: InstallationBinding,
    *,
    expected_operation_id: str,
    expected_request_hash: str,
    legacy_request_hash: str,
) -> UninstallOperation | None:
    if existing is None:
        return None
    if (
        not _matches_uninstall_identity(
            existing,
            binding,
            expected_operation_id=expected_operation_id,
        )
        or not isinstance(existing, UninstallOperation)
        or (
            existing.phase != "failed_recoverable"
            and not _is_committed_uninstall_complete(existing)
        )
    ):
        raise LifecycleViolation(
            "uninstall_operation_active",
            "another active lifecycle operation owns the machine; refusing uninstall",
        )
    if _is_same_incarnation_hash_conflict(
        existing,
        binding,
        expected_request_hash=expected_request_hash,
    ):
        raise LifecycleViolation(
            "uninstall_operation_conflict",
            "active uninstall request_hash conflicts with the current installation binding",
        )
    if existing.phase == "failed_recoverable":
        if not _matches_strict_current_incarnation(
            existing,
            binding,
            expected_request_hash=expected_request_hash,
        ):
            raise LifecycleViolation(
                "uninstall_operation_active",
                "another active lifecycle operation owns the machine; refusing uninstall",
            )
    elif not _matches_strict_current_incarnation(
        existing,
        binding,
        expected_request_hash=expected_request_hash,
    ) and not _matches_legacy_committed_incarnation(
        existing,
        binding,
        stores,
        legacy_request_hash=legacy_request_hash,
        from_active=True,
    ):
        raise LifecycleViolation(
            "uninstall_operation_active",
            "another active lifecycle operation owns the machine; refusing uninstall",
        )
    history_record = stores.operations_read.read_committed(expected_operation_id)
    if existing.phase == "committed":
        if history_record is not None and history_record != existing:
            if not (
                _matches_uninstall_identity(
                    history_record,
                    binding,
                    expected_operation_id=expected_operation_id,
                )
                and isinstance(history_record, UninstallOperation)
                and _is_committed_uninstall_complete(history_record)
                and _is_prior_committed_uninstall(history_record, binding, stores)
            ):
                raise LifecycleViolation(
                    "uninstall_operation_conflict",
                    "committed active uninstall conflicts with archived history for this operation_id",
                )
    elif history_record is not None:
        matched = _resolve_committed_uninstall(
            stores,
            history_record,
            binding,
            expected_operation_id=expected_operation_id,
            expected_request_hash=expected_request_hash,
            legacy_request_hash=legacy_request_hash,
        )
        if matched is not None:
            raise LifecycleViolation(
                "uninstall_operation_conflict",
                "failed_recoverable active uninstall conflicts with already-archived history for this incarnation",
            )
    return existing


def check_uninstall_preflight(
    stores: LifecycleStores,
    *,
    expected_data_root: str | None = None,
    expected_pg_service_name: str | None = None,
    expected_backend_service_name: str | None = None,
    expected_pg_port: int | None = None,
    expected_backend_port: int | None = None,
    expected_postgres_major: int | None = None,
) -> None:
    """Read-only admission check shared by Inno and the uninstall coordinator."""
    binding = stores.binding_read.read()
    existing = stores.operations_read.read_active()
    if binding is None or not _is_sha256_hex(binding.release_manifest_sha256):
        raise LifecycleViolation(
            "uninstall_binding_missing",
            "controlled uninstall requires a verified installation.json; refusing unbound deletion",
        )
    if (
        (expected_data_root is not None and _norm_path(binding.data_root) != _norm_path(expected_data_root))
        or (expected_pg_service_name is not None and binding.pg_service_name != expected_pg_service_name)
        or (
            expected_backend_service_name is not None
            and binding.backend_service_name != expected_backend_service_name
        )
        or (expected_pg_port is not None and binding.pg_port != expected_pg_port)
        or (expected_backend_port is not None and binding.backend_port != expected_backend_port)
        or (expected_postgres_major is not None and binding.postgres_major != expected_postgres_major)
    ):
        raise LifecycleViolation(
            "uninstall_identity_mismatch",
            "installed binding does not match the closed machine contract",
        )
    expected_operation_id = f"uninstall-{binding.release_manifest_sha256.lower()}"
    request_hash = _uninstall_request_hash(binding)
    legacy_hash = _legacy_uninstall_request_hash(binding)
    validated = _validate_existing_uninstall_operation(
        stores,
        existing,
        binding,
        expected_operation_id=expected_operation_id,
        expected_request_hash=request_hash,
        legacy_request_hash=legacy_hash,
    )
    if validated is None:
        _resolve_committed_uninstall(
            stores,
            stores.operations_read.read_committed(expected_operation_id),
            binding,
            expected_operation_id=expected_operation_id,
            expected_request_hash=request_hash,
            legacy_request_hash=legacy_hash,
        )


def uninstall(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UninstallPlatform,
) -> CommandResult:
    """Stop and unregister only owned services; preserve pgdata, originals, backups and installation.json."""
    if request.command != "uninstall":
        raise LifecycleViolation("unsupported_command", f"uninstall path cannot execute {request.command}")
    stores.mutex.acquire()
    try:
        return _uninstall_locked(stores, request, platform)
    finally:
        stores.mutex.release()


def _committed_uninstall_result(
    bound: InstallRequest,
    binding: InstallationBinding,
    *,
    removed_services: list[str],
    removed_releases: list[str],
    shortcut_removed: bool,
) -> CommandResult:
    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command="uninstall",
        operation_id=bound.operation_id,
        phase="committed",
        code="uninstalled_data_preserved",
        message="Controlled uninstall completed; services unregistered and database, originals, backups and installation identity preserved.",
        installation_published=True,
        client_generation=binding.install_id,
        restore_epoch=binding.expected_restore_epoch,
        details={
            "dataset_id": binding.dataset_id,
            "removed_services": removed_services,
            "removed_releases": removed_releases,
            "shortcut_removed": shortcut_removed,
            "data_preserved": True,
            "backups_preserved": True,
            "binding_preserved": True,
        },
    )


def _prepare_uninstall_active(
    stores: LifecycleStores,
    bound: InstallRequest,
    binding: InstallationBinding,
    existing: ActiveOperation | ConnectorOperation | None,
    request_hash: str,
) -> UninstallOperation:
    if isinstance(existing, UninstallOperation):
        return existing
    stores.operations_write.prepare(bound)
    active = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=bound.operation_id,
        kind="uninstall",
        request_hash=request_hash,
        target_release_id=binding.active_release_id,
        data_root=binding.data_root,
        release_manifest_sha256=binding.release_manifest_sha256,
        backend_port=binding.backend_port,
        phase="prepared",
        no_return_point=False,
        completed_step=None,
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision=bound.schema_revision or "",
        health_attestation_key=bound.health_attestation_key,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    stores.operations_write.publish_active(active)
    return active


def _uninstall_locked(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: UninstallPlatform,
) -> CommandResult:
    binding = stores.binding_read.read()
    existing = stores.operations_read.read_active()
    if binding is None:
        raise LifecycleViolation(
            "uninstall_binding_missing",
            "controlled uninstall requires a verified installation.json; refusing unbound deletion",
        )
    _require_uninstall_binding_match(request, binding)
    request_hash = _uninstall_request_hash(binding)
    legacy_hash = _legacy_uninstall_request_hash(binding)
    validated_existing = _validate_existing_uninstall_operation(
        stores,
        existing,
        binding,
        expected_operation_id=request.operation_id,
        expected_request_hash=request_hash,
        legacy_request_hash=legacy_hash,
    )
    committed = (
        _resolve_committed_uninstall(
            stores,
            stores.operations_read.read_committed(request.operation_id),
            binding,
            expected_operation_id=request.operation_id,
            expected_request_hash=request_hash,
            legacy_request_hash=legacy_hash,
        )
        if validated_existing is None
        else None
    )

    bound = replace(
        request,
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        target_release_id=binding.active_release_id,
        release_manifest_sha256=binding.release_manifest_sha256,
        health_attestation_key=binding.health_attestation_key,
    )
    resuming_cleanup = (
        validated_existing is not None and validated_existing.no_return_point
    ) or committed is not None
    platform.verify_owned_services(bound, binding)
    registered_releases, expected_manifests = _registered_releases(stores, binding)
    platform.verify_registered_release_manifests(
        bound,
        binding,
        release_ids=registered_releases,
        expected_manifests=expected_manifests,
        resuming_cleanup=resuming_cleanup,
    )

    durable_committed = committed is not None or (
        validated_existing is not None and validated_existing.phase == "committed"
    )
    if committed is not None:
        active: UninstallOperation | None = None
    elif validated_existing is not None and validated_existing.phase == "committed":
        active = validated_existing
    else:
        active = _prepare_uninstall_active(stores, bound, binding, validated_existing, request_hash)

    try:
        removed_services = platform.stop_and_unregister_services(bound, binding)
        if active is not None and not durable_committed:
            progressed = replace(
                active,
                request_hash=request_hash,
                health_attestation_key=binding.health_attestation_key,
                completed_step="unregister_services",
                no_return_point=True,
            )
            stores.operations_write.publish_active(progressed)
            active = progressed
        shortcut_removed = platform.remove_start_menu_shortcut(bound)
        removed_releases = platform.cleanup_registered_release_payloads(
            bound,
            binding,
            release_ids=registered_releases,
            expected_manifests=expected_manifests,
            resuming_cleanup=resuming_cleanup,
        )
        if active is not None:
            if not durable_committed:
                committed_op = replace(
                    active,
                    phase="committed",
                    completed_step="remove_shortcut",
                    no_return_point=True,
                )
                stores.operations_write.publish_active(committed_op)
                active = committed_op
                durable_committed = True
            stores.operations_write.archive_committed(active)
    except Exception as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "uninstall_failed"
        message = exc.message if isinstance(exc, LifecycleError) else "controlled uninstall failed; preserved data untouched"
        if active is not None and not durable_committed:
            failed = replace(active, phase="failed_recoverable")
            try:
                stores.operations_write.publish_active(failed)
            except (LifecycleError, OSError) as publish_exc:
                if (
                    isinstance(publish_exc, LifecycleViolation)
                    and publish_exc.code == "committed_operation_immutable"
                ):
                    durable_committed = True
                else:
                    try:
                        observed = stores.operations_read.read_active()
                    except (LifecycleError, OSError, ValueError):
                        observed = None
                    if (
                        isinstance(observed, UninstallOperation)
                        and observed.operation_id == bound.operation_id
                    ):
                        active = observed
                        if observed.phase == "committed":
                            durable_committed = True
            else:
                active = failed
        reported_phase = (
            "committed"
            if durable_committed
            else (active.phase if active is not None else "failed_recoverable")
        )
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="uninstall",
            operation_id=bound.operation_id,
            phase=reported_phase,
            code=code,
            message=message,
            installation_published=True,
        )

    return _committed_uninstall_result(
        bound,
        binding,
        removed_services=removed_services,
        removed_releases=removed_releases,
        shortcut_removed=shortcut_removed,
    )
