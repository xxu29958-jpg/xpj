"""Controlled default uninstall: remove owned services/projections while preserving data and identity."""

from __future__ import annotations

import os
import secrets
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


def _validate_existing_uninstall_operation(
    existing: ActiveOperation | ConnectorOperation | None,
    binding: InstallationBinding,
    *,
    expected_operation_id: str,
) -> None:
    if existing is None:
        return
    if (
        not isinstance(existing, UninstallOperation)
        or existing.kind != "uninstall"
        or existing.phase != "failed_recoverable"
        or existing.operation_id != expected_operation_id
        or existing.install_id != binding.install_id
        or existing.dataset_id != binding.dataset_id
        or not _is_sha256_hex(existing.release_manifest_sha256)
        or not _is_sha256_hex(binding.release_manifest_sha256)
        or existing.release_manifest_sha256.lower() != binding.release_manifest_sha256.lower()
    ):
        raise LifecycleViolation(
            "uninstall_operation_active",
            "another active lifecycle operation owns the machine; refusing uninstall",
        )


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
    _validate_existing_uninstall_operation(
        existing,
        binding,
        expected_operation_id=f"uninstall-{binding.release_manifest_sha256.lower()}",
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
    _validate_existing_uninstall_operation(
        existing,
        binding,
        expected_operation_id=request.operation_id,
    )

    bound = replace(
        request,
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        target_release_id=binding.active_release_id,
        release_manifest_sha256=binding.release_manifest_sha256,
        health_attestation_key=secrets.token_hex(32),
    )
    resuming_cleanup = existing is not None and existing.no_return_point
    platform.verify_owned_services(bound, binding)
    registered_releases, expected_manifests = _registered_releases(stores, binding)
    platform.verify_registered_release_manifests(
        bound,
        binding,
        release_ids=registered_releases,
        expected_manifests=expected_manifests,
        resuming_cleanup=resuming_cleanup,
    )

    if existing is not None:
        active = existing
    else:
        request_hash = hash_request_payload(
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

    try:
        removed_services = platform.stop_and_unregister_services(bound, binding)
        active = replace(active, completed_step="unregister_services", no_return_point=True)
        stores.operations_write.publish_active(active)
        shortcut_removed = platform.remove_start_menu_shortcut(bound)
        removed_releases = platform.cleanup_registered_release_payloads(
            bound,
            binding,
            release_ids=registered_releases,
            expected_manifests=expected_manifests,
            resuming_cleanup=resuming_cleanup,
        )
        active = replace(active, phase="committed", completed_step="remove_shortcut", no_return_point=True)
        stores.operations_write.publish_active(active)
        stores.operations_write.archive_committed(active)
    except Exception as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "uninstall_failed"
        message = exc.message if isinstance(exc, LifecycleError) else "controlled uninstall failed; preserved data untouched"
        failed = replace(active, phase="failed_recoverable")
        try:
            stores.operations_write.publish_active(failed)
        except (LifecycleError, OSError):
            pass
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="uninstall",
            operation_id=bound.operation_id,
            phase="failed_recoverable",
            code=code,
            message=message,
            installation_published=True,
        )

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
