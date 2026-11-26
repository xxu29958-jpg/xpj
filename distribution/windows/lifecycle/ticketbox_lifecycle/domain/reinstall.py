"""Narrow reinstall coordinator: rebind preserved data and identity without running initdb."""

from __future__ import annotations

import os
import secrets
from dataclasses import replace
from typing import Protocol

from ticketbox_lifecycle.domain.install import hash_request_payload
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    CommandResult,
    InstallationBinding,
    InstallRequest,
    ReinstallOperation,
)


class ReinstallPlatform(Protocol):
    def publish_and_verify_program_acls(self, request: InstallRequest) -> None: ...

    def verify_preserved_dataset(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> dict[str, object]: ...

    def verify_candidate_health(self, request: InstallRequest) -> None: ...

    def verify_normal_health(self, request: InstallRequest) -> None: ...

    def update_start_menu_shortcut(self, request: InstallRequest) -> None: ...


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def reinstall(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: ReinstallPlatform,
) -> CommandResult:
    """Reinstall program/services over verified preserved data; never run initdb or adopt orphans."""
    if request.command != "reinstall":
        raise LifecycleViolation("unsupported_command", f"reinstall path cannot execute {request.command}")
    stores.mutex.acquire()
    try:
        return _reinstall_locked(stores, request, platform)
    finally:
        stores.mutex.release()


def _reinstall_locked(
    stores: LifecycleStores,
    request: InstallRequest,
    platform: ReinstallPlatform,
) -> CommandResult:
    binding = stores.binding_read.read()
    existing = stores.operations_read.read_active()
    if binding is None:
        raise LifecycleViolation(
            "reinstall_binding_missing",
            "preserved-data reinstall requires an existing verified installation.json; refusing orphan data adoption",
        )

    allowed_siblings = _known_siblings(stores, binding, request.target_release_id)
    request = stores.shipment.bind_and_verify(
        request,
        allowed_sibling_releases=allowed_siblings,
    )
    observation = stores.observer.observe(request)
    if not observation.pgdata_present:
        raise LifecycleViolation(
            "reinstall_pgdata_missing",
            "preserved-data reinstall requires existing pgdata; refusing to run initdb",
        )
    if (
        binding.active_release_id != request.target_release_id
        or binding.release_manifest_sha256 != request.release_manifest_sha256
    ):
        raise LifecycleViolation(
            "reinstall_version_mismatch",
            "preserved-data reinstall requires the exact matching installed release and manifest",
        )
    if (
        _norm_path(binding.data_root) != _norm_path(request.data_root)
        or binding.pg_service_name != request.pg_service_name
        or binding.backend_service_name != request.backend_service_name
        or binding.pg_port != request.pg_port
        or binding.backend_port != request.backend_port
        or binding.postgres_major != request.postgres_major
        or (request.install_id and request.install_id != binding.install_id)
        or (request.dataset_id and request.dataset_id != binding.dataset_id)
    ):
        raise LifecycleViolation(
            "reinstall_identity_mismatch",
            "reinstall request does not match preserved installation binding",
        )
    if existing is not None:
        if (
            not isinstance(existing, ReinstallOperation)
            or existing.kind != "reinstall"
            or existing.operation_id != request.operation_id
            or existing.install_id != binding.install_id
            or existing.dataset_id != binding.dataset_id
            or existing.expected_restore_epoch != binding.expected_restore_epoch
        ):
            raise LifecycleViolation(
                "operation_conflict",
                "another active lifecycle operation owns the machine",
            )

    new_health_key = existing.health_attestation_key if existing is not None else secrets.token_hex(32)
    bound = replace(
        request,
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        health_attestation_key=new_health_key,
    )
    if existing is not None:
        active = replace(existing, phase="prepared") if existing.phase == "failed_recoverable" else existing
        stores.operations_write.prepare(bound)
        stores.operations_write.publish_active(active)
    else:
        request_hash = hash_request_payload(
            {
                "kind": "reinstall",
                "install_id": binding.install_id,
                "dataset_id": binding.dataset_id,
                "expected_restore_epoch": binding.expected_restore_epoch,
                "target_release_id": bound.target_release_id,
                "release_manifest_sha256": bound.release_manifest_sha256,
                "data_root": bound.data_root,
            }
        )
        stores.operations_write.prepare(bound)
        active = ReinstallOperation(
            schema=OPERATION_SCHEMA,
            operation_id=bound.operation_id,
            kind="reinstall",
            request_hash=request_hash,
            target_release_id=bound.target_release_id,
            data_root=bound.data_root,
            release_manifest_sha256=bound.release_manifest_sha256,
            backend_port=bound.backend_port,
            phase="prepared",
            no_return_point=False,
            completed_step=None,
            install_id=bound.install_id,
            dataset_id=bound.dataset_id,
            schema_revision=bound.schema_revision,
            health_attestation_key=new_health_key,
            expected_restore_epoch=binding.expected_restore_epoch,
        )
        stores.operations_write.publish_active(active)

    published = False
    try:
        platform.publish_and_verify_program_acls(bound)
        stores.adapters.files.apply(bound, "programdata_root")
        stores.adapters.files.verify(bound, "programdata_root")
        stores.adapters.security.apply(bound, "acl")
        stores.adapters.security.verify(bound, "acl")
        stores.adapters.scm.apply(bound, "scm")
        stores.adapters.scm.verify(bound, "scm")
        _ensure_postcondition(stores.adapters.postgres, bound, "start_postgres")
        stores.adapters.postgres.verify(bound, "roles_database")
        stores.adapters.alembic.verify(bound, "alembic")
        dataset_evidence = platform.verify_preserved_dataset(bound, binding)

        active = replace(active, phase="data_ready", completed_step="scm", no_return_point=True)
        stores.operations_write.publish_active(active)
        stores.adapters.scm.apply(bound, "start_services")
        stores.adapters.scm.verify(bound, "start_services")
        platform.verify_candidate_health(bound)
        stores.adapters.scm.fence_backend(bound)

        active = replace(active, phase="release_activated", completed_step="health", no_return_point=True)
        stores.operations_write.publish_active(active)
        refreshed = replace(binding, health_attestation_key=new_health_key)
        stores.binding_write.publish(refreshed)
        published = True
        platform.update_start_menu_shortcut(bound)

        active = replace(active, phase="committed", completed_step="health", no_return_point=True)
        stores.operations_write.publish_active(active)
        stores.adapters.scm.apply(bound, "start_services")
        stores.adapters.scm.verify(bound, "start_services")
        platform.verify_normal_health(bound)
        stores.adapters.scm.enable_autostart(bound)
        stores.operations_write.archive_committed(active)
    except Exception as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "reinstall_failed"
        message = exc.message if isinstance(exc, LifecycleError) else "preserved-data reinstall failed"
        try:
            stores.adapters.scm.fence_backend(bound)
        except (LifecycleError, OSError):
            pass
        failed = replace(active, phase="failed_recoverable")
        try:
            stores.operations_write.publish_active(failed)
        except (LifecycleError, OSError):
            pass
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="reinstall",
            operation_id=bound.operation_id,
            phase="failed_recoverable",
            code=code,
            message=message,
            installation_published=published,
        )

    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command="reinstall",
        operation_id=bound.operation_id,
        phase="committed",
        code="reinstalled_data_preserved",
        message="Reinstall completed with preserved dataset, originals, and installation identity.",
        installation_published=True,
        client_generation=binding.install_id,
        restore_epoch=binding.expected_restore_epoch,
        details={
            "dataset_id": binding.dataset_id,
            "verified_originals": dataset_evidence.get("verified_originals", 0),
        },
    )


def _known_siblings(
    stores: LifecycleStores,
    binding: InstallationBinding,
    target_release_id: str,
) -> frozenset[str]:
    releases: set[str] = set()
    if binding.previous_release_id:
        releases.add(binding.previous_release_id)
    for record in stores.operations_read.list_committed():
        if getattr(record, "install_id", None) != binding.install_id:
            continue
        if getattr(record, "dataset_id", None) != binding.dataset_id:
            continue
        rid = getattr(record, "target_release_id", None)
        if isinstance(rid, str) and rid:
            releases.add(rid)
        prev = getattr(record, "previous_release_id", None)
        if isinstance(prev, str) and prev:
            releases.add(prev)
    excluded = target_release_id.casefold()
    return frozenset(rid for rid in releases if rid.casefold() != excluded)


def _ensure_postcondition(adapter, request: InstallRequest, step: str) -> None:
    try:
        adapter.verify(request, step)
        return
    except LifecycleError:
        pass
    adapter.apply(request, step)
    adapter.verify(request, step)
