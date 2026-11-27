"""Cold backup, quarantine, and previous-release restore helpers for Windows upgrades."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.adapters.cold_copy import ColdCopySource
from ticketbox_lifecycle.adapters.upgrade import PreUpgradeBackup, RollbackRestoreResult
from ticketbox_lifecycle.domain.binding import binding_from_request
from ticketbox_lifecycle.domain.cold_copy import create_cold_copy_locked
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import cold_archive, layout
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation, read_stopped_cluster
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_cold_copy import (
    COLD_COPY_SPACE_MARGIN_BYTES,
    require_cold_copy_disk_space,
    verify_cold_copy,
)
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive
from ticketbox_lifecycle.runtime.windows_cold_restore import WindowsColdRestore
from ticketbox_lifecycle.runtime.windows_security_native import (
    protect_directory,
    reject_reparse_components,
)
from ticketbox_lifecycle.runtime.windows_services import (
    delete_service,
    scm_query_state,
    service_exists,
    stop_service,
    stop_service_and_wait,
)
from ticketbox_lifecycle.runtime.windows_shipment import (
    WindowsShipmentVerifier,
    _publish_and_verify_tree_acls,
)
from ticketbox_lifecycle.schemas import (
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)


@dataclass(frozen=True)
class UpgradeBackupContext:
    stores: FilesystemStores
    runner: CommandRunner
    expected_app: Path
    expected_program_data: Path
    verifier: WindowsShipmentVerifier
    fence_backend: Callable[..., None]
    verify_pg_service: Callable[[InstallRequest], None]
    publish_acl: Callable[..., None] | None = None
    verify_acl: Callable[..., None] | None = None
    protect_dir_fn: Callable[..., None] = protect_directory
    archive_creator: Callable[[Path], AbstractContextManager[BinaryIO]] = create_private_archive
    cold_restore_cls: type[WindowsColdRestore] = WindowsColdRestore


class _HeldLockColdCopyPlatform:
    def __init__(
        self,
        stores: FilesystemStores,
        runner: CommandRunner,
        app_dir: Path,
        program_data: Path,
        allowed_operation_id: str,
        target_release_id: str,
        *,
        archive_creator: Callable[[Path], AbstractContextManager[BinaryIO]] = create_private_archive,
    ) -> None:
        self.mutex = stores._mutex
        self._stores = stores
        self._runner = runner
        self._app_dir = app_dir
        self._program_data = program_data
        self._allowed_operation_id = allowed_operation_id
        self._target_release_id = target_release_id
        self._archive_creator = archive_creator

    def read_source(self) -> ColdCopySource:
        return ColdInstallation.read(
            self._stores,
            self._app_dir,
            self._program_data,
            allowed_operation_id=self._allowed_operation_id,
            target_release_id=None,
            runner=self._runner,
        )

    def check_disk_space(self, output: Path, source: ColdCopySource) -> None:
        require_cold_copy_disk_space(output, source)

    def create_archive(self, output: Path) -> AbstractContextManager[BinaryIO]:
        return self._archive_creator(output)

    def write_archive(self, target: BinaryIO, source: ColdCopySource) -> dict[str, object]:
        rp_fn = getattr(source, "recovery_point", None)
        recovery_point = rp_fn() if callable(rp_fn) else None
        return cold_archive.write_archive(
            target,
            source.roots(),
            source.identity(),
            source.require_stopped,
            exclude_entry=getattr(source, "exclude_entry", None),
            recovery_point=recovery_point,
        )

    def verify_archive(self, target: BinaryIO) -> dict[str, object]:
        return cold_archive.verify_archive(target)


def check_backup_disk_space(
    ctx: UpgradeBackupContext,
    binding: InstallationBinding,
) -> None:
    backup_dir = ctx.expected_program_data / "backups"
    reject_reparse_components(backup_dir)
    data = Path(binding.data_root)
    roots = {
        "program": ctx.expected_app,
        "machine": ctx.expected_program_data / "machine",
        "data/pgdata": data / "pgdata",
        "data/attachments": data / "attachments",
        "data/app": data / "app",
    }
    active_rel_prefix = f"program/releases/{binding.active_release_id.casefold()}/"

    def _exclude(relative: str) -> bool:
        folded = relative.replace("\\", "/").casefold()
        if folded == "machine/operations/active.json":
            return True
        if folded.startswith("program/releases/") and folded != "program/releases/":
            return not folded.startswith(active_rel_prefix)
        return False

    required = cold_archive.estimate_source_bytes(roots, exclude_entry=_exclude)
    anchor = backup_dir.anchor or str(ctx.expected_program_data.resolve())
    if shutil.disk_usage(anchor).free < required + COLD_COPY_SPACE_MARGIN_BYTES:
        raise LifecycleError(
            "cold_space_insufficient",
            "destination volume lacks free space for pre-upgrade cold backup",
        )


def stop_services_for_backup(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    binding: InstallationBinding,
) -> None:
    ctx.fence_backend(request, expected_previous_release_id=binding.active_release_id)
    ctx.verify_pg_service(request)
    if scm_query_state(ctx.runner, request.pg_service_name) != "STOPPED":
        stop_service(ctx.runner, request.pg_service_name, code="upgrade_pg_stop_failed")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if scm_query_state(ctx.runner, request.pg_service_name) == "STOPPED":
            read_stopped_cluster(ctx.runner, layout.pg_bin(request), layout.pgdata(request))
            return
        time.sleep(1)
    raise LifecycleError("upgrade_pg_stop_timeout", "TicketboxPg did not reach STOPPED")


def verify_cold_backup_restorable(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    archive_path: Path,
    expected_sha256: str,
    binding: InstallationBinding,
    *,
    source_release_id: str,
    source_schema_revision: str,
) -> None:
    manifest_path = ctx.expected_app / "releases" / source_release_id / "release-manifest.json"
    reject_reparse_components(manifest_path)
    manifest_sha = _file_sha256(manifest_path)
    source_binding = replace(
        binding,
        active_release_id=source_release_id,
        release_manifest_sha256=manifest_sha,
    )
    manifest = ctx.verifier.verify_release_manifest(source_binding)
    source_request = replace(
        request,
        target_release_id=source_release_id,
        release_manifest_sha256=manifest_sha,
        schema_revision=source_schema_revision,
        semantic_revision=str(manifest["min_semantic_revision"]),
    )
    with archive_path.open("rb") as stream:
        restore_source = ColdRestoreSource(stream, expected_sha256, source_request)
    if (
        restore_source.identity.get("install_id") != binding.install_id
        or restore_source.identity.get("dataset_id") != binding.dataset_id
        or restore_source.identity.get("restore_epoch") != binding.expected_restore_epoch
    ):
        raise LifecycleViolation(
            "upgrade_backup_identity_mismatch",
            "cold backup restore source identity disagrees with installation",
        )


def create_verified_cold_backup(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    binding: InstallationBinding,
    *,
    allowed_operation_id: str,
) -> PreUpgradeBackup:
    backup_dir = ctx.expected_program_data / "backups"
    reject_reparse_components(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    ctx.protect_dir_fn(ctx.runner, backup_dir, code="upgrade_backup_acl_failed")
    output = backup_dir / f"pre-upgrade-{allowed_operation_id}-{uuid.uuid4().hex[:12]}.tbxcold"
    cold_platform = _HeldLockColdCopyPlatform(
        ctx.stores,
        ctx.runner,
        ctx.expected_app,
        ctx.expected_program_data,
        allowed_operation_id,
        request.target_release_id,
        archive_creator=ctx.archive_creator,
    )
    summary = create_cold_copy_locked(output, cold_platform)
    identity = summary.get("identity")
    if (
        not isinstance(identity, dict)
        or identity.get("install_id") != binding.install_id
        or identity.get("dataset_id") != binding.dataset_id
        or identity.get("restore_epoch") != binding.expected_restore_epoch
    ):
        raise LifecycleViolation(
            "upgrade_backup_identity_mismatch",
            "cold backup identity does not match existing installation",
        )
    digest = _file_sha256(output)
    schema_revision = str(identity.get("schema_revision") or "")
    verify_cold_backup_restorable(
        ctx,
        request,
        output,
        digest,
        binding,
        source_release_id=binding.active_release_id,
        source_schema_revision=schema_revision,
    )
    return PreUpgradeBackup(
        path=str(output),
        sha256=digest,
        schema_revision=schema_revision,
    )


def verify_existing_cold_backup(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    backup_path: str,
    expected_sha256: str,
    binding: InstallationBinding,
    *,
    source_release_id: str,
    source_schema_revision: str,
) -> None:
    path = Path(backup_path)
    reject_reparse_components(path)
    if not path.is_file():
        raise LifecycleError("upgrade_backup_missing", "recorded pre-upgrade cold backup is missing")
    if _file_sha256(path) != expected_sha256:
        raise LifecycleError("upgrade_backup_corrupt", "recorded pre-upgrade cold backup digest changed")
    summary = verify_cold_copy(path)
    identity = summary.get("identity")
    if (
        not isinstance(identity, dict)
        or identity.get("install_id") != binding.install_id
        or identity.get("dataset_id") != binding.dataset_id
        or identity.get("restore_epoch") != binding.expected_restore_epoch
    ):
        raise LifecycleViolation(
            "upgrade_backup_identity_mismatch",
            "recorded pre-upgrade cold backup identity does not match installation",
        )
    verify_cold_backup_restorable(
        ctx,
        request,
        path,
        expected_sha256,
        binding,
        source_release_id=source_release_id,
        source_schema_revision=source_schema_revision,
    )


def quarantine_failed_upgrade(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    active: UpgradeOperation,
    binding: InstallationBinding,
    *,
    primary_code: str,
    primary_message: str,
) -> str:
    quarantine_root = ctx.expected_program_data / "quarantine"
    reject_reparse_components(quarantine_root)
    quarantine_root.mkdir(parents=True, exist_ok=True)
    ctx.protect_dir_fn(ctx.runner, quarantine_root, code="upgrade_quarantine_acl_failed")
    quarantine_dir = quarantine_root / f"upgrade-failed-{active.operation_id[:24]}-{uuid.uuid4().hex[:12]}"
    reject_reparse_components(quarantine_dir)
    quarantine_dir.mkdir(parents=False, exist_ok=False)
    ctx.protect_dir_fn(ctx.runner, quarantine_dir, code="upgrade_quarantine_acl_failed")

    record = {
        "schema": "ticketbox-upgrade-quarantine-v1",
        "primary_code": primary_code,
        "primary_message": primary_message,
        "operation": asdict(active),
        "previous_binding": asdict(binding),
    }
    durable_write_text(
        quarantine_dir / "failed-upgrade-operation.json",
        json.dumps(record, indent=2, sort_keys=True) + "\n",
    )

    ctx.fence_backend(request, expected_previous_release_id=active.previous_release_id)
    if service_exists(ctx.runner, request.backend_service_name):
        delete_service(ctx.runner, request.backend_service_name, code="rollback_backend_delete_failed")
    if service_exists(ctx.runner, request.pg_service_name):
        ctx.verify_pg_service(request)
        stop_service_and_wait(ctx.runner, request.pg_service_name, code="rollback_pg_stop_failed")
        delete_service(ctx.runner, request.pg_service_name, code="rollback_pg_delete_failed")

    failed_release = ctx.expected_app / "releases" / active.target_release_id
    if os.path.lexists(failed_release):
        reject_reparse_components(failed_release)
        shutil.copytree(failed_release, quarantine_dir / "failed-release")
        shutil.rmtree(failed_release)

    failed_data = Path(binding.data_root)
    if os.path.lexists(failed_data):
        reject_reparse_components(failed_data)
        os.replace(failed_data, quarantine_dir / "failed-data")

    return str(quarantine_dir)


def restore_previous_from_backup(
    ctx: UpgradeBackupContext,
    request: InstallRequest,
    active: UpgradeOperation,
    binding: InstallationBinding,
    *,
    new_install_id: str,
    rollback_operation_id: str,
    new_health_key: str,
    target_restore_epoch: int,
) -> RollbackRestoreResult:
    expected_app = ctx.expected_app
    manifest_path = expected_app / "releases" / active.previous_release_id / "release-manifest.json"
    reject_reparse_components(manifest_path)
    prev_manifest_sha = _file_sha256(manifest_path)
    if prev_manifest_sha != active.previous_release_manifest_sha256:
        raise LifecycleViolation(
            "rollback_previous_release_mismatch",
            "installed previous release manifest no longer matches pre-upgrade backup",
        )
    prev_binding_check = replace(
        binding,
        active_release_id=active.previous_release_id,
        release_manifest_sha256=prev_manifest_sha,
    )
    prev_manifest = ctx.verifier.verify_release_manifest(prev_binding_check)
    prev_request = replace(
        request,
        command="restore",
        operation_id=rollback_operation_id,
        target_release_id=active.previous_release_id,
        release_manifest_sha256=prev_manifest_sha,
        install_id=new_install_id,
        dataset_id=binding.dataset_id,
        schema_revision=active.source_schema_revision,
        schema_min_compatible=str(prev_manifest["product_version"]),
        semantic_revision=str(prev_manifest["min_semantic_revision"]),
        health_attestation_key=new_health_key,
    )
    cold_restore = ctx.cold_restore_cls(ctx.runner)
    backup_path = Path(active.backup_path)
    stage_parent = expected_app.parent / "Ticketbox-UpgradeStage"
    reject_reparse_components(expected_app.parent)
    reject_reparse_components(stage_parent)
    created_stage_parent = not os.path.lexists(stage_parent)
    stage_parent.mkdir(parents=False, exist_ok=True)
    ctx.protect_dir_fn(ctx.runner, stage_parent, code="rollback_stage_acl_failed")
    sync_temp = stage_parent / f"_rollback_tmp_{uuid.uuid4().hex[:12]}"
    reject_reparse_components(sync_temp)
    sync_temp.mkdir(parents=False, exist_ok=False)
    ctx.protect_dir_fn(ctx.runner, sync_temp, code="rollback_stage_acl_failed")
    with cold_restore.open_source(prev_request, backup_path, active.backup_sha256) as source:
        try:
            source.restore_shared_program_files(
                expected_app,
                temp_root=sync_temp,
                publish_acl=ctx.publish_acl,
                verify_acl=ctx.verify_acl,
            )
        finally:
            if sync_temp.exists():
                shutil.rmtree(sync_temp, ignore_errors=True)
            if created_stage_parent and stage_parent.is_dir():
                try:
                    if not any(stage_parent.iterdir()):
                        stage_parent.rmdir()
                except OSError:
                    pass
        lifecycle_dir = expected_app / "bin" / "lifecycle"
        if lifecycle_dir.is_dir():
            _publish_and_verify_tree_acls(lifecycle_dir, publish_acl=ctx.publish_acl, verify_acl=ctx.verify_acl)
        _publish_and_verify_tree_acls(
            expected_app / "releases" / active.previous_release_id,
            publish_acl=ctx.publish_acl,
            verify_acl=ctx.verify_acl,
        )
        prev_siblings = (
            frozenset({binding.previous_release_id})
            if isinstance(binding.previous_release_id, str) and binding.previous_release_id
            else frozenset()
        )
        ctx.verifier.verify_installed(prev_binding_check, allowed_sibling_releases=prev_siblings)
        cold_restore.extract_data(prev_request, source)
        cold_restore.prepare_data(prev_request, source)
        adapters = ctx.stores._adapters
        adapters.files.apply(prev_request, "programdata_root")
        adapters.files.verify(prev_request, "programdata_root")
        adapters.security.apply(prev_request, "acl")
        adapters.security.verify(prev_request, "acl")
        adapters.scm.apply(prev_request, "scm")
        adapters.scm.verify(prev_request, "scm")
        cold_restore.rotate_credentials(prev_request, source)
        adapters.postgres.verify(prev_request, "start_postgres")
        adapters.postgres.verify(prev_request, "roles_database")
        adapters.alembic.verify(prev_request, "alembic")
        pairing = cold_restore.rebind_identity(
            prev_request,
            source,
            secret=adapters.security.owner_bootstrap_secret(prev_request),
        )
        backup_digest = source.digest
    restored_binding = replace(
        binding_from_request(prev_request),
        expected_restore_epoch=target_restore_epoch,
        previous_release_id=None,
    )
    return RollbackRestoreResult(
        previous_request=prev_request,
        pairing=pairing,
        restored_binding=restored_binding,
        backup_digest=backup_digest,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
