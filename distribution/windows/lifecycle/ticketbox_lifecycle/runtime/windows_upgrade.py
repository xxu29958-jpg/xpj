"""Windows platform implementation for existing-dataset managed upgrades."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ticketbox_lifecycle.adapters.scm import ScmObserver
from ticketbox_lifecycle.adapters.upgrade import (
    PreUpgradeBackup,
    RollbackRestoreResult,
    UpgradeMigrationResult,
)
from ticketbox_lifecycle.domain.connector import ConnectorStateStore
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
    require_service_configuration,
)
from ticketbox_lifecycle.runtime import layout, windows_upgrade_backup
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_account import lookup_account_sid
from ticketbox_lifecycle.runtime.windows_alembic import WindowsAlembicAdapter
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
from ticketbox_lifecycle.runtime.windows_services import scm_query_state, service_exists
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.runtime.windows_shortcut import update_manager_start_menu_shortcut
from ticketbox_lifecycle.runtime.windows_upgrade_backup import (
    UpgradeBackupContext,
    _file_sha256,
    _HeldLockColdCopyPlatform,
)
from ticketbox_lifecycle.schemas import (
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)

__all__ = ["WindowsUpgradePlatform", "_HeldLockColdCopyPlatform", "_file_sha256"]

_ALEMBIC_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")


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

    def _program_acl_hooks(self):
        publish_acl = getattr(self._security, "publish_installed_program_acl", None)
        verify_acl = getattr(self._security, "verify_installed_program_acl", None)
        return (
            publish_acl if callable(publish_acl) else None,
            verify_acl if callable(verify_acl) else None,
        )

    def _backup_context(self) -> UpgradeBackupContext:
        expected_app, expected_program_data = self._expected_roots()
        publish_acl, verify_acl = self._program_acl_hooks()
        return UpgradeBackupContext(
            stores=self._stores,
            runner=self._runner,
            expected_app=expected_app,
            expected_program_data=expected_program_data,
            verifier=WindowsShipmentVerifier(expected_app, expected_program_data),
            fence_backend=self.fence_backend_for_upgrade,
            verify_pg_service=self.verify_pg_service_for_upgrade,
            publish_acl=publish_acl,
            verify_acl=verify_acl,
            protect_dir_fn=protect_directory,
            archive_creator=create_private_archive,
            cold_restore_cls=WindowsColdRestore,
        )

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

    def check_backup_disk_space(self, request: InstallRequest, binding: InstallationBinding) -> None:
        del request
        windows_upgrade_backup.check_backup_disk_space(self._backup_context(), binding)

    def stop_services_for_backup(self, request: InstallRequest, binding: InstallationBinding) -> None:
        windows_upgrade_backup.stop_services_for_backup(self._backup_context(), request, binding)

    def create_verified_cold_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        allowed_operation_id: str,
    ) -> PreUpgradeBackup:
        return windows_upgrade_backup.create_verified_cold_backup(
            self._backup_context(), request, binding, allowed_operation_id=allowed_operation_id
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
        windows_upgrade_backup.verify_existing_cold_backup(
            self._backup_context(),
            request,
            backup_path,
            expected_sha256,
            binding,
            source_release_id=source_release_id,
            source_schema_revision=source_schema_revision,
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

    def _verify_previous_health(
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

    def verify_previous_candidate_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        self._verify_previous_health(previous_request, expected_restore_epoch=expected_restore_epoch)

    def verify_previous_normal_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        self._verify_previous_health(previous_request, expected_restore_epoch=expected_restore_epoch)

    def quarantine_failed_upgrade(
        self,
        request: InstallRequest,
        active: UpgradeOperation,
        binding: InstallationBinding,
        *,
        primary_code: str,
        primary_message: str,
    ) -> str:
        return windows_upgrade_backup.quarantine_failed_upgrade(
            self._backup_context(),
            request,
            active,
            binding,
            primary_code=primary_code,
            primary_message=primary_message,
        )

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
        return windows_upgrade_backup.restore_previous_from_backup(
            self._backup_context(),
            request,
            active,
            binding,
            new_install_id=new_install_id,
            rollback_operation_id=rollback_operation_id,
            new_health_key=new_health_key,
            target_restore_epoch=target_restore_epoch,
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
            bin_path = subprocess.list2cmdline(list(expected_target.argv))
            require_ok(
                self._runner.run(["sc.exe", "config", request.backend_service_name, "binPath=", bin_path]),
                code="backend_rebind_failed",
            )
        self._scm._set_identity(request.backend_service_name, start="demand")
        require_ok(
            self._runner.run(["sc.exe", "config", request.backend_service_name, "depend=", request.pg_service_name]),
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
