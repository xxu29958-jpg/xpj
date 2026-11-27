"""Platform capabilities for the bounded existing-dataset managed upgrade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ticketbox_lifecycle.schemas import (
    InstallationBinding,
    InstallRequest,
    OwnerPairing,
    UpgradeOperation,
)

MigrationOutcome = Literal["target_committed", "target_observed_after_interruption"]


@dataclass(frozen=True)
class PreUpgradeBackup:
    path: str
    sha256: str
    schema_revision: str


@dataclass(frozen=True)
class UpgradeMigrationResult:
    outcome: MigrationOutcome
    source_revision: str
    target_revision: str
    operation_id: str


@dataclass(frozen=True)
class RollbackRestoreResult:
    previous_request: InstallRequest
    pairing: OwnerPairing
    restored_binding: InstallationBinding
    backup_digest: str


class UpgradePlatform(Protocol):
    def verify_staged_release(
        self,
        request: InstallRequest,
        *,
        require_target_absent: bool = False,
    ) -> InstallRequest: ...

    def materialize_target_release(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None: ...

    def cleanup_uncommitted_target_release(self, request: InstallRequest) -> None: ...

    def read_source_schema_revision(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> str: ...

    def check_backup_disk_space(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None: ...

    def stop_services_for_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None: ...

    def create_verified_cold_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        allowed_operation_id: str,
    ) -> PreUpgradeBackup: ...

    def verify_existing_cold_backup(
        self,
        request: InstallRequest,
        backup_path: str,
        expected_sha256: str,
        binding: InstallationBinding,
        *,
        source_release_id: str,
        source_schema_revision: str,
    ) -> None: ...

    def verify_pg_service_for_upgrade(self, request: InstallRequest) -> None: ...

    def run_offline_migration(
        self,
        request: InstallRequest,
        *,
        source_revision: str,
        target_revision: str,
        expected_restore_epoch: int,
        backup_path: str,
        backup_sha256: str,
    ) -> UpgradeMigrationResult: ...

    def fence_backend_for_upgrade(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None: ...

    def rebind_backend_service(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None: ...

    def sync_shared_payload(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None: ...

    def rebind_removed_connector_state(
        self,
        request: InstallRequest,
        published: InstallationBinding,
    ) -> None: ...

    def update_start_menu_shortcut(self, request: InstallRequest) -> None: ...

    def verify_candidate_health(self, request: InstallRequest) -> None: ...

    def verify_normal_health(self, request: InstallRequest) -> None: ...

    def quarantine_failed_upgrade(
        self,
        request: InstallRequest,
        active: UpgradeOperation,
        binding: InstallationBinding,
        *,
        primary_code: str,
        primary_message: str,
    ) -> str: ...

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
    ) -> RollbackRestoreResult: ...

    def verify_previous_candidate_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None: ...

    def verify_previous_normal_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None: ...
