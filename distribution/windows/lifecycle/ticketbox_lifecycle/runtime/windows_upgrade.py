"""Windows platform implementation for existing-dataset managed upgrades."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, replace
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.adapters.cold_copy import ColdCopySource
from ticketbox_lifecycle.adapters.scm import ScmObserver
from ticketbox_lifecycle.adapters.upgrade import (
    PreUpgradeBackup,
    RollbackRestoreResult,
    UpgradeMigrationResult,
)
from ticketbox_lifecycle.domain.binding import binding_from_request
from ticketbox_lifecycle.domain.cold_copy import create_cold_copy_locked
from ticketbox_lifecycle.domain.connector import ConnectorStateStore
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
    require_service_configuration,
)
from ticketbox_lifecycle.runtime import cold_archive, layout
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation, read_stopped_cluster
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_account import lookup_account_sid
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter
from ticketbox_lifecycle.runtime.windows_cold_copy import (
    COLD_COPY_SPACE_MARGIN_BYTES,
    require_cold_copy_disk_space,
    verify_cold_copy,
)
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive
from ticketbox_lifecycle.runtime.windows_cold_restore import WindowsColdRestore
from ticketbox_lifecycle.runtime.windows_connector_files import WindowsConnectorFiles
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
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
from ticketbox_lifecycle.runtime.windows_shortcut import update_manager_start_menu_shortcut
from ticketbox_lifecycle.schemas import (
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)

_ALEMBIC_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")


class _HeldLockColdCopyPlatform:
    def __init__(
        self,
        stores: FilesystemStores,
        runner: CommandRunner,
        app_dir: Path,
        program_data: Path,
        allowed_operation_id: str,
        target_release_id: str,
    ) -> None:
        self.mutex = stores._mutex
        self._stores = stores
        self._runner = runner
        self._app_dir = app_dir
        self._program_data = program_data
        self._allowed_operation_id = allowed_operation_id
        self._target_release_id = target_release_id

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
        return create_private_archive(output)

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


class WindowsUpgradePlatform:
    def __init__(
        self,
        stores: FilesystemStores,
        runner: CommandRunner,
        security: WindowsSecurityAdapter,
        scm: WindowsScmAdapter,
        observer: ScmObserver,
        dataset: WindowsDatasetAdapter | None = None,
        *,
        expected_app_dir: Path | None = None,
        expected_program_data_root: Path | None = None,
        staged_release_root: Path | None = None,
        connector_store_factory: Callable[[Path, str], ConnectorStateStore] | None = None,
        shortcut_updater: Callable[[InstallRequest], None] | None = None,
    ) -> None:
        self._stores = stores
        self._runner = runner
        self._security = security
        self._scm = scm
        self._observer = observer
        self._dataset = dataset if dataset is not None else WindowsDatasetAdapter(runner, security)
        self._expected_app_dir = expected_app_dir
        self._expected_program_data_root = expected_program_data_root
        self._staged_release_root = staged_release_root
        self._connector_store_factory = connector_store_factory
        self._shortcut_updater = shortcut_updater

    def _expected_roots(self) -> tuple[Path, Path]:
        app_dir = self._expected_app_dir if self._expected_app_dir is not None else ticketbox_install_root()
        program_data = (
            self._expected_program_data_root
            if self._expected_program_data_root is not None
            else ticketbox_program_data_root()
        )
        return app_dir, program_data

    def _verifier(self) -> WindowsShipmentVerifier:
        app_dir, program_data = self._expected_roots()
        return WindowsShipmentVerifier(app_dir, program_data)

    def _require_staged_root(self) -> Path:
        if self._staged_release_root is None:
            raise LifecycleViolation(
                "staged_release_missing",
                "managed upgrade requires --staged-release-root",
            )
        return self._staged_release_root

    def _verify_stage_security(self, request: InstallRequest, staged_root: Path) -> None:
        stage_check = getattr(self._security, "verify_upgrade_stage_directory", None)
        if not callable(stage_check):
            return
        app_dir, _program_data = self._expected_roots()
        if Path(request.app_dir).resolve(strict=False) == app_dir.resolve(strict=False):
            stage_check(staged_root)

    def verify_staged_release(
        self,
        request: InstallRequest,
        *,
        require_target_absent: bool = False,
    ) -> InstallRequest:
        staged_root = self._require_staged_root()
        self._verify_stage_security(request, staged_root)
        return self._verifier().verify_staged_release(
            request,
            staged_release_root=staged_root,
            require_target_absent=require_target_absent,
        )

    def _program_acl_hooks(self):
        publish_acl = getattr(self._security, "publish_installed_program_acl", None)
        verify_acl = getattr(self._security, "verify_installed_program_acl", None)
        return (
            publish_acl if callable(publish_acl) else None,
            verify_acl if callable(verify_acl) else None,
        )

    def materialize_target_release(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None:
        del allowed_sibling_releases
        staged_root = self._require_staged_root()
        self._verify_stage_security(request, staged_root)
        publish_acl, verify_acl = self._program_acl_hooks()
        self._verifier().materialize_staged_release(
            request,
            staged_release_root=staged_root,
            publish_acl=publish_acl,
            verify_acl=verify_acl,
        )

    def cleanup_uncommitted_target_release(self, request: InstallRequest) -> None:
        self._verifier().cleanup_uncommitted_target_release(request)

    def read_source_schema_revision(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> str:
        del request
        manifest = self._verifier().verify_release_manifest(binding)
        revision = str(manifest["max_schema_revision"])
        if _ALEMBIC_REVISION.fullmatch(revision) is None or revision == "99991231_9999":
            raise LifecycleViolation(
                "missing_source_schema_revision",
                "installed release manifest lacks a valid schema revision",
            )
        return revision

    def verify_pg_service_for_upgrade(self, request: InstallRequest) -> None:
        require_service_configuration(
            request.pg_service_name,
            self._observer.observe(request.pg_service_name),
            expected_pg_service(request),
            allowed_start_types=frozenset({SERVICE_AUTO_START}),
        )

    def check_backup_disk_space(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None:
        expected_app, expected_program_data = self._expected_roots()
        backup_dir = expected_program_data / "backups"
        reject_reparse_components(backup_dir)
        data = Path(binding.data_root)
        roots = {
            "program": expected_app,
            "machine": expected_program_data / "machine",
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
        anchor = backup_dir.anchor or str(expected_program_data.resolve())
        if shutil.disk_usage(anchor).free < required + COLD_COPY_SPACE_MARGIN_BYTES:
            raise LifecycleError(
                "cold_space_insufficient",
                "destination volume lacks free space for pre-upgrade cold backup",
            )

    def stop_services_for_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None:
        self.fence_backend_for_upgrade(
            request,
            expected_previous_release_id=binding.active_release_id,
        )
        self.verify_pg_service_for_upgrade(request)
        if scm_query_state(self._runner, request.pg_service_name) != "STOPPED":
            stop_service(self._runner, request.pg_service_name, code="upgrade_pg_stop_failed")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if scm_query_state(self._runner, request.pg_service_name) == "STOPPED":
                read_stopped_cluster(self._runner, layout.pg_bin(request), layout.pgdata(request))
                return
            time.sleep(1)
        raise LifecycleError("upgrade_pg_stop_timeout", "TicketboxPg did not reach STOPPED")

    def create_verified_cold_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        allowed_operation_id: str,
    ) -> PreUpgradeBackup:
        expected_app, expected_program_data = self._expected_roots()
        backup_dir = expected_program_data / "backups"
        reject_reparse_components(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        protect_directory(self._runner, backup_dir, code="upgrade_backup_acl_failed")
        output = backup_dir / f"pre-upgrade-{allowed_operation_id}-{uuid.uuid4().hex[:12]}.tbxcold"
        cold_platform = _HeldLockColdCopyPlatform(
            self._stores,
            self._runner,
            expected_app,
            expected_program_data,
            allowed_operation_id,
            request.target_release_id,
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
        self._verify_cold_backup_restorable(
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
        self,
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
        self._verify_cold_backup_restorable(
            request,
            path,
            expected_sha256,
            binding,
            source_release_id=source_release_id,
            source_schema_revision=source_schema_revision,
        )

    def _verify_cold_backup_restorable(
        self,
        request: InstallRequest,
        archive_path: Path,
        expected_sha256: str,
        binding: InstallationBinding,
        *,
        source_release_id: str,
        source_schema_revision: str,
    ) -> None:
        expected_app, _expected_program_data = self._expected_roots()
        manifest_path = expected_app / "releases" / source_release_id / "release-manifest.json"
        reject_reparse_components(manifest_path)
        manifest_sha = _file_sha256(manifest_path)
        verifier = self._verifier()
        source_binding = replace(
            binding,
            active_release_id=source_release_id,
            release_manifest_sha256=manifest_sha,
        )
        manifest = verifier.verify_release_manifest(source_binding)
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

    def run_offline_migration(
        self,
        request: InstallRequest,
        *,
        source_revision: str,
        target_revision: str,
        expected_restore_epoch: int,
        backup_path: str,
        backup_sha256: str,
    ) -> UpgradeMigrationResult:
        return WindowsAlembicAdapter(self._runner).upgrade_existing_dataset(
            request,
            source_revision=source_revision,
            target_revision=target_revision,
            expected_restore_epoch=expected_restore_epoch,
            backup_path=backup_path,
            backup_sha256=backup_sha256,
        )

    def sync_shared_payload(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None:
        staged_root = self._require_staged_root()
        self._verify_stage_security(request, staged_root)
        publish_acl, verify_acl = self._program_acl_hooks()
        self._verifier().sync_staged_shared_payload(
            request,
            staged_release_root=staged_root,
            allowed_sibling_releases=allowed_sibling_releases,
            publish_acl=publish_acl,
            verify_acl=verify_acl,
        )

    def rebind_removed_connector_state(
        self,
        request: InstallRequest,
        published: InstallationBinding,
    ) -> None:
        machine_root = layout.machine_root(request)
        state_path = machine_root / "connectors" / "cloudflare" / "state.json"
        reject_reparse_components(state_path)
        if not state_path.exists():
            return
        if self._connector_store_factory is not None:
            store = self._connector_store_factory(machine_root, published.backend_service_name)
        else:
            backend_sid = lookup_account_sid("NT SERVICE\\" + published.backend_service_name)
            store = WindowsConnectorFiles(machine_root, backend_sid)
        state = store.read()
        if state is None:
            return
        if (
            state.configured
            or state.enabled
            or state.tunnel_id is not None
            or state.install_id != published.install_id
            or state.dataset_id != published.dataset_id
            or state.expected_restore_epoch != published.expected_restore_epoch
        ):
            raise LifecycleViolation(
                "upgrade_managed_connector_active",
                "connector state is not a removed record for this installation",
            )
        if state.release_manifest_sha256 == published.release_manifest_sha256:
            return
        store.publish(replace(state, release_manifest_sha256=published.release_manifest_sha256))

    def update_start_menu_shortcut(self, request: InstallRequest) -> None:
        if self._shortcut_updater is not None:
            self._shortcut_updater(request)
            return
        update_manager_start_menu_shortcut(request)

    def fence_backend_for_upgrade(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None:
        if not service_exists(self._runner, request.backend_service_name):
            return
        observed = self._observer.observe(request.backend_service_name)
        expected_target = expected_backend_service(request, start_type=SERVICE_DEMAND_START)
        if _matches_service(request.backend_service_name, observed, expected_target):
            self._scm.fence_backend(request)
            return
        previous_request = replace(request, target_release_id=expected_previous_release_id)
        expected_previous = expected_backend_service(previous_request, start_type=SERVICE_DEMAND_START)
        if _matches_service(request.backend_service_name, observed, expected_previous):
            self._scm.fence_backend(previous_request)
            return
        require_service_configuration(
            request.backend_service_name,
            observed,
            expected_previous,
            allowed_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
        )

    def verify_candidate_health(self, request: InstallRequest) -> None:
        self._dataset.wait_for_runtime_mode(request, expected_mode="upgrade_verify_only")
        self._dataset.verify_runtime_mode(request, expected_mode="upgrade_verify_only")

    def verify_normal_health(self, request: InstallRequest) -> None:
        self._dataset.wait_for_runtime_mode(request, expected_mode="normal")
        self._dataset.verify_runtime_mode(request, expected_mode="normal")

    def verify_previous_candidate_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        self._dataset.apply(previous_request, "health")
        self._dataset.verify(previous_request, "health")
        self._dataset.verify_live_authority(
            previous_request,
            expected_restore_epoch=expected_restore_epoch,
        )

    def verify_previous_normal_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        self._dataset.apply(previous_request, "health")
        self._dataset.verify(previous_request, "health")
        self._dataset.verify_live_authority(
            previous_request,
            expected_restore_epoch=expected_restore_epoch,
        )

    def quarantine_failed_upgrade(
        self,
        request: InstallRequest,
        active: UpgradeOperation,
        binding: InstallationBinding,
        *,
        primary_code: str,
        primary_message: str,
    ) -> str:
        expected_app, expected_program_data = self._expected_roots()
        quarantine_root = expected_program_data / "quarantine"
        reject_reparse_components(quarantine_root)
        quarantine_root.mkdir(parents=True, exist_ok=True)
        protect_directory(self._runner, quarantine_root, code="upgrade_quarantine_acl_failed")
        quarantine_dir = quarantine_root / f"upgrade-failed-{active.operation_id[:24]}-{uuid.uuid4().hex[:12]}"
        reject_reparse_components(quarantine_dir)
        quarantine_dir.mkdir(parents=False, exist_ok=False)
        protect_directory(self._runner, quarantine_dir, code="upgrade_quarantine_acl_failed")

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

        self.fence_backend_for_upgrade(request, expected_previous_release_id=active.previous_release_id)
        if service_exists(self._runner, request.backend_service_name):
            delete_service(self._runner, request.backend_service_name, code="rollback_backend_delete_failed")
        if service_exists(self._runner, request.pg_service_name):
            self.verify_pg_service_for_upgrade(request)
            stop_service_and_wait(self._runner, request.pg_service_name, code="rollback_pg_stop_failed")
            delete_service(self._runner, request.pg_service_name, code="rollback_pg_delete_failed")

        failed_release = expected_app / "releases" / active.target_release_id
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
        self,
        request: InstallRequest,
        active: UpgradeOperation,
        binding: InstallationBinding,
        *,
        new_install_id: str,
        rollback_operation_id: str,
        new_health_key: str,
        target_restore_epoch: int,
    ) -> RollbackRestoreResult:
        expected_app, _expected_program_data = self._expected_roots()
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
        prev_manifest = self._verifier().verify_release_manifest(prev_binding_check)
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
        publish_acl, verify_acl = self._program_acl_hooks()
        cold_restore = WindowsColdRestore(self._runner)
        backup_path = Path(active.backup_path)
        stage_parent = expected_app.parent / "Ticketbox-UpgradeStage"
        reject_reparse_components(expected_app.parent)
        reject_reparse_components(stage_parent)
        created_stage_parent = not os.path.lexists(stage_parent)
        stage_parent.mkdir(parents=False, exist_ok=True)
        protect_directory(self._runner, stage_parent, code="rollback_stage_acl_failed")
        sync_temp = stage_parent / f"_rollback_tmp_{uuid.uuid4().hex[:12]}"
        reject_reparse_components(sync_temp)
        sync_temp.mkdir(parents=False, exist_ok=False)
        protect_directory(self._runner, sync_temp, code="rollback_stage_acl_failed")
        with cold_restore.open_source(prev_request, backup_path, active.backup_sha256) as source:
            try:
                source.restore_shared_program_files(
                    expected_app,
                    temp_root=sync_temp,
                    publish_acl=publish_acl,
                    verify_acl=verify_acl,
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
                _publish_and_verify_tree_acls(
                    lifecycle_dir,
                    publish_acl=publish_acl,
                    verify_acl=verify_acl,
                )
            _publish_and_verify_tree_acls(
                expected_app / "releases" / active.previous_release_id,
                publish_acl=publish_acl,
                verify_acl=verify_acl,
            )
            prev_siblings = (
                frozenset({binding.previous_release_id})
                if isinstance(binding.previous_release_id, str) and binding.previous_release_id
                else frozenset()
            )
            self._verifier().verify_installed(
                prev_binding_check,
                allowed_sibling_releases=prev_siblings,
            )
            cold_restore.extract_data(prev_request, source)
            cold_restore.prepare_data(prev_request, source)
            adapters = self._stores._adapters
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

    def rebind_backend_service(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None:
        backend = layout.backend_exe(request)
        if not backend.is_file():
            raise LifecycleError("missing_platform_binary", "target immutable backend is missing")
        if not service_exists(self._runner, request.backend_service_name):
            raise LifecycleError("upgrade_service_missing", "TicketboxBackend service is not registered")
        if scm_query_state(self._runner, request.backend_service_name) != "STOPPED":
            raise LifecycleError(
                "live_scm_mutation_forbidden",
                "upgrade refuses to rebind a running TicketboxBackend service",
            )
        require_service_configuration(
            request.pg_service_name,
            self._observer.observe(request.pg_service_name),
            expected_pg_service(request),
            allowed_start_types=frozenset({SERVICE_AUTO_START}),
        )
        observed = self._observer.observe(request.backend_service_name)
        expected_target = expected_backend_service(request, start_type=SERVICE_DEMAND_START)
        expected_previous = expected_backend_service(
            replace(request, target_release_id=expected_previous_release_id),
            start_type=SERVICE_DEMAND_START,
        )
        already_rebound = _matches_service(request.backend_service_name, observed, expected_target)
        if not already_rebound:
            require_service_configuration(
                request.backend_service_name,
                observed,
                expected_previous,
                allowed_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
            )
            require_ok(
                self._runner.run(
                    [
                        "sc.exe",
                        "config",
                        request.backend_service_name,
                        "binPath=",
                        subprocess.list2cmdline(list(expected_target.argv)),
                    ]
                ),
                code="backend_rebind_failed",
            )
        self._scm._set_identity(request.backend_service_name, start="demand")
        require_ok(
            self._runner.run(
                [
                    "sc.exe",
                    "config",
                    request.backend_service_name,
                    "depend=",
                    request.pg_service_name,
                ]
            ),
            code="backend_depend_failed",
        )
        self._security.configure_backend_runtime_acl(request)
        require_service_configuration(
            request.backend_service_name,
            self._observer.observe(request.backend_service_name),
            expected_target,
            allowed_start_types=frozenset({SERVICE_DEMAND_START}),
        )
        self._security.verify_backend_runtime_authority(request)


def _matches_service(name: str, observed, expected) -> bool:
    try:
        require_service_configuration(
            name,
            observed,
            expected,
            allowed_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
        )
    except LifecycleError:
        return False
    return True


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
