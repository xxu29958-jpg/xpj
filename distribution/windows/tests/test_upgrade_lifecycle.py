from __future__ import annotations

import hashlib
import io
import json
import shutil
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import MemoryMutex, MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.adapters.upgrade import (
    PreUpgradeBackup,
    RollbackRestoreResult,
    UpgradeMigrationResult,
)
from ticketbox_lifecycle.cli import main as lifecycle_main
from ticketbox_lifecycle.domain.binding import binding_from_request, upgrade_binding
from ticketbox_lifecycle.domain.cold_copy import create_cold_copy_locked
from ticketbox_lifecycle.domain.upgrade import rollback_upgrade, upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import sign_challenge, sign_runtime_mode
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
)
from ticketbox_lifecycle.runtime import cold_archive
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores, _managed_connector_present
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_shipment import (
    WindowsShipmentVerifier,
    expected_upgrade_stage_root,
)
from ticketbox_lifecycle.runtime.windows_shortcut import MANAGER_APP_ID, read_shortcut, update_manager_start_menu_shortcut
from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REQUEST_SCHEMA,
    ActiveOperation,
    InstallationBinding,
    InstallRequest,
    OwnerPairing,
    UpgradeOperation,
)
from ticketbox_lifecycle.upgrade_cli import _read_durable_failure_status

INSTALL_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "22222222-2222-4222-8222-222222222222"
OLD_KEY = "a" * 64
OLD_MANIFEST_SHA = "b" * 64


def _make_upgrade_fixture(
    tmp_path: Path,
    *,
    old_release: str = "1.2.1",
    new_release: str = "1.3.0",
    source_revision: str = "20261029_0002",
    target_revision: str = "20261101_0001",
    restore_epoch: int = 0,
):
    app_dir = tmp_path / "app"
    stage_manifest = tmp_path / "stage" / new_release / "release-manifest.json"
    stage_manifest.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({
        "max_schema_revision": target_revision,
        "product_version": new_release,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
    }).encode("utf-8")
    stage_manifest.write_bytes(body)
    if old_release == new_release:
        installed_manifest = app_dir / "releases" / old_release / "release-manifest.json"
        installed_manifest.parent.mkdir(parents=True, exist_ok=True)
        installed_manifest.write_bytes(body)
    manifest_sha = hashlib.sha256(body).hexdigest()
    operation_id = f"upgrade-{manifest_sha}"
    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=operation_id,
        request_hash="pending",
        target_release_id=new_release,
        app_dir=str(app_dir),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=manifest_sha,
    )
    adapters = RecordingAdapterBundle()
    adapters.security._done.add("acl")
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    stores.pgdata_present = True
    stores.pg_service_present = True
    stores.backend_service_present = True
    stores._binding = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=restore_epoch,
        data_root=request.data_root,
        active_release_id=old_release,
        previous_release_id=None,
        release_manifest_sha256=OLD_MANIFEST_SHA,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )
    return request, stores, adapters, source_revision, target_revision


class FakeUpgradePlatform:
    def __init__(
        self,
        *,
        stores: MemoryStores,
        source_revision: str,
        target_revision: str,
        fail_at: str | None = None,
        forged_target: bool = False,
    ) -> None:
        self.stores = stores
        self.source_revision = source_revision
        self.target_revision = target_revision
        self.fail_at = fail_at
        self.forged_target = forged_target
        self.live_revision = target_revision if forged_target else source_revision
        self.attestation: dict[str, object] | None = None
        self.events: list[str] = []
        self.backup_creates = 0
        self.backup_verifies = 0
        self.migration_calls = 0
        self.rebind_calls = 0
        self.sync_calls = 0
        self.materialize_calls = 0
        self.cleanup_calls = 0
        self.connector_rebind_calls = 0
        self.shortcut_update_calls = 0
        self.pg_verify_calls = 0
        self.last_backup_path = ""
        self.last_backup_sha256 = ""
        self.bound_release = stores._binding.active_release_id if stores._binding else ""
        self.running_mode: str | None = None
        self.health_modes_verified: list[str] = []
        self.stale_mode_on_commit: str | None = None

        orig_start = stores.adapters.scm.apply

        def tracking_scm_apply(req: InstallRequest, step: str) -> str:
            res = orig_start(req, step)
            if step == "start_services":
                active = self.stores.read_active()
                if self.stale_mode_on_commit is not None and active is not None and active.phase == "committed":
                    self.running_mode = self.stale_mode_on_commit
                elif active is not None and active.kind == "upgrade" and active.phase != "committed":
                    self.running_mode = "upgrade_verify_only"
                else:
                    self.running_mode = "normal"
            return res

        orig_fence = stores.adapters.scm.fence_backend

        def tracking_fence(req: InstallRequest) -> None:
            orig_fence(req)
            self.running_mode = None

        stores.adapters.scm.apply = tracking_scm_apply  # type: ignore[method-assign]
        stores.adapters.scm.fence_backend = tracking_fence  # type: ignore[method-assign]

    def verify_staged_release(
        self,
        request: InstallRequest,
        *,
        require_target_absent: bool = False,
    ) -> InstallRequest:
        self.events.append("verify_staged")
        target_dir = Path(request.app_dir) / "releases" / request.target_release_id
        if require_target_absent and target_dir.exists():
            raise LifecycleViolation("upgrade_target_release_exists", "pre-existing target release dir")
        stage_manifest = Path(request.app_dir).parent / "stage" / request.target_release_id / "release-manifest.json"
        if stage_manifest.is_file():
            raw = stage_manifest.read_bytes()
            if hashlib.sha256(raw).hexdigest() != request.release_manifest_sha256:
                raise LifecycleViolation("manifest_mismatch", "staged manifest mismatch")
            payload = json.loads(raw.decode("utf-8"))
            return replace(
                request,
                schema_revision=str(payload["max_schema_revision"]),
                semantic_revision=str(payload["min_semantic_revision"]),
            )
        return self.stores.bind_and_verify(request)

    def materialize_target_release(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None:
        del allowed_sibling_releases
        self.materialize_calls += 1
        self.events.append("materialize_target")
        stage_manifest = Path(request.app_dir).parent / "stage" / request.target_release_id / "release-manifest.json"
        if stage_manifest.is_file():
            target_manifest = Path(request.app_dir) / "releases" / request.target_release_id / "release-manifest.json"
            target_manifest.parent.mkdir(parents=True, exist_ok=True)
            target_manifest.write_bytes(stage_manifest.read_bytes())

    def cleanup_uncommitted_target_release(self, request: InstallRequest) -> None:
        self.cleanup_calls += 1
        self.events.append("cleanup_target")
        target_dir = Path(request.app_dir) / "releases" / request.target_release_id
        if target_dir.exists():
            shutil.rmtree(target_dir)

    def read_source_schema_revision(self, request: InstallRequest, binding: InstallationBinding) -> str:
        del request, binding
        self.events.append("read_source_revision")
        return self.source_revision

    def check_backup_disk_space(self, request: InstallRequest, binding: InstallationBinding) -> None:
        del request, binding
        self.events.append("check_backup_disk_space")
        if self.fail_at == "backup_disk_space":
            raise LifecycleError("cold_space_insufficient", "insufficient disk space before backup")

    def stop_services_for_backup(self, request: InstallRequest, binding: InstallationBinding) -> None:
        del request, binding
        assert self.stores.mutex._lock.locked()
        self.running_mode = None
        self.events.append("stop_services")

    def create_verified_cold_backup(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        allowed_operation_id: str,
    ) -> PreUpgradeBackup:
        assert self.stores.mutex._lock.locked()
        active = self.stores.read_active()
        assert active is not None and active.operation_id == allowed_operation_id
        self.backup_creates += 1
        self.events.append("cold_backup")
        if self.fail_at == "cold_backup":
            raise LifecycleError("cold_corrupt", "injected backup readback failure")
        backup_file = Path(request.program_data_root) / "backups" / f"{allowed_operation_id}.tbxcold"
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(b"verified-pre-upgrade-backup-fixture")
        return PreUpgradeBackup(
            path=str(backup_file),
            sha256="f" * 64,
            schema_revision=self.source_revision,
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
        del request
        assert backup_path and expected_sha256 == "f" * 64 and binding.dataset_id == DATASET_ID
        assert source_release_id and source_schema_revision == self.source_revision
        self.backup_verifies += 1
        self.events.append("verify_existing_backup")

    def verify_pg_service_for_upgrade(self, request: InstallRequest) -> None:
        del request
        self.pg_verify_calls += 1
        if self.fail_at == "pg_start_type":
            raise LifecycleViolation("scm_configuration_mismatch", "TicketboxPg must be AUTO_START")

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
        assert self.stores.mutex._lock.locked()
        assert backup_path and backup_sha256
        self.migration_calls += 1
        self.last_backup_path = backup_path
        self.last_backup_sha256 = backup_sha256
        self.events.append(f"migrate:{source_revision}->{target_revision}")
        if self.fail_at == "migrate_before_commit":
            raise LifecycleError("upgrade_migration_failed", "injected pre-commit SQL failure")
        expected = {
            "operation_id": request.operation_id,
            "dataset_id": request.dataset_id,
            "restore_epoch": expected_restore_epoch,
            "source_revision": source_revision,
            "target_revision": target_revision,
            "backup_archive_sha256": backup_sha256,
        }
        if source_revision == target_revision:
            if self.attestation == expected:
                outcome = "target_observed_after_interruption"
            else:
                self.attestation = expected
                outcome = "target_committed"
        elif self.live_revision == target_revision:
            if self.attestation != expected:
                raise LifecycleError(
                    "upgrade_migration_failed",
                    "target revision lacks matching managed upgrade attestation",
                )
            outcome = "target_observed_after_interruption"
        else:
            self.live_revision = target_revision
            self.attestation = expected
            outcome = "target_committed"
        if self.fail_at == "migrate_after_commit_before_stdout":
            raise LifecycleError("upgrade_migration_failed", "helper crashed after PG commit before stdout")
        return UpgradeMigrationResult(
            outcome=outcome,  # type: ignore[arg-type]
            source_revision=source_revision,
            target_revision=target_revision,
            operation_id=request.operation_id,
        )

    def fence_backend_for_upgrade(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None:
        if self.bound_release not in {expected_previous_release_id, request.target_release_id}:
            raise LifecycleViolation("scm_configuration_mismatch", "foreign SCM binding refused")
        self.stores.adapters.scm.fence_backend(replace(request, target_release_id=self.bound_release))

    def rebind_backend_service(
        self,
        request: InstallRequest,
        *,
        expected_previous_release_id: str,
    ) -> None:
        assert self.stores.mutex._lock.locked()
        assert expected_previous_release_id
        self.rebind_calls += 1
        self.events.append("rebind_scm")
        if self.fail_at == "rebind_scm":
            raise LifecycleError("backend_rebind_failed", "injected SCM rebind failure")
        self.bound_release = request.target_release_id
        if self.fail_at == "rebind_scm_after_config":
            raise LifecycleError("backend_rebind_failed", "crash after SCM binPath update")

    def sync_shared_payload(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> None:
        del request, allowed_sibling_releases
        assert self.stores.mutex._lock.locked()
        self.sync_calls += 1
        self.events.append("sync_shared")

    def rebind_removed_connector_state(
        self,
        request: InstallRequest,
        published: InstallationBinding,
    ) -> None:
        del request, published
        assert self.stores.mutex._lock.locked()
        self.connector_rebind_calls += 1
        self.events.append("rebind_connector")

    def update_start_menu_shortcut(self, request: InstallRequest) -> None:
        del request
        assert self.stores.mutex._lock.locked()
        self.shortcut_update_calls += 1
        self.events.append("update_shortcut")

    def verify_candidate_health(self, request: InstallRequest) -> None:
        self.stores.adapters.dataset.apply(request, "health")
        self.stores.adapters.dataset.verify(request, "health")
        if self.running_mode != "upgrade_verify_only":
            raise LifecycleError("health_mode_mismatch", f"expected upgrade_verify_only, got {self.running_mode}")
        self.health_modes_verified.append("upgrade_verify_only")

    def verify_normal_health(self, request: InstallRequest) -> None:
        self.stores.adapters.dataset.apply(request, "health")
        self.stores.adapters.dataset.verify(request, "health")
        if self.running_mode != "normal":
            raise LifecycleError("health_mode_mismatch", f"expected normal, got {self.running_mode}")
        self.health_modes_verified.append("normal")

    def quarantine_failed_upgrade(
        self,
        request: InstallRequest,
        active: UpgradeOperation,
        binding: InstallationBinding,
        *,
        primary_code: str,
        primary_message: str,
    ) -> str:
        assert self.stores.mutex._lock.locked()
        self.events.append("quarantine_failed_upgrade")
        if self.fail_at == "quarantine":
            raise LifecycleError("quarantine_failed", "injected quarantine failure")
        quarantine_dir = Path(request.program_data_root) / "quarantine" / f"failed-{active.operation_id[:12]}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        (quarantine_dir / "record.json").write_text(
            json.dumps({"primary_code": primary_code, "primary_message": primary_message}),
            encoding="utf-8",
        )
        self.quarantined_path = str(quarantine_dir)
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
        assert self.stores.mutex._lock.locked()
        self.events.append("restore_previous_from_backup")
        if self.fail_at == "rollback_restore":
            raise LifecycleError("rollback_extract_failed", "injected rollback extract failure")
        prev_req = replace(
            request,
            command="restore",
            operation_id=rollback_operation_id,
            target_release_id=active.previous_release_id,
            release_manifest_sha256=active.previous_release_manifest_sha256,
            install_id=new_install_id,
            dataset_id=binding.dataset_id,
            schema_revision=active.source_schema_revision,
            health_attestation_key=new_health_key,
        )
        self.live_revision = active.source_schema_revision
        self.bound_release = active.previous_release_id
        restored_binding = replace(
            binding_from_request(prev_req),
            expected_restore_epoch=target_restore_epoch,
            previous_release_id=None,
        )
        return RollbackRestoreResult(
            previous_request=prev_req,
            pairing=OwnerPairing(
                pairing_code="87654321",
                pairing_expires_at="2026-11-27T12:00:00Z",
                revoked_credentials_summary={"auth_tokens": 1, "devices": 1, "pairing_codes": 1, "upload_links": 0, "invitations": 0},
            ),
            restored_binding=restored_binding,
            backup_digest=active.backup_sha256,
        )

    def verify_previous_candidate_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        assert self.stores.mutex._lock.locked()
        assert expected_restore_epoch >= 1
        self.events.append("verify_previous_candidate_health")
        if self.fail_at == "previous_candidate_health":
            raise LifecycleError("previous_health_failed", "injected previous candidate health failure")
        self.health_modes_verified.append("restore_verify_only")

    def verify_previous_normal_health(
        self,
        previous_request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        assert self.stores.mutex._lock.locked()
        assert expected_restore_epoch >= 1
        self.events.append("verify_previous_normal_health")
        self.health_modes_verified.append("previous_normal")


def test_cross_revision_upgrade_preserves_identity_and_publishes_after_candidate_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(
        tmp_path,
        source_revision="20261029_0002",
        target_revision="20261101_0001",
        restore_epoch=4,
    )
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    health_phases: list[tuple[str, str]] = []
    orig_health = adapters.dataset.apply

    def record_health(req: InstallRequest, step: str) -> str:
        active = stores.read_active()
        binding = stores.read()
        assert active is not None and binding is not None
        health_phases.append((active.phase, binding.active_release_id))
        return orig_health(req, step)

    monkeypatch.setattr(adapters.dataset, "apply", record_health)

    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is True
    assert result.command == "upgrade"
    assert result.phase == "committed"
    assert result.code == "upgraded"
    assert result.installation_published is True
    assert result.pairing_code == ""
    assert result.pairing_expires_at == ""
    assert stores.mutex.acquired == 1
    assert not stores.mutex._lock.locked()
    assert health_phases == [("data_ready", "1.2.1"), ("committed", "1.3.0"), ("committed", "1.3.0")]
    binding = stores.read()
    assert binding is not None
    assert binding.install_id == INSTALL_ID
    assert binding.dataset_id == DATASET_ID
    assert binding.expected_restore_epoch == 4
    assert binding.active_release_id == "1.3.0"
    assert binding.previous_release_id == "1.2.1"
    assert binding.release_manifest_sha256 == request.release_manifest_sha256
    assert binding.health_attestation_key != OLD_KEY
    assert stores.read_active() is None
    assert len(stores.history) == 1
    assert isinstance(stores.history[0], UpgradeOperation)
    assert stores.history[0].kind == "upgrade"
    assert stores.history[0].previous_release_id == "1.2.1"
    assert adapters.scm.autostart_enabled is True
    assert adapters.scm.fence_calls == 2
    assert platform.health_modes_verified == ["upgrade_verify_only", "normal", "normal"]
    assert platform.backup_creates == 1
    assert platform.migration_calls == 1
    assert platform.connector_rebind_calls == 1
    assert platform.shortcut_update_calls == 1


def test_same_schema_upgrade_still_executes_offline_migrator_and_attestation(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(
        tmp_path,
        source_revision="20261101_0001",
        target_revision="20261101_0001",
    )
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)

    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is True
    assert platform.migration_calls == 1
    assert platform.attestation == {
        "operation_id": request.operation_id,
        "dataset_id": DATASET_ID,
        "restore_epoch": 0,
        "source_revision": "20261101_0001",
        "target_revision": "20261101_0001",
        "backup_archive_sha256": "f" * 64,
    }
    assert stores.read().active_release_id == "1.3.0"
    assert stores.read().previous_release_id == "1.2.1"
    assert adapters.scm.autostart_enabled is True


def test_sql_pre_commit_interruption_recovers_without_retaking_cold_backup(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="migrate_before_commit",
    )

    first = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert first.ok is False
    assert first.phase == "failed_recoverable"
    assert first.installation_published is False
    assert stores.read().active_release_id == "1.2.1"
    assert stores.read().previous_release_id is None
    assert adapters.scm.backend_fenced is True
    assert adapters.scm.autostart_enabled is False
    active = stores.read_active()
    assert isinstance(active, UpgradeOperation)
    assert active.backup_path and active.backup_sha256 == "f" * 64
    assert active.no_return_point is True
    assert platform.live_revision == src_rev

    platform.fail_at = None
    second = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert second.ok is True
    assert second.phase == "committed"
    assert platform.backup_creates == 1
    assert platform.backup_verifies == 1
    assert platform.migration_calls == 2
    assert stores.read().active_release_id == "1.3.0"
    assert stores.read().previous_release_id == "1.2.1"
    assert stores.read_active() is None
    assert adapters.scm.autostart_enabled is True


def test_sql_post_commit_pre_publish_interruption_continues_with_same_attestation(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="rebind_scm",
    )

    first = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert first.ok is False
    assert first.phase == "failed_recoverable"
    assert first.installation_published is False
    assert platform.live_revision == tgt_rev
    assert stores.read().active_release_id == "1.2.1"
    active = stores.read_active()
    assert isinstance(active, UpgradeOperation)
    assert active.no_return_point is True
    assert active.completed_step == "alembic"

    platform.fail_at = None
    second = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert second.ok is True
    assert second.phase == "committed"
    assert platform.backup_creates == 1
    assert platform.backup_verifies == 1
    assert platform.migration_calls == 2
    assert stores.read().active_release_id == "1.3.0"
    assert stores.read().previous_release_id == "1.2.1"
    assert stores.read().install_id == INSTALL_ID
    assert stores.read().dataset_id == DATASET_ID
    assert stores.read_active() is None


def test_forged_target_revision_without_attestation_is_rejected_and_fenced(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        forged_target=True,
    )

    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is False
    assert result.code == "upgrade_migration_failed"
    assert result.phase == "failed_recoverable"
    assert result.installation_published is False
    assert stores.read().active_release_id == "1.2.1"
    assert stores.read().previous_release_id is None
    assert adapters.scm.backend_fenced is True
    assert adapters.scm.autostart_enabled is False
    assert not stores.history


def test_candidate_health_failure_fences_candidate_and_preserves_old_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    fenced_releases: list[str] = []
    orig_fence = adapters.scm.fence_backend

    def record_fence(req: InstallRequest) -> None:
        fenced_releases.append(req.target_release_id)
        orig_fence(req)

    monkeypatch.setattr(adapters.scm, "fence_backend", record_fence)
    adapters.dataset.fail_on = "health"

    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is False
    assert result.phase == "failed_recoverable"
    assert result.installation_published is False
    assert fenced_releases == ["1.3.0"]
    assert adapters.scm.backend_fenced is True
    assert adapters.scm.autostart_enabled is False
    assert stores.read().active_release_id == "1.2.1"
    assert stores.read().previous_release_id is None
    assert not stores.history


def test_upgrade_rejects_downgrade_and_same_release_and_missing_binding(tmp_path: Path) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(
        tmp_path,
        old_release="1.3.0",
        new_release="1.2.1",
    )
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    with pytest.raises(LifecycleViolation, match="downgrade"):
        upgrade(stores.as_lifecycle_stores(), request, platform)

    request_same, stores_same, _a2, s2, t2 = _make_upgrade_fixture(
        tmp_path / "same",
        old_release="1.3.0",
        new_release="1.3.0",
    )
    with pytest.raises(LifecycleViolation, match="already running"):
        upgrade(
            stores_same.as_lifecycle_stores(),
            request_same,
            FakeUpgradePlatform(stores=stores_same, source_revision=s2, target_revision=t2),
        )

    request_none, stores_none, _a3, s3, t3 = _make_upgrade_fixture(tmp_path / "none")
    stores_none._binding = None
    with pytest.raises(LifecycleViolation, match="existing verified installation.json"):
        upgrade(
            stores_none.as_lifecycle_stores(),
            request_none,
            FakeUpgradePlatform(stores=stores_none, source_revision=s3, target_revision=t3),
        )


def test_cold_installation_allowed_operation_id_and_locked_cold_copy_no_reentry(tmp_path: Path) -> None:
    pgdata = tmp_path / "data" / "pgdata"
    (pgdata / "global").mkdir(parents=True)
    (pgdata / "PG_VERSION").write_text("17\n", encoding="ascii")
    control = pgdata / "global" / "pg_control"
    control.write_bytes(b"control-bytes")
    pg_bin = tmp_path / "app" / "postgresql" / "bin"
    pg_bin.mkdir(parents=True)

    binding = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=0,
        data_root=str(tmp_path / "data"),
        active_release_id="1.2.1",
        previous_release_id=None,
        release_manifest_sha256=OLD_MANIFEST_SHA,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )
    req = replace(
        make_install_request(tmp_path),
        app_dir=str(tmp_path / "app"),
        data_root=str(tmp_path / "data"),
        target_release_id="1.2.1",
    )
    op_id = "upgrade-" + ("c" * 64)
    upgrade_op = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id=op_id,
        kind="upgrade",
        request_hash="d" * 64,
        target_release_id="1.3.0",
        data_root=binding.data_root,
        release_manifest_sha256="c" * 64,
        backend_port=8000,
        phase="prepared",
        no_return_point=False,
        completed_step="stop_services",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="e" * 64,
        expected_restore_epoch=0,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256=binding.release_manifest_sha256,
        source_schema_revision="20261029_0002",
    )

    class StoppedRunner:
        def run(self, argv, **_kwargs):
            cmd = Path(str(argv[0])).name.lower()
            if cmd == "sc.exe":
                return CompletedCommand(tuple(argv), 0, "STATE : 1 STOPPED\n", "")
            return CompletedCommand(
                tuple(argv),
                0,
                "Database cluster state: shut down\nDatabase system identifier: 123456789\n",
                "",
            )

    class FakeStores:
        def __init__(self, active):
            self._active = active

        def read_active(self):
            return self._active

        def read(self):
            return binding

    control_sha = hashlib.sha256(control.read_bytes()).hexdigest()
    allowed_source = ColdInstallation(
        FakeStores(upgrade_op),  # type: ignore[arg-type]
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=op_id,
    )
    allowed_source.require_stopped()

    disallowed_other = ColdInstallation(
        FakeStores(replace(upgrade_op, operation_id="upgrade-" + ("9" * 64))),  # type: ignore[arg-type]
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=op_id,
    )
    with pytest.raises(LifecycleError, match="changed or is busy"):
        disallowed_other.require_stopped()

    install_op = ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id=op_id,
        kind="install",
        request_hash="d" * 64,
        target_release_id="1.3.0",
        data_root=binding.data_root,
        release_manifest_sha256="c" * 64,
        backend_port=8000,
        phase="prepared",
        no_return_point=False,
        completed_step=None,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="e" * 64,
    )
    disallowed_kind = ColdInstallation(
        FakeStores(install_op),  # type: ignore[arg-type]
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=op_id,
    )
    with pytest.raises(LifecycleError, match="changed or is busy"):
        disallowed_kind.require_stopped()

    disallowed_default = ColdInstallation(
        FakeStores(upgrade_op),  # type: ignore[arg-type]
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=None,
    )
    with pytest.raises(LifecycleError, match="changed or is busy"):
        disallowed_default.require_stopped()

    mutex = MemoryMutex()
    buf = io.BytesIO()

    @contextmanager
    def open_buf(_output):
        yield buf

    locked_platform = SimpleNamespace(
        mutex=mutex,
        read_source=lambda: allowed_source,
        create_archive=open_buf,
        write_archive=lambda target, _source: (target.write(b"ok"), {"ok": True})[1],
        verify_archive=lambda _target: {"ok": True},
    )
    assert create_cold_copy_locked(tmp_path / "copy.tbxcold", locked_platform) == {"ok": True}
    assert mutex.acquired == 0


def test_shipment_verifier_allows_sibling_previous_release_during_upgrade(tmp_path: Path) -> None:
    app = tmp_path / "Ticketbox"
    old_release = app / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe"
    new_backend = app / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe"
    postgres = app / "postgresql" / "bin" / "postgres.exe"
    for path, content in (
        (old_release, b"old-backend"),
        (new_backend, b"new-backend"),
        (postgres, b"postgres"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def rec(rel: str) -> dict[str, object]:
        data = (app / Path(rel)).read_bytes()
        return {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.3.0",
        "product_version": "1.3.0",
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                rec("releases/1.3.0/backend/ticketbox-backend.exe"),
                rec("postgresql/bin/postgres.exe"),
            ],
        },
    }
    manifest_path = app / "releases" / "1.3.0" / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{digest}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=digest,
    )
    verifier = WindowsShipmentVerifier(app, tmp_path / "programdata")
    bound = verifier.bind_and_verify(request, allowed_sibling_releases=frozenset({"1.2.1"}))
    assert bound.schema_revision == "20261101_0001"
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        verifier.bind_and_verify(request)
    upgraded_binding = SimpleNamespace(
        active_release_id="1.3.0",
        previous_release_id="1.2.1",
        release_manifest_sha256=digest,
    )
    assert verifier.verify_installed(upgraded_binding)["release_id"] == "1.3.0"

    unknown_sibling = app / "releases" / "9.9.9" / "backend" / "evil.exe"
    unknown_sibling.parent.mkdir(parents=True, exist_ok=True)
    unknown_sibling.write_bytes(b"hostile-sibling")
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        verifier.bind_and_verify(request, allowed_sibling_releases=frozenset({"1.2.1"}))
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        verifier.verify_installed(upgraded_binding)
    unknown_sibling.unlink()
    unknown_sibling.parent.rmdir()
    (app / "releases" / "9.9.9").rmdir()

    (app / "unexpected.dll").write_bytes(b"hostile")
    with pytest.raises(LifecycleViolation, match="unexpected files"):
        verifier.bind_and_verify(request, allowed_sibling_releases=frozenset({"1.2.1"}))


def test_filesystem_stores_persists_upgrade_operation_and_rejects_bad_fields(tmp_path: Path) -> None:
    class NoopSecurity:
        def verify_machine_json(self, *_args):
            pass

        def protect_machine_json(self, *_args):
            pass

    stores = FilesystemStores(
        tmp_path / "machine",
        "TicketboxBackend",
        SimpleNamespace(security=NoopSecurity()),
        ThreadMutex(),
    )
    operation = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id="upgrade-" + ("a" * 64),
        kind="upgrade",
        request_hash="b" * 64,
        target_release_id="1.3.0",
        data_root=r"C:\ProgramData\Ticketbox\data",
        release_manifest_sha256="a" * 64,
        backend_port=8000,
        phase="data_ready",
        no_return_point=True,
        completed_step="scm",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="c" * 64,
        expected_restore_epoch=2,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256="e" * 64,
        source_schema_revision="20261029_0002",
        backup_path=r"C:\ProgramData\Ticketbox\backups\pre.tbxcold",
        backup_sha256="d" * 64,
    )
    stores.publish_active(operation)
    assert stores.read_active() == operation
    committed = replace(operation, phase="committed", completed_step="health")
    stores.archive_committed(committed)
    assert stores.read_active() is None
    assert stores.read_committed(operation.operation_id) == committed

    bad = asdict(operation)
    bad["previous_release_id"] = "1.3.0"
    with pytest.raises(LifecycleError, match="previous_release_id"):
        stores._operation_from_payload(bad)


def test_windows_upgrade_platform_migrator_and_rebind_contracts(tmp_path: Path) -> None:
    request = replace(
        make_install_request(tmp_path),
        command="upgrade",
        operation_id="upgrade-" + ("a" * 64),
        target_release_id="1.3.0",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
    )
    backend_dir = Path(request.app_dir) / "releases" / "1.3.0" / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "ticketbox-database-maintenance.exe").write_bytes(b"MZ")
    (backend_dir / "ticketbox-backend.exe").write_bytes(b"MZ")

    prev_cfg = expected_backend_service(
        replace(request, target_release_id="1.2.1"),
        start_type=SERVICE_AUTO_START,
    )
    next_cfg = expected_backend_service(request, start_type=SERVICE_DEMAND_START)
    pg_cfg = expected_pg_service(request)
    state = {"backend_cfg": prev_cfg}

    class FakeObserver:
        def observe(self, name: str):
            return pg_cfg if name == "TicketboxPg" else state["backend_cfg"]

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, argv, **_kwargs):
            parts = tuple(str(x) for x in argv)
            self.calls.append(parts)
            if parts[0].endswith("ticketbox-database-maintenance.exe"):
                return CompletedCommand(
                    parts,
                    0,
                    json.dumps({
                        "schema": "ticketbox-existing-dataset-upgrade-result-v1",
                        "operation_id": request.operation_id,
                        "dataset_id": DATASET_ID,
                        "installation_id": INSTALL_ID,
                        "restore_epoch": 2,
                        "source_revision": "20261029_0002",
                        "target_revision": "20261101_0001",
                        "alembic_revision": "20261101_0001",
                        "backup_archive_sha256": "e" * 64,
                        "result": "target_committed",
                    }),
                    "",
                )
            if parts[:2] == ("sc.exe", "query"):
                return CompletedCommand(parts, 0, "STATE : 1 STOPPED\n", "")
            if parts[:2] == ("sc.exe", "config") and "binPath=" in parts:
                state["backend_cfg"] = next_cfg
            return CompletedCommand(parts, 0, "", "")

    class FakeSecurity:
        def configure_backend_runtime_acl(self, _req):
            pass

        def verify_backend_runtime_authority(self, _req):
            pass

    fenced_releases: list[str] = []

    class FakeScm:
        def _set_identity(self, *_args, **_kwargs):
            pass

        def fence_backend(self, req: InstallRequest):
            fenced_releases.append(req.target_release_id)

    runner = FakeRunner()
    platform = WindowsUpgradePlatform(
        SimpleNamespace(_mutex=ThreadMutex()),  # type: ignore[arg-type]
        runner,
        FakeSecurity(),  # type: ignore[arg-type]
        FakeScm(),  # type: ignore[arg-type]
        FakeObserver(),  # type: ignore[arg-type]
        expected_app_dir=Path(request.app_dir),
        expected_program_data_root=Path(request.program_data_root),
    )
    backup_file = str(tmp_path / "pre-upgrade.tbxcold")
    migration = platform.run_offline_migration(
        request,
        source_revision="20261029_0002",
        target_revision="20261101_0001",
        expected_restore_epoch=2,
        backup_path=backup_file,
        backup_sha256="e" * 64,
    )
    assert migration.outcome == "target_committed"
    helper_call = runner.calls[0]
    assert "--upgrade-existing-dataset" in helper_call
    assert "--expected-restore-epoch" in helper_call
    assert "--backup-archive" in helper_call
    assert "--backup-archive-sha256" in helper_call
    assert "e" * 64 in helper_call

    platform.fence_backend_for_upgrade(request, expected_previous_release_id="1.2.1")
    platform.rebind_backend_service(request, expected_previous_release_id="1.2.1")
    platform.fence_backend_for_upgrade(request, expected_previous_release_id="1.2.1")
    assert fenced_releases == ["1.2.1", "1.3.0"]
    rebind_call = next(c for c in runner.calls if "binPath=" in c)
    assert "releases\\1.3.0\\backend\\ticketbox-backend.exe" in rebind_call[-1] or "releases/1.3.0/backend/ticketbox-backend.exe" in rebind_call[-1]

    state["backend_cfg"] = expected_backend_service(
        replace(request, target_release_id="9.9.9"),
        start_type=SERVICE_DEMAND_START,
    )
    with pytest.raises(LifecycleError):
        platform.fence_backend_for_upgrade(request, expected_previous_release_id="1.2.1")


def test_upgrade_cli_reports_structured_failure_on_bad_schema(tmp_path: Path, monkeypatch) -> None:
    import ctypes

    req_path = tmp_path / "req.json"
    res_path = tmp_path / "res.json"
    req_path.write_text('{"schema":"bad","operation_id":"op-1"}\n', encoding="utf-8")
    monkeypatch.setattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 1, raising=False)
    code = lifecycle_main(["upgrade", "--request", str(req_path), "--result", str(res_path)])
    assert code == 2
    payload = json.loads(res_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["command"] == "upgrade"
    assert payload["code"] == "bad_request_schema"


def _build_physical_installation(
    tmp_path: Path,
    *,
    release_id: str,
    schema_revision: str,
    lifecycle_bytes: bytes = b"lifecycle-v1",
    previous_release_id: str | None = None,
):
    app = tmp_path / "Ticketbox"
    program_data = tmp_path / "ProgramData" / "Ticketbox"
    data = program_data / "data"
    machine = program_data / "machine"
    for rel, content in (
        (f"releases/{release_id}/backend/ticketbox-backend.exe", f"backend-{release_id}".encode()),
        (f"releases/{release_id}/manager/ticketbox-manager.exe", f"manager-{release_id}".encode()),
        (f"releases/{release_id}/lifecycle/TicketboxLifecycle.exe", lifecycle_bytes),
        ("postgresql/bin/postgres.exe", b"trusted-pg-17"),
        ("bin/shawl.exe", b"shawl-bin"),
        ("bin/vc_redist.x64.exe", b"vcredist-v1"),
        ("bin/lifecycle/TicketboxLifecycle.exe", lifecycle_bytes),
        ("ticketbox.ico", b"ico-v1"),
    ):
        path = app / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def rec(rel: str) -> dict[str, object]:
        raw = (app / Path(rel)).read_bytes()
        return {"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": schema_revision,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                rec(f"releases/{release_id}/backend/ticketbox-backend.exe"),
                rec(f"releases/{release_id}/manager/ticketbox-manager.exe"),
                rec(f"releases/{release_id}/lifecycle/TicketboxLifecycle.exe"),
                rec("postgresql/bin/postgres.exe"),
                rec("bin/shawl.exe"),
                rec("bin/vc_redist.x64.exe"),
                rec("bin/lifecycle/TicketboxLifecycle.exe"),
                rec("ticketbox.ico"),
            ],
        },
    }
    manifest_path = app / "releases" / release_id / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    (data / "pgdata" / "global").mkdir(parents=True, exist_ok=True)
    (data / "pgdata" / "PG_VERSION").write_text("17\n", encoding="ascii")
    (data / "pgdata" / "global" / "pg_control").write_bytes(b"clean-control")
    (data / "attachments").mkdir(parents=True, exist_ok=True)
    (data / "attachments" / "receipt.jpg").write_bytes(b"retained-image")
    (data / "app").mkdir(parents=True, exist_ok=True)
    (data / "app" / ".env").write_bytes(b"SECRET=1\n")
    secrets_dir = machine / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    for name in ("postgres.password", "ticketbox_migrator.password", "ticketbox_runtime.password", "pgpass"):
        (secrets_dir / name).write_bytes(b"fixture-only-secret-0123456789abcdef")

    binding = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=0,
        data_root=str(data),
        active_release_id=release_id,
        previous_release_id=previous_release_id,
        release_manifest_sha256=manifest_sha,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )

    class NoopSecurity:
        def verify_machine_json(self, *_args):
            pass

        def protect_machine_json(self, *_args):
            pass

        def grant_backend_binding_read(self, *_args):
            pass

        def verify_binding_json(self, *_args):
            pass

    stores = FilesystemStores(
        machine,
        "TicketboxBackend",
        SimpleNamespace(security=NoopSecurity()),
        ThreadMutex(),
    )
    stores.publish(binding)
    install_op = ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id=f"fresh-{manifest_sha}",
        kind="install",
        request_hash="1" * 64,
        target_release_id=release_id,
        data_root=str(data),
        release_manifest_sha256=manifest_sha,
        backend_port=8000,
        phase="committed",
        no_return_point=True,
        completed_step="health",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision=schema_revision,
        health_attestation_key=OLD_KEY,
    )
    stores.archive_committed(install_op)
    return app, program_data, stores, binding, install_op


def _stopped_pg_runner():
    class StoppedRunner:
        def run(self, argv, **_kwargs):
            cmd = Path(str(argv[0])).name.lower()
            if cmd == "sc.exe":
                return CompletedCommand(tuple(argv), 0, "STATE : 1 STOPPED\n", "")
            return CompletedCommand(
                tuple(argv),
                0,
                "Database cluster state: shut down\nDatabase system identifier: 123456789\n",
                "",
            )

    return StoppedRunner()


def _build_staged_release(
    app: Path,
    *,
    release_id: str,
    schema_revision: str,
    lifecycle_bytes: bytes,
    vcredist_bytes: bytes = b"vcredist-1.3.0",
    ico_bytes: bytes = b"ico-1.3.0",
) -> tuple[Path, str]:
    stage = expected_upgrade_stage_root(app, release_id)
    for rel, content in (
        ("backend/ticketbox-backend.exe", f"backend-{release_id}".encode()),
        ("manager/ticketbox-manager.exe", f"manager-{release_id}".encode()),
        ("connector/cloudflared.exe", f"cloudflared-{release_id}".encode()),
        ("lifecycle/TicketboxLifecycle.exe", lifecycle_bytes),
        ("_staging/vc_redist.x64.exe", vcredist_bytes),
        ("_staging/ticketbox.ico", ico_bytes),
    ):
        path = stage / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def rec_from(disk_path: Path, manifest_rel: str) -> dict[str, object]:
        raw = disk_path.read_bytes()
        return {"path": manifest_rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    manifest_payload = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": schema_revision,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                rec_from(stage / "backend/ticketbox-backend.exe", f"releases/{release_id}/backend/ticketbox-backend.exe"),
                rec_from(stage / "manager/ticketbox-manager.exe", f"releases/{release_id}/manager/ticketbox-manager.exe"),
                rec_from(stage / "connector/cloudflared.exe", f"releases/{release_id}/connector/cloudflared.exe"),
                rec_from(stage / "lifecycle/TicketboxLifecycle.exe", f"releases/{release_id}/lifecycle/TicketboxLifecycle.exe"),
                rec_from(app / "postgresql/bin/postgres.exe", "postgresql/bin/postgres.exe"),
                rec_from(app / "bin/shawl.exe", "bin/shawl.exe"),
                rec_from(stage / "_staging/vc_redist.x64.exe", "bin/vc_redist.x64.exe"),
                rec_from(stage / "lifecycle/TicketboxLifecycle.exe", "bin/lifecycle/TicketboxLifecycle.exe"),
                rec_from(stage / "_staging/ticketbox.ico", "ticketbox.ico"),
            ],
        },
    }
    manifest_path = stage / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    return stage, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_m1_pre_upgrade_cold_backup_is_natively_valid_without_exemption_and_sync_promotes_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, program_data, stores, binding, install_op = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
        lifecycle_bytes=b"lifecycle-1.2.1",
    )
    stage_130, manifest_130_sha = _build_staged_release(
        app,
        release_id="1.3.0",
        schema_revision="20261101_0001",
        lifecycle_bytes=b"lifecycle-1.3.0",
    )
    assert not (app / "releases" / "1.3.0").exists()

    op_id = f"upgrade-{manifest_130_sha}"
    active_upgrade = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id=op_id,
        kind="upgrade",
        request_hash="2" * 64,
        target_release_id="1.3.0",
        data_root=binding.data_root,
        release_manifest_sha256=manifest_130_sha,
        backend_port=8000,
        phase="prepared",
        no_return_point=False,
        completed_step="stop_services",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="f" * 64,
        expected_restore_epoch=0,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256=binding.release_manifest_sha256,
        source_schema_revision="20261029_0002",
    )
    stores.publish_active(active_upgrade)

    import ticketbox_lifecycle.runtime.windows_upgrade as win_upgrade_mod

    @contextmanager
    def open_archive(path: Path):
        with path.open("x+b") as handle:
            yield handle

    monkeypatch.setattr(win_upgrade_mod, "protect_directory", lambda *_a, **_k: None)
    monkeypatch.setattr(win_upgrade_mod, "create_private_archive", open_archive)

    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=op_id,
        request_hash="2" * 64,
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=manifest_130_sha,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    verifier = WindowsShipmentVerifier(app, program_data)
    verifier.verify_staged_release(request, staged_release_root=stage_130)

    platform = WindowsUpgradePlatform(
        stores,
        _stopped_pg_runner(),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        staged_release_root=stage_130,
        expected_app_dir=app,
        expected_program_data_root=program_data,
    )
    backup = platform.create_verified_cold_backup(request, binding, allowed_operation_id=op_id)
    assert backup.schema_revision == "20261029_0002"
    backup_path = Path(backup.path)
    source_request = replace(
        request,
        target_release_id="1.2.1",
        release_manifest_sha256=binding.release_manifest_sha256,
        schema_revision="20261029_0002",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    with backup_path.open("rb") as stream:
        restore_source = ColdRestoreSource(stream, backup.sha256, source_request)
        assert restore_source.source_operation_id == install_op.operation_id
        assert "machine/operations/active.json" not in restore_source.manifest["entries"]
        assert not any(k.startswith("program/releases/1.3.0/") for k in restore_source.manifest["entries"])
        assert "pre_upgrade_shared_excluded" not in restore_source.manifest
        assert "program/bin/lifecycle/TicketboxLifecycle.exe" in restore_source.manifest["entries"]
        assert len(restore_source.recovery_secret()) == 64

    partial_tmp = app / "releases" / "1.3.0" / "backend" / "is-abc123.tmp"
    partial_tmp.parent.mkdir(parents=True, exist_ok=True)
    partial_tmp.write_bytes(b"power-loss-junk")
    platform.materialize_target_release(request, allowed_sibling_releases=frozenset({"1.2.1"}))
    assert not partial_tmp.exists()
    assert (app / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").read_bytes() == b"backend-1.3.0"

    platform.sync_shared_payload(request, allowed_sibling_releases=frozenset({"1.2.1"}))
    assert (app / "bin" / "lifecycle" / "TicketboxLifecycle.exe").read_bytes() == b"lifecycle-1.3.0"
    assert (app / "bin" / "vc_redist.x64.exe").read_bytes() == b"vcredist-1.3.0"
    assert (app / "ticketbox.ico").read_bytes() == b"ico-1.3.0"
    assert not (app / "releases" / "1.3.0" / "_staging").exists()
    verifier.bind_and_verify(request, allowed_sibling_releases=frozenset({"1.2.1"}))

    platform.verify_existing_cold_backup(
        request,
        backup.path,
        backup.sha256,
        binding,
        source_release_id="1.2.1",
        source_schema_revision="20261029_0002",
    )


def test_m2_post_upgrade_cold_copy_excludes_previous_release_and_preserves_owner_recovery_secret(
    tmp_path: Path,
) -> None:
    app, program_data, stores, old_binding, install_op = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
        lifecycle_bytes=b"lifecycle-1.2.1",
    )
    for rel, content in (
        ("releases/1.3.0/backend/ticketbox-backend.exe", b"backend-1.3.0"),
        ("releases/1.3.0/manager/ticketbox-manager.exe", b"manager-1.3.0"),
        ("releases/1.3.0/lifecycle/TicketboxLifecycle.exe", b"lifecycle-1.3.0"),
        ("bin/lifecycle/TicketboxLifecycle.exe", b"lifecycle-1.3.0"),
    ):
        path = app / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def rec(rel: str) -> dict[str, object]:
        raw = (app / Path(rel)).read_bytes()
        return {"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    new_manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.3.0",
        "product_version": "1.3.0",
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                rec("releases/1.3.0/backend/ticketbox-backend.exe"),
                rec("releases/1.3.0/manager/ticketbox-manager.exe"),
                rec("releases/1.3.0/lifecycle/TicketboxLifecycle.exe"),
                rec("postgresql/bin/postgres.exe"),
                rec("bin/shawl.exe"),
                rec("bin/vc_redist.x64.exe"),
                rec("bin/lifecycle/TicketboxLifecycle.exe"),
                rec("ticketbox.ico"),
            ],
        },
    }
    manifest_130 = app / "releases" / "1.3.0" / "release-manifest.json"
    manifest_130.write_text(json.dumps(new_manifest), encoding="utf-8")
    sha_130 = hashlib.sha256(manifest_130.read_bytes()).hexdigest()

    new_binding = replace(
        old_binding,
        active_release_id="1.3.0",
        previous_release_id="1.2.1",
        release_manifest_sha256=sha_130,
        health_attestation_key="9" * 64,
    )
    stores.publish(new_binding)
    upgrade_op = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id=f"upgrade-{sha_130}",
        kind="upgrade",
        request_hash="3" * 64,
        target_release_id="1.3.0",
        data_root=new_binding.data_root,
        release_manifest_sha256=sha_130,
        backend_port=8000,
        phase="committed",
        no_return_point=True,
        completed_step="health",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="9" * 64,
        expected_restore_epoch=0,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256=old_binding.release_manifest_sha256,
        source_schema_revision="20261029_0002",
        backup_path=str(program_data / "backups" / "pre.tbxcold"),
        backup_sha256="f" * 64,
    )
    stores.archive_committed(upgrade_op)

    source = ColdInstallation.read(stores, app, program_data, runner=_stopped_pg_runner())
    archive_path = tmp_path / "daily-post-upgrade.tbxcold"
    with archive_path.open("x+b") as handle:
        cold_archive.write_archive(
            handle,
            source.roots(),
            source.identity(),
            source.require_stopped,
            exclude_entry=source.exclude_entry,
        )
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    restore_req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="restore",
        operation_id=f"restore-{sha_130}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=str(tmp_path / "restored" / "data"),
        program_data_root=str(tmp_path / "restored"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_130,
        schema_revision="20261101_0001",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    with archive_path.open("rb") as stream:
        restored = ColdRestoreSource(stream, digest, restore_req)
        assert restored.source_operation_id == install_op.operation_id
        assert not any(k.startswith("program/releases/1.2.1/") for k in restored.manifest["entries"])
        assert "pre_upgrade_shared_excluded" not in restored.manifest
        assert len(restored.recovery_secret()) == 64

    foreign_sibling = app / "releases" / "9.9.9" / "backend" / "evil.exe"
    foreign_sibling.parent.mkdir(parents=True, exist_ok=True)
    foreign_sibling.write_bytes(b"rogue")
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        ColdInstallation.read(stores, app, program_data, runner=_stopped_pg_runner())


def test_m3_crash_after_scm_rebind_before_scm_journal_recovers_and_foreign_scm_fails_closed(
    tmp_path: Path,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="rebind_scm_after_config",
    )

    first = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert first.ok is False
    assert first.phase == "failed_recoverable"
    assert platform.bound_release == "1.3.0"
    active = stores.read_active()
    assert isinstance(active, UpgradeOperation)
    assert active.completed_step == "alembic"
    assert adapters.scm.backend_fenced is True

    platform.fail_at = None
    second = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert second.ok is True
    assert second.phase == "committed"
    assert stores.read().active_release_id == "1.3.0"
    assert stores.read().previous_release_id == "1.2.1"

    req_bad, stores_bad, _a2, s2, t2 = _make_upgrade_fixture(tmp_path / "foreign-scm")
    plat_bad = FakeUpgradePlatform(
        stores=stores_bad,
        source_revision=s2,
        target_revision=t2,
        fail_at="rebind_scm",
    )
    upgrade(stores_bad.as_lifecycle_stores(), req_bad, plat_bad)
    plat_bad.fail_at = None
    plat_bad.bound_release = "9.9.9"
    blocked = upgrade(stores_bad.as_lifecycle_stores(), req_bad, plat_bad)
    assert blocked.ok is False
    assert blocked.code == "scm_configuration_mismatch"


@pytest.mark.parametrize("hard_crash", [True, False])
def test_m4_crash_after_release_activated_health_before_binding_publish_never_emits_illegal_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hard_crash: bool,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    observed_transitions: list[tuple[str, str | None]] = []
    orig_publish_active = stores.publish_active
    orig_publish_binding = stores.publish
    crash_armed = {"armed": True}

    def track_active(op: ActiveOperation) -> None:
        observed_transitions.append((op.phase, op.completed_step))
        orig_publish_active(op)

    def fail_binding_once(binding: InstallationBinding) -> None:
        if crash_armed["armed"]:
            crash_armed["armed"] = False
            if hard_crash:
                raise KeyboardInterrupt("simulated power loss before installation.json replace")
            raise OSError("simulated transient I/O error publishing installation.json")
        orig_publish_binding(binding)

    monkeypatch.setattr(stores, "publish_active", track_active)
    monkeypatch.setattr(stores, "publish", fail_binding_once)

    if hard_crash:
        with pytest.raises(KeyboardInterrupt):
            upgrade(stores.as_lifecycle_stores(), request, platform)
        active = stores.read_active()
        assert isinstance(active, UpgradeOperation)
        assert (active.phase, active.completed_step) == ("release_activated", "health")
    else:
        first = upgrade(stores.as_lifecycle_stores(), request, platform)
        assert first.ok is False
        assert first.installation_published is False
        active = stores.read_active()
        assert isinstance(active, UpgradeOperation)
        assert (active.phase, active.completed_step) == ("failed_recoverable", "health")

    assert stores.read().active_release_id == "1.2.1"

    second = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert second.ok is True
    assert second.phase == "committed"
    assert stores.read().active_release_id == "1.3.0"
    assert stores.read().previous_release_id == "1.2.1"
    assert ("data_ready", "health") not in observed_transitions
    assert ("prepared", "health") not in observed_transitions


def test_m7_residual_verify_only_process_is_rejected_and_forced_restart_reaches_normal_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    platform.stale_mode_on_commit = "upgrade_verify_only"

    first = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert first.ok is False
    assert first.phase == "committed"
    assert first.code == "health_mode_mismatch"
    assert first.installation_published is True
    assert adapters.scm.autostart_enabled is False
    assert stores.read_active() is not None
    assert not stores.history

    platform.stale_mode_on_commit = None
    second = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert second.ok is True
    assert second.phase == "committed"
    assert adapters.scm.autostart_enabled is True
    assert stores.read_active() is None
    assert len(stores.history) == 1
    assert platform.health_modes_verified[-1] == "normal"

    import ticketbox_lifecycle.runtime.windows_dataset as ds_mod

    key = "a" * 64
    req = replace(
        request,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        health_attestation_key=key,
    )
    body = json.dumps({
        "contract": "ticketbox-installation-health-v3",
        "status": "ok",
        "product": "ticketbox",
        "backend_version": "1.3.0",
        "installation_id": INSTALL_ID,
        "runtime_access_state": "available",
        "owner_state": "configured",
        "owner_recovery_channel": "managed_host",
        "mobile_connectivity": {
            "public_origin": "",
            "mobile_endpoint_state": "local_only",
            "android_binding_state": "not_configured",
            "iphone_upload_state": "not_configured",
        },
    }).encode("utf-8")

    def fake_fetch(_port: int, *, challenge: str):
        return (
            200,
            body,
            sign_challenge(key, challenge),
            "upgrade_verify_only",
            sign_runtime_mode(key, challenge, "upgrade_verify_only"),
        )

    adapter = WindowsDatasetAdapter(
        SimpleNamespace(run=lambda *_a, **_k: CompletedCommand((), 0, DATASET_ID + "\n", "")),
        SimpleNamespace(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(ds_mod, "fetch_installation_health_with_mode", fake_fetch)
    adapter.verify_runtime_mode(req, expected_mode="upgrade_verify_only")
    with pytest.raises(LifecycleError, match="expected 'normal'"):
        adapter.verify_runtime_mode(req, expected_mode="normal")

    def fake_forged_mode(_port: int, *, challenge: str):
        return (200, body, sign_challenge(key, challenge), "normal", "0" * 64)

    monkeypatch.setattr(ds_mod, "fetch_installation_health_with_mode", fake_forged_mode)
    with pytest.raises(LifecycleError, match="runtime mode attestation is invalid"):
        adapter.verify_runtime_mode(req, expected_mode="normal")


def test_should_fix_strict_previous_release_id_and_durable_published_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    binding = stores.read()
    assert binding is not None
    bound_req = replace(
        request,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        health_attestation_key="c" * 64,
    )
    for bad_prev in ("", "bad release!", "1.3.0"):
        with pytest.raises(LifecycleViolation, match="previous_release_id"):
            upgrade_binding(binding, bound_req, previous_release_id=bad_prev)

    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    orig_publish_active = stores.publish_active
    fail_commit = {"armed": True}

    def fail_on_committed_publish(op: ActiveOperation) -> None:
        if fail_commit["armed"] and op.phase == "committed":
            fail_commit["armed"] = False
            raise OSError("disk full writing committed active.json")
        orig_publish_active(op)

    monkeypatch.setattr(stores, "publish_active", fail_on_committed_publish)
    failed = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert failed.ok is False
    assert failed.installation_published is True
    assert stores.read().active_release_id == "1.3.0"

    recovered = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert recovered.ok is True
    assert recovered.phase == "committed"


def test_sequential_a_b_c_upgrades_support_daily_cold_copy_replay_and_durable_cli_status(
    tmp_path: Path,
) -> None:
    app, program_data, stores, binding_a, install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.0",
        schema_revision="20261023_0002",
        lifecycle_bytes=b"lifecycle-1.2.0",
    )

    def materialize_release(release_id: str, schema_rev: str, lifecycle_bytes: bytes) -> str:
        for rel, content in (
            (f"releases/{release_id}/backend/ticketbox-backend.exe", f"backend-{release_id}".encode()),
            (f"releases/{release_id}/manager/ticketbox-manager.exe", f"manager-{release_id}".encode()),
            (f"releases/{release_id}/lifecycle/TicketboxLifecycle.exe", lifecycle_bytes),
            ("bin/lifecycle/TicketboxLifecycle.exe", lifecycle_bytes),
        ):
            path = app / Path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        def rec(rel: str) -> dict[str, object]:
            raw = (app / Path(rel)).read_bytes()
            return {"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

        manifest = {
            "schema": "ticketbox-release-manifest-v1",
            "release_id": release_id,
            "product_version": release_id,
            "lifecycle_compatibility": [REQUEST_SCHEMA],
            "min_schema_revision": "20260722_0001",
            "max_schema_revision": schema_rev,
            "min_semantic_revision": "ticketbox-dataset-semantics-v1",
            "signing_state": "release-bound",
            "immutable_payload": {
                "algorithm": "SHA-256",
                "files": [
                    rec(f"releases/{release_id}/backend/ticketbox-backend.exe"),
                    rec(f"releases/{release_id}/manager/ticketbox-manager.exe"),
                    rec(f"releases/{release_id}/lifecycle/TicketboxLifecycle.exe"),
                    rec("postgresql/bin/postgres.exe"),
                    rec("bin/shawl.exe"),
                    rec("bin/vc_redist.x64.exe"),
                    rec("bin/lifecycle/TicketboxLifecycle.exe"),
                    rec("ticketbox.ico"),
                ],
            },
        }
        mpath = app / "releases" / release_id / "release-manifest.json"
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        return hashlib.sha256(mpath.read_bytes()).hexdigest()

    sha_b = materialize_release("1.2.1", "20261029_0002", b"lifecycle-1.2.1")
    stores.archive_committed(
        UpgradeOperation(
            schema=OPERATION_SCHEMA,
            operation_id=f"upgrade-{sha_b}",
            kind="upgrade",
            request_hash="4" * 64,
            target_release_id="1.2.1",
            data_root=binding_a.data_root,
            release_manifest_sha256=sha_b,
            backend_port=8000,
            phase="committed",
            no_return_point=True,
            completed_step="health",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261029_0002",
            health_attestation_key="7" * 64,
            expected_restore_epoch=0,
            previous_release_id="1.2.0",
            previous_release_manifest_sha256=binding_a.release_manifest_sha256,
            source_schema_revision="20261023_0002",
            backup_path=str(program_data / "backups" / "pre-b.tbxcold"),
            backup_sha256="e" * 64,
        )
    )
    sha_c = materialize_release("1.3.0", "20261101_0001", b"lifecycle-1.3.0")
    binding_c = replace(
        binding_a,
        active_release_id="1.3.0",
        previous_release_id="1.2.1",
        release_manifest_sha256=sha_c,
        health_attestation_key="8" * 64,
    )
    stores.publish(binding_c)
    stores.archive_committed(
        UpgradeOperation(
            schema=OPERATION_SCHEMA,
            operation_id=f"upgrade-{sha_c}",
            kind="upgrade",
            request_hash="5" * 64,
            target_release_id="1.3.0",
            data_root=binding_a.data_root,
            release_manifest_sha256=sha_c,
            backend_port=8000,
            phase="committed",
            no_return_point=True,
            completed_step="health",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="8" * 64,
            expected_restore_epoch=0,
            previous_release_id="1.2.1",
            previous_release_manifest_sha256=sha_b,
            source_schema_revision="20261029_0002",
            backup_path=str(program_data / "backups" / "pre-c.tbxcold"),
            backup_sha256="f" * 64,
        )
    )

    assert stores.known_sibling_releases(binding_c, exclude_release_id="1.3.0") == frozenset({"1.2.0", "1.2.1"})
    source = ColdInstallation.read(stores, app, program_data, runner=_stopped_pg_runner())
    archive_path = tmp_path / "post-abc.tbxcold"
    with archive_path.open("x+b") as handle:
        cold_archive.write_archive(
            handle,
            source.roots(),
            source.identity(),
            source.require_stopped,
            exclude_entry=source.exclude_entry,
        )
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    replay_req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{sha_c}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_c.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_c,
        schema_revision="20261101_0001",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    with archive_path.open("rb") as stream:
        restored = ColdRestoreSource(stream, digest, replay_req)
        assert restored.source_operation_id == install_a.operation_id
        assert not any(k.startswith("program/releases/1.2.0/") for k in restored.manifest["entries"])
        assert not any(k.startswith("program/releases/1.2.1/") for k in restored.manifest["entries"])

    verifier = WindowsShipmentVerifier(app, program_data)
    verifier.bind_and_verify(
        replay_req,
        allowed_sibling_releases=stores.known_sibling_releases(binding_c, exclude_release_id="1.3.0"),
    )
    assert _read_durable_failure_status(stores, replay_req, replay_req.operation_id) == ("committed", True)

    rogue = app / "releases" / "9.9.9" / "backend" / "rogue.exe"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_bytes(b"rogue")
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        ColdInstallation.read(stores, app, program_data, runner=_stopped_pg_runner())


def test_upgrade_refuses_active_managed_connector_and_succeeds_after_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    stores.managed_connector_present = True
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    with pytest.raises(LifecycleViolation) as caught:
        upgrade(stores.as_lifecycle_stores(), request, platform)
    assert caught.value.code == "upgrade_managed_connector_active"
    assert stores.read_active() is None
    assert platform.backup_creates == 0
    assert platform.migration_calls == 0

    stores.managed_connector_present = False
    ok_res = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert ok_res.ok is True

    import ticketbox_lifecycle.runtime.filesystem_stores as fs_mod

    machine = tmp_path / "machine-conn"
    state_file = machine / "connectors" / "cloudflare" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        fs_mod,
        "service_registered",
        lambda name: name in {"TicketboxPg", "TicketboxBackend"},
    )
    binding = stores.read()
    assert binding is not None
    assert _managed_connector_present(machine, binding=binding) is False
    state_file.write_text('{"configured": true}', encoding="utf-8")
    assert _managed_connector_present(machine, binding=binding) is True
    state_file.write_text("{corrupt", encoding="utf-8")
    assert _managed_connector_present(machine, binding=binding) is True
    state_file.write_text('{"configured": false}', encoding="utf-8")
    assert _managed_connector_present(machine, binding=binding) is True
    removed_state = {
        "schema": "ticketbox-connector-state-v1",
        "profile": "cloudflare-tunnel-v1",
        "install_id": binding.install_id,
        "dataset_id": binding.dataset_id,
        "expected_restore_epoch": binding.expected_restore_epoch,
        "release_manifest_sha256": binding.release_manifest_sha256,
        "revision": 2,
        "credential_generation": 2,
        "public_origin_revision": 1,
        "enabled": False,
        "configured": False,
        "operation_id": "33333333-3333-4333-8333-333333333333",
        "tunnel_id": None,
    }
    state_file.write_text(json.dumps(removed_state), encoding="utf-8")
    assert _managed_connector_present(machine, binding=binding) is False
    secret = machine / "connectors" / "cloudflare" / "secrets" / "credential-g1.token"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_bytes(b"secret")
    assert _managed_connector_present(machine, binding=binding) is True
    secret.unlink()
    monkeypatch.setattr(fs_mod, "service_registered", lambda _name: True)
    assert _managed_connector_present(machine, binding=binding) is True


def test_pg_start_type_must_be_auto_start_before_backup_and_sql(tmp_path: Path) -> None:
    request = replace(
        make_install_request(tmp_path),
        command="upgrade",
        operation_id="upgrade-" + ("a" * 64),
        target_release_id="1.3.0",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
    )
    binding = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=0,
        data_root=request.data_root,
        active_release_id="1.2.1",
        previous_release_id=None,
        release_manifest_sha256=OLD_MANIFEST_SHA,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )
    pg_demand = replace(expected_pg_service(request), start_type=SERVICE_DEMAND_START)
    backend_cfg = expected_backend_service(
        replace(request, target_release_id="1.2.1"),
        start_type=SERVICE_AUTO_START,
    )

    class DemandPgObserver:
        def observe(self, name: str):
            return pg_demand if name == "TicketboxPg" else backend_cfg

    class NoopScm:
        def fence_backend(self, _req):
            pass

    platform = WindowsUpgradePlatform(
        SimpleNamespace(_mutex=ThreadMutex()),  # type: ignore[arg-type]
        _stopped_pg_runner(),
        SimpleNamespace(),  # type: ignore[arg-type]
        NoopScm(),  # type: ignore[arg-type]
        DemandPgObserver(),  # type: ignore[arg-type]
        expected_app_dir=Path(request.app_dir),
        expected_program_data_root=Path(request.program_data_root),
    )
    with pytest.raises(LifecycleError):
        platform.stop_services_for_backup(request, binding)
    with pytest.raises(LifecycleError):
        platform.verify_pg_service_for_upgrade(request)


def test_crash_after_pg_commit_before_stdout_and_post_replace_committed_never_downgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path / "win1")
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="migrate_after_commit_before_stdout",
    )
    first = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert first.ok is False
    assert platform.live_revision == tgt_rev
    active = stores.read_active()
    assert isinstance(active, UpgradeOperation)
    assert active.no_return_point is True

    platform.fail_at = None
    second = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert second.ok is True
    assert second.phase == "committed"

    req2, stores2, _a2, s2, t2 = _make_upgrade_fixture(tmp_path / "win2")
    plat2 = FakeUpgradePlatform(stores=stores2, source_revision=s2, target_revision=t2)
    orig_publish_active = stores2.publish_active
    armed = {"fail": True}

    def publish_then_readback_error(op: ActiveOperation) -> None:
        orig_publish_active(op)
        if armed["fail"] and op.phase == "committed":
            armed["fail"] = False
            raise OSError("transient post-replace ACL readback error")

    monkeypatch.setattr(stores2, "publish_active", publish_then_readback_error)
    failed = upgrade(stores2.as_lifecycle_stores(), req2, plat2)
    assert failed.ok is False
    assert failed.phase == "committed"
    assert failed.installation_published is True
    persisted = stores2.read_active()
    assert persisted is not None and persisted.phase == "committed"

    recovered = upgrade(stores2.as_lifecycle_stores(), req2, plat2)
    assert recovered.ok is True
    assert recovered.phase == "committed"
    assert stores2.read_active() is None


def test_archived_committed_upgrade_replay_verifies_scm_running_and_restarts_if_stopped(
    tmp_path: Path,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    first = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert first.ok is True
    assert stores.read_active() is None
    assert len(stores.history) == 1

    starts_before = adapters.scm.apply_calls
    adapters.scm._done.discard("start_services")
    platform.running_mode = "normal"

    replay = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert replay.ok is True
    assert replay.phase == "committed"
    assert adapters.scm.apply_calls == starts_before + 1
    assert "start_services" in adapters.scm._done
    assert adapters.scm.autostart_enabled is True


def test_shipment_verifier_accepts_prerelease_previous_release_id_matching_runtime_pattern(
    tmp_path: Path,
) -> None:
    app = tmp_path / "Ticketbox"
    old_release = app / "releases" / "1.2.1-rc1" / "backend" / "ticketbox-backend.exe"
    new_backend = app / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe"
    postgres = app / "postgresql" / "bin" / "postgres.exe"
    for path, content in (
        (old_release, b"old-rc"),
        (new_backend, b"new-backend"),
        (postgres, b"postgres"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def rec(rel: str) -> dict[str, object]:
        data = (app / Path(rel)).read_bytes()
        return {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.3.0",
        "product_version": "1.3.0",
        "lifecycle_compatibility": [REQUEST_SCHEMA],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                rec("releases/1.3.0/backend/ticketbox-backend.exe"),
                rec("postgresql/bin/postgres.exe"),
            ],
        },
    }
    mpath = app / "releases" / "1.3.0" / "release-manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(mpath.read_bytes()).hexdigest()
    verifier = WindowsShipmentVerifier(app, tmp_path / "programdata")
    binding = SimpleNamespace(
        active_release_id="1.3.0",
        previous_release_id="1.2.1-rc1",
        release_manifest_sha256=digest,
    )
    assert verifier.verify_installed(binding)["release_id"] == "1.3.0"


def test_pass2_f2_shared_sync_temp_stays_outside_app_and_post_binding_unarchived_resume_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ticketbox_lifecycle.runtime.windows_shipment as ship_mod

    app, program_data, stores, binding_a, _install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
        lifecycle_bytes=b"lifecycle-1.2.1",
    )
    stage_b, sha_b = _build_staged_release(
        app,
        release_id="1.3.0",
        schema_revision="20261101_0001",
        lifecycle_bytes=b"lifecycle-1.3.0",
    )
    req_b = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{sha_b}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_a.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_b,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    verifier = WindowsShipmentVerifier(app, program_data)
    verifier.materialize_staged_release(req_b, staged_release_root=stage_b)

    real_replace = ship_mod.os.replace
    armed = {"crash": True}

    def crash_on_vcredist_replace(src: Path, dst: Path) -> None:
        if armed["crash"] and Path(dst).name == "vc_redist.x64.exe":
            armed["crash"] = False
            assert app not in Path(src).parents
            assert stage_b in Path(src).parents
            raise OSError("simulated power loss between mkstemp and os.replace")
        real_replace(src, dst)

    monkeypatch.setattr(ship_mod.os, "replace", crash_on_vcredist_replace)
    with pytest.raises(OSError, match="simulated power loss"):
        verifier.sync_staged_shared_payload(
            req_b,
            staged_release_root=stage_b,
            allowed_sibling_releases=frozenset({"1.2.1"}),
        )
    assert not list(app.rglob("*.tmp"))

    verifier.sync_staged_shared_payload(
        req_b,
        staged_release_root=stage_b,
        allowed_sibling_releases=frozenset({"1.2.1"}),
    )
    assert not list(app.rglob("*.tmp"))

    req2, mem_stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path / "post-bind")
    plat2 = FakeUpgradePlatform(stores=mem_stores, source_revision=src_rev, target_revision=tgt_rev)
    orig_pub = mem_stores.publish_active
    crash_post_bind = {"armed": True}

    def crash_before_committed(op: ActiveOperation) -> None:
        if crash_post_bind["armed"] and op.phase == "committed":
            crash_post_bind["armed"] = False
            raise KeyboardInterrupt("power loss after installation.json publish before committed")
        orig_pub(op)

    monkeypatch.setattr(mem_stores, "publish_active", crash_before_committed)
    with pytest.raises(KeyboardInterrupt):
        upgrade(mem_stores.as_lifecycle_stores(), req2, plat2)
    assert mem_stores.read().active_release_id == "1.3.0"
    assert not mem_stores.history

    resumed = upgrade(mem_stores.as_lifecycle_stores(), req2, plat2)
    assert resumed.ok is True
    assert resumed.phase == "committed"
    assert len(mem_stores.history) == 1
    assert plat2.connector_rebind_calls >= 1
    assert plat2.shortcut_update_calls >= 1


def test_pass2_f5_empty_unknown_release_dir_rejected_and_cli_io_error_reports_unknown_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, program_data, stores, binding, _install_op = _build_physical_installation(
        tmp_path,
        release_id="1.3.0",
        schema_revision="20261101_0001",
    )
    empty_rogue = app / "releases" / "9.9.9"
    empty_rogue.mkdir(parents=True)

    verifier = WindowsShipmentVerifier(app, program_data)
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        verifier.verify_installed(binding)
    with pytest.raises(LifecycleViolation, match="unexpected release directory"):
        ColdInstallation.read(stores, app, program_data, runner=_stopped_pg_runner())
    empty_rogue.rmdir()

    empty_top = app / "rogue_empty"
    empty_top.mkdir()
    with pytest.raises(LifecycleViolation, match="unexpected directory"):
        verifier.verify_installed(binding)
    empty_top.rmdir()

    req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{binding.release_manifest_sha256}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=binding.release_manifest_sha256,
    )
    monkeypatch.setattr(stores, "read", lambda: (_ for _ in ()).throw(OSError("binding read I/O failure")))
    phase, published = _read_durable_failure_status(stores, req, req.operation_id)
    assert phase == "failed_recoverable"
    assert published is None


def test_pass2_f6_removed_connector_rebinds_and_reconfigures_on_b_and_shortcut_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ticketbox_lifecycle.connector_schema import (
        PROFILE,
        REQUEST_SCHEMA as CONN_REQ_SCHEMA,
        ConnectorState,
        parse_request,
        parse_state,
    )
    from ticketbox_lifecycle.domain.connector import ConnectorStores, run_connector

    app, program_data, stores, binding_a, _install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
    )
    stage_b, sha_b = _build_staged_release(
        app,
        release_id="1.3.0",
        schema_revision="20261101_0001",
        lifecycle_bytes=b"lifecycle-1.3.0",
    )
    state_path = program_data / "machine" / "connectors" / "cloudflare" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    class PlainConnectorStore:
        def read(self) -> ConnectorState | None:
            if not state_path.exists():
                return None
            return parse_state(json.loads(state_path.read_text(encoding="utf-8")))

        def publish(self, state: ConnectorState) -> None:
            state_path.write_text(json.dumps(asdict(state)), encoding="utf-8")

    class FakeHost:
        def verify_context(self, _req): pass
        def verify_owned(self, _req, _st): pass
        def credential_identity(self, _req, _gen, _tok): return "44444444-4444-4444-8444-444444444444"
        def prepare_credential(self, _req, _gen, _tok): pass
        def prepare_service(self, _req, _st): pass
        def apply_desired(self, _req, _st): pass
        def verify_desired(self, _req, _st): pass
        def clean_credentials(self, _req, _st): pass

    store = PlainConnectorStore()
    configure_a = parse_request({
        "schema": CONN_REQ_SCHEMA,
        "profile": PROFILE,
        "action": "configure",
        "operation_id": "22222222-2222-4222-8222-222222222222",
        "install_id": binding_a.install_id,
        "dataset_id": binding_a.dataset_id,
        "expected_restore_epoch": binding_a.expected_restore_epoch,
        "release_manifest_sha256": binding_a.release_manifest_sha256,
        "expected_revision": 0,
        "expected_credential_generation": 0,
        "expected_enabled": False,
        "expected_public_origin_revision": 0,
        "initiator_sid": "S-1-5-21-1-2-3-1001",
        "desired_enabled": True,
        "closing_operation_id": None,
        "closing_request_hash": None,
    })
    assert run_connector(ConnectorStores(MemoryMutex(), stores, stores, store, FakeHost()), configure_a, token="tok-a").phase == "committed"

    remove_op_id = "33333333-3333-4333-8333-333333333333"
    remove_a = parse_request({
        "schema": CONN_REQ_SCHEMA,
        "profile": PROFILE,
        "action": "remove",
        "operation_id": remove_op_id,
        "install_id": binding_a.install_id,
        "dataset_id": binding_a.dataset_id,
        "expected_restore_epoch": binding_a.expected_restore_epoch,
        "release_manifest_sha256": binding_a.release_manifest_sha256,
        "expected_revision": 1,
        "expected_credential_generation": 1,
        "expected_enabled": True,
        "expected_public_origin_revision": 0,
        "initiator_sid": "S-1-5-21-1-2-3-1001",
        "desired_enabled": False,
        "closing_operation_id": None,
        "closing_request_hash": None,
    })
    assert run_connector(ConnectorStores(MemoryMutex(), stores, stores, store, FakeHost()), remove_a, token=None).phase == "committed"
    remove_history_path = program_data / "machine" / "operations" / "history" / f"{remove_op_id}.json"
    remove_history_before = remove_history_path.read_bytes()

    req_b = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{sha_b}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_a.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_b,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
    )
    binding_b = replace(
        binding_a,
        active_release_id="1.3.0",
        previous_release_id="1.2.1",
        release_manifest_sha256=sha_b,
    )
    stores.publish(binding_b)
    upgrade_op = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id=req_b.operation_id,
        kind="upgrade",
        request_hash="a" * 64,
        target_release_id="1.3.0",
        data_root=binding_a.data_root,
        release_manifest_sha256=sha_b,
        backend_port=8000,
        phase="committed",
        no_return_point=True,
        completed_step="health",
        install_id=binding_a.install_id,
        dataset_id=binding_a.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key=binding_a.health_attestation_key,
        expected_restore_epoch=binding_a.expected_restore_epoch,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256=binding_a.release_manifest_sha256,
        source_schema_revision="20261029_0002",
        backup_path=str(program_data / "backups" / "pre.tbxcold"),
        backup_sha256="b" * 64,
        business_writes_opened=True,
    )
    stores.publish_active(upgrade_op)
    stores.archive_committed(upgrade_op)

    platform = WindowsUpgradePlatform(
        stores,
        _stopped_pg_runner(),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        staged_release_root=stage_b,
        expected_app_dir=app,
        expected_program_data_root=program_data,
        connector_store_factory=lambda _m, _s: store,
    )
    platform.rebind_removed_connector_state(req_b, binding_b)
    rebound = store.read()
    assert rebound is not None
    assert rebound.release_manifest_sha256 == sha_b
    assert rebound.revision == 2
    assert rebound.credential_generation == 2
    assert rebound.configured is False
    assert rebound.enabled is False
    assert remove_history_path.read_bytes() == remove_history_before

    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repo_root / "backend"))
    monkeypatch.syspath_prepend(str(repo_root / "desktop"))
    from app.services import windows_connector_projection as backend_proj
    from backend_manager.connector_projection import parse_projection

    def _read_plain_record(path: Path) -> dict | None:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(backend_proj.os, "name", "nt")
    monkeypatch.setattr(backend_proj, "_read_record", _read_plain_record)
    monkeypatch.setattr(
        type(program_data),
        "glob",
        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("no FILE_LIST_DIRECTORY")),
    )
    monkeypatch.setattr(backend_proj, "runtime_settings_service_owned", lambda: True)
    monkeypatch.setattr(backend_proj, "DATA_ROOT", program_data / "data" / "app")
    monkeypatch.setattr(
        backend_proj,
        "read_runtime_settings",
        lambda *_a, **_kw: SimpleNamespace(public_origin_revision=0),
    )
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", binding_b.install_id)
    monkeypatch.setenv("TICKETBOX_DATASET_ID", binding_b.dataset_id)
    monkeypatch.setenv("TICKETBOX_EXPECTED_RESTORE_EPOCH", str(binding_b.expected_restore_epoch))
    monkeypatch.setenv("TICKETBOX_RELEASE_MANIFEST_SHA256", binding_b.release_manifest_sha256)

    raw_projection = backend_proj.connector_projection()
    assert raw_projection["operation"] is None
    assert raw_projection["lifecycle_busy"] is False
    proj = parse_projection(raw_projection, asdict(binding_b))
    assert proj.state == rebound

    conn_req = proj.request("configure", enabled=True, sid="S-1-5-21-1-2-3-1001")
    conn_op = run_connector(
        ConnectorStores(MemoryMutex(), stores, stores, store, FakeHost()),
        conn_req,
        token="valid-token",
    )
    assert conn_op.phase == "committed"
    final_state = store.read()
    assert final_state is not None
    assert final_state.configured is True
    assert final_state.revision == 3
    assert final_state.credential_generation == 3

    if sys.platform == "win32":
        fake_programs = tmp_path / "StartMenuPrograms"
        lnk = update_manager_start_menu_shortcut(req_b, programs_root=fake_programs)
        info = read_shortcut(lnk)
        assert str(info["target"]).casefold() == str(app / "releases" / "1.3.0" / "manager" / "ticketbox-manager.exe").casefold()
        assert str(info["working_dir"]).casefold() == str(app / "releases" / "1.3.0" / "manager").casefold()
        assert str(info["icon"]).casefold() == str(app / "ticketbox.ico").casefold()
        assert info["icon_index"] == 0
        assert info["app_user_model_id"] == MANAGER_APP_ID


def test_pass2_f7_double_readback_failure_after_committed_replace_never_overwrites_active_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingReadbackSecurity:
        def __init__(self) -> None:
            self.fail_verify = False

        def verify_machine_json(self, path: Path, *_args) -> None:
            if self.fail_verify and path.name == "active.json":
                raise OSError("transient ACL readback failure on active.json")

        def protect_machine_json(self, *_args) -> None:
            pass

        def grant_backend_binding_read(self, *_args) -> None:
            pass

        def verify_binding_json(self, *_args) -> None:
            pass

        def prepare_operation_store(self, *_args) -> None:
            pass

        def verify(self, *_args) -> None:
            pass

    sec = FailingReadbackSecurity()
    req, mem_stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    adapters.security = sec  # type: ignore[assignment]
    fs_stores = FilesystemStores(
        tmp_path / "programdata" / "machine",
        "TicketboxBackend",
        adapters,
        ThreadMutex(),
    )
    fs_stores.publish(mem_stores.read())

    orig_publish_active = fs_stores.publish_active

    def arm_fail_on_committed(op: ActiveOperation) -> None:
        if op.phase == "committed":
            sec.fail_verify = True
        orig_publish_active(op)

    monkeypatch.setattr(fs_stores, "publish_active", arm_fail_on_committed)

    lifecycle = fs_stores.as_lifecycle_stores()
    lifecycle = replace(
        lifecycle,
        shipment=mem_stores,
        observer=mem_stores,
        operations_write=fs_stores,
        operations_read=fs_stores,
        binding_read=fs_stores,
        binding_write=fs_stores,
    )
    plat = FakeUpgradePlatform(stores=mem_stores, source_revision=src_rev, target_revision=tgt_rev)
    plat.stores = SimpleNamespace(  # type: ignore[assignment]
        mutex=SimpleNamespace(_lock=SimpleNamespace(locked=lambda: True)),
        read_active=fs_stores.read_active,
        adapters=adapters,
        bind_and_verify=mem_stores.bind_and_verify,
    )
    result = upgrade(lifecycle, req, plat)
    assert result.ok is False
    assert result.phase == "committed"
    assert result.installation_published is True

    sec.fail_verify = False
    persisted = fs_stores.read_active()
    assert persisted is not None
    assert persisted.phase == "committed"

    with pytest.raises(LifecycleViolation, match="committed"):
        orig_publish_active(replace(persisted, phase="failed_recoverable"))
    sec.fail_verify = True
    with pytest.raises(LifecycleError, match="unreadable"):
        orig_publish_active(replace(persisted, phase="failed_recoverable"))
    sec.fail_verify = False
    assert fs_stores.read_active().phase == "committed"


def test_pass2_f8_service_exit_before_enable_autostart_never_reports_upgraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    first = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert first.ok is True
    assert stores.read_active() is None

    orig_enable = adapters.scm.enable_autostart

    def exit_right_before_autostart(req: InstallRequest) -> None:
        adapters.scm._done.discard("start_services")
        orig_enable(req)

    monkeypatch.setattr(adapters.scm, "enable_autostart", exit_right_before_autostart)
    replay_fail = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert replay_fail.ok is False
    assert replay_fail.phase == "committed"
    assert replay_fail.code != "upgraded"

    req2, stores2, adapters2, s2, t2 = _make_upgrade_fixture(tmp_path / "fresh-commit")
    plat2 = FakeUpgradePlatform(stores=stores2, source_revision=s2, target_revision=t2)
    orig_enable2 = adapters2.scm.enable_autostart

    def exit_before_autostart_fresh(req: InstallRequest) -> None:
        adapters2.scm._done.discard("start_services")
        orig_enable2(req)

    monkeypatch.setattr(adapters2.scm, "enable_autostart", exit_before_autostart_fresh)
    commit_fail = upgrade(stores2.as_lifecycle_stores(), req2, plat2)
    assert commit_fail.ok is False
    assert commit_fail.phase == "committed"
    assert commit_fail.code != "upgraded"
    assert stores2.read_active() is not None
    assert not stores2.history


def test_pass3_m2_preflight_blocks_residual_connector_secrets_and_bad_state_dacl_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.connector_schema import PROFILE, STATE_SCHEMA, ConnectorState
    from ticketbox_lifecycle.runtime import filesystem_stores as fs_mod

    monkeypatch.setattr(
        fs_mod,
        "service_registered",
        lambda name: name in {"TicketboxPg", "TicketboxBackend"},
    )
    app, program_data, stores, binding_a, _install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
    )
    req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id="upgrade-" + ("1" * 64),
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_a.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="1" * 64,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
    )
    connector_dir = program_data / "machine" / "connectors" / "cloudflare"
    secrets_dir = connector_dir / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    leftover_token = secrets_dir / "credential-g1.token"
    leftover_token.write_text("leftover", encoding="utf-8")
    assert stores.observe(req).managed_connector_present is True
    leftover_token.unlink()
    assert stores.observe(req).managed_connector_present is False

    removed_state = ConnectorState(
        schema=STATE_SCHEMA,
        profile=PROFILE,
        install_id=binding_a.install_id,
        dataset_id=binding_a.dataset_id,
        expected_restore_epoch=binding_a.expected_restore_epoch,
        release_manifest_sha256=binding_a.release_manifest_sha256,
        revision=2,
        credential_generation=1,
        public_origin_revision=0,
        enabled=False,
        configured=False,
        operation_id="33333333-3333-4333-8333-333333333333",
        tunnel_id=None,
    )
    state_path = connector_dir / "state.json"
    state_path.write_text(json.dumps(asdict(removed_state)), encoding="utf-8")
    assert stores.observe(req).managed_connector_present is False

    orig_verify = stores._adapters.security.verify_machine_json

    def reject_connector_dacl(path: Path, service_name: str) -> None:
        if path == state_path:
            raise LifecycleViolation("machine_state_untrusted", "broad reader on connector state.json")
        orig_verify(path, service_name)

    monkeypatch.setattr(stores._adapters.security, "verify_machine_json", reject_connector_dacl)
    assert stores.observe(req).managed_connector_present is True

    req_dom, mem_stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path / "dom-m2")
    plat = FakeUpgradePlatform(stores=mem_stores, source_revision=src_rev, target_revision=tgt_rev)
    lifecycle = replace(
        mem_stores.as_lifecycle_stores(),
        observer=SimpleNamespace(observe=lambda _r: stores.observe(req)),
    )
    with pytest.raises(LifecycleViolation) as exc_info:
        upgrade(lifecycle, req_dom, plat)
    assert exc_info.value.code == "upgrade_managed_connector_active"
    assert plat.backup_creates == 0
    assert plat.migration_calls == 0
    assert mem_stores.read().active_release_id == "1.2.1"

    dangling_machine = tmp_path / "dangling-machine"
    dangling_secrets = dangling_machine / "connectors" / "cloudflare" / "secrets"
    dangling_state = dangling_machine / "connectors" / "cloudflare" / "state.json"
    orig_lexists = fs_mod.os.path.lexists
    orig_reject = fs_mod.reject_reparse_components

    def fake_lexists(p) -> bool:
        if Path(p) in {dangling_secrets, dangling_state}:
            return True
        return orig_lexists(p)

    def fake_reject(p: Path) -> None:
        if p in {dangling_secrets, dangling_state}:
            raise LifecycleViolation("reparse_path", "dangling reparse point")
        orig_reject(p)

    monkeypatch.setattr(fs_mod.os.path, "lexists", fake_lexists)
    monkeypatch.setattr(fs_mod, "reject_reparse_components", fake_reject)
    assert not dangling_secrets.exists()
    assert fs_mod._managed_connector_present(dangling_machine, binding=binding_a) is True


def test_pass3_m3_fresh_upgrade_preserves_preexisting_target_release_directory(
    tmp_path: Path,
) -> None:
    app, program_data, stores, binding_a, _install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
    )
    stage_b, sha_b = _build_staged_release(
        app,
        release_id="1.3.0",
        schema_revision="20261101_0001",
        lifecycle_bytes=b"lifecycle-1.3.0",
    )
    preexisting_dir = app / "releases" / "1.3.0"
    preexisting_dir.mkdir(parents=True, exist_ok=True)
    sentinel = preexisting_dir / "foreign-sentinel.txt"
    sentinel.write_text("do-not-delete", encoding="utf-8")

    req_b = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{sha_b}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_a.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_b,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
    )
    verifier = WindowsShipmentVerifier(app, program_data)
    with pytest.raises(LifecycleViolation) as exc_info:
        verifier.verify_staged_release(req_b, staged_release_root=stage_b, require_target_absent=True)
    assert exc_info.value.code == "upgrade_target_release_exists"
    assert sentinel.read_text(encoding="utf-8") == "do-not-delete"

    req, mem_stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path / "domain")
    foreign_dir = Path(req.app_dir) / "releases" / req.target_release_id
    foreign_dir.mkdir(parents=True, exist_ok=True)
    foreign_file = foreign_dir / "keep-me.txt"
    foreign_file.write_text("preserved", encoding="utf-8")
    plat = FakeUpgradePlatform(stores=mem_stores, source_revision=src_rev, target_revision=tgt_rev)
    with pytest.raises(LifecycleViolation) as dom_exc:
        upgrade(mem_stores.as_lifecycle_stores(), req, plat)
    assert dom_exc.value.code == "upgrade_target_release_exists"
    assert plat.cleanup_calls == 0
    assert plat.backup_creates == 0
    assert foreign_file.read_text(encoding="utf-8") == "preserved"


def test_pass3_m4_cli_and_platform_reject_spoofed_roots_against_system_known_folders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes
    from ticketbox_lifecycle import upgrade_cli

    real_app = tmp_path / "Program Files" / "Ticketbox"
    real_pd = tmp_path / "ProgramData" / "Ticketbox"
    spoof_app = tmp_path / "SpoofApp" / "Ticketbox"
    spoof_pd = tmp_path / "SpoofPD" / "Ticketbox"
    stage_spoof = spoof_app.parent / "Ticketbox-UpgradeStage" / "1.3.0"
    stage_spoof.mkdir(parents=True, exist_ok=True)
    (stage_spoof / "release-manifest.json").write_text("{}", encoding="utf-8")

    req_spoof = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id="upgrade-" + ("2" * 64),
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(spoof_app),
        data_root=str(spoof_pd / "data"),
        program_data_root=str(spoof_pd),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="2" * 64,
    )
    platform = WindowsUpgradePlatform(
        SimpleNamespace(_mutex=ThreadMutex()),  # type: ignore[arg-type]
        _stopped_pg_runner(),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        staged_release_root=stage_spoof,
        expected_app_dir=real_app,
        expected_program_data_root=real_pd,
    )
    with pytest.raises(LifecycleViolation) as exc_info:
        platform.verify_staged_release(req_spoof)
    assert exc_info.value.code == "untrusted_install_root"

    req_path = tmp_path / "spoof-req.json"
    res_path = tmp_path / "spoof-res.json"
    req_path.write_text(json.dumps(asdict(req_spoof)), encoding="utf-8")
    monkeypatch.setattr(upgrade_cli, "ticketbox_install_root", lambda: real_app)
    monkeypatch.setattr(upgrade_cli, "ticketbox_program_data_root", lambda: real_pd)
    monkeypatch.setattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 1, raising=False)
    code = upgrade_cli.main([
        "upgrade",
        "--request",
        str(req_path),
        "--result",
        str(res_path),
        "--staged-release-root",
        str(stage_spoof),
    ])
    assert code == 2
    payload = json.loads(res_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "untrusted_install_root"

    req_spoof_pd = replace(req_spoof, app_dir=str(real_app))
    req_path.write_text(json.dumps(asdict(req_spoof_pd)), encoding="utf-8")
    code_pd = upgrade_cli.main([
        "upgrade",
        "--request",
        str(req_path),
        "--result",
        str(res_path),
        "--staged-release-root",
        str(stage_spoof),
    ])
    assert code_pd == 2
    payload_pd = json.loads(res_path.read_text(encoding="utf-8"))
    assert payload_pd["ok"] is False
    assert payload_pd["code"] == "untrusted_setup_request"

    import sys
    if sys.platform == "win32":
        from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
        from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter

        user_writable_stage = real_app.parent / "Ticketbox-UpgradeStage" / "1.3.0"
        user_writable_stage.mkdir(parents=True, exist_ok=True)
        real_sec = WindowsSecurityAdapter(_stopped_pg_runner(), WindowsFileSecurity())
        with pytest.raises(LifecycleViolation) as stage_acl_exc:
            real_sec.verify_upgrade_stage_directory(user_writable_stage)
        assert stage_acl_exc.value.code == "untrusted_stage_root"

        req_real = replace(req_spoof, app_dir=str(real_app), data_root=str(real_pd / "data"), program_data_root=str(real_pd))
        plat_real = WindowsUpgradePlatform(
            SimpleNamespace(_mutex=ThreadMutex()),  # type: ignore[arg-type]
            _stopped_pg_runner(),
            real_sec,
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            staged_release_root=user_writable_stage,
            expected_app_dir=real_app,
            expected_program_data_root=real_pd,
        )
        with pytest.raises(LifecycleViolation) as plat_acl_exc:
            plat_real.verify_staged_release(req_real)
        assert plat_acl_exc.value.code == "untrusted_stage_root"


def test_pass3_m7_shortcut_rejects_s_false_and_readback_mismatch_and_cleans_on_coinit_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from ticketbox_lifecycle.runtime import windows_shortcut as ws

    if sys.platform != "win32":
        pytest.skip("Windows COM shortcut contract only")

    lnk = tmp_path / "Manager.lnk"
    lnk.write_bytes(b"original-working-shortcut")
    target = tmp_path / "releases" / "1.3.0" / "manager" / "ticketbox-manager.exe"
    icon = tmp_path / "ticketbox.ico"

    orig_vtable = ws._vtable_call

    def s_false_on_save(interface, index, restype, *argtypes):
        fn = orig_vtable(interface, index, restype, *argtypes)
        if index == 6 and len(argtypes) == 2 and argtypes[0] is ws.ctypes.c_wchar_p:
            return lambda *_args: 1
        return fn

    monkeypatch.setattr(ws, "_vtable_call", s_false_on_save)
    with pytest.raises(LifecycleError) as save_exc:
        ws.write_shortcut(lnk, target_path=target, working_dir=target.parent, icon_path=icon)
    assert save_exc.value.code == "shortcut_update_failed"
    assert "IPersistFile.Save" in save_exc.value.message
    assert lnk.read_bytes() == b"original-working-shortcut"
    assert list(tmp_path.glob("*.tmp")) == []

    monkeypatch.undo()

    def fail_coinit() -> bool:
        raise LifecycleError("shortcut_com_init_failed", "simulated COM init error")

    monkeypatch.setattr(ws, "_co_initialize", fail_coinit)
    with pytest.raises(LifecycleError) as init_exc:
        ws.write_shortcut(lnk, target_path=target, working_dir=target.parent, icon_path=icon)
    assert init_exc.value.code == "shortcut_com_init_failed"
    assert lnk.read_bytes() == b"original-working-shortcut"
    assert list(tmp_path.glob("*.tmp")) == []

    monkeypatch.undo()
    monkeypatch.setattr(
        ws,
        "read_shortcut",
        lambda _p: {
            "target": str(tmp_path / "wrong.exe"),
            "working_dir": str(target.parent),
            "icon": str(icon),
            "icon_index": 0,
            "app_user_model_id": MANAGER_APP_ID,
        },
    )
    with pytest.raises(LifecycleError) as rb_exc:
        ws.write_shortcut(lnk, target_path=target, working_dir=target.parent, icon_path=icon)
    assert rb_exc.value.code == "shortcut_update_failed"
    assert "readback" in rb_exc.value.message
    assert lnk.read_bytes() == b"original-working-shortcut"
    assert list(tmp_path.glob("*.tmp")) == []

    monkeypatch.setattr(
        ws,
        "read_shortcut",
        lambda _p: {
            "target": str(target),
            "working_dir": str(target.parent),
            "icon": str(icon),
            "icon_index": 1,
            "app_user_model_id": MANAGER_APP_ID,
        },
    )
    with pytest.raises(LifecycleError) as idx_exc:
        ws.write_shortcut(lnk, target_path=target, working_dir=target.parent, icon_path=icon)
    assert idx_exc.value.code == "shortcut_update_failed"
    assert "readback" in idx_exc.value.message
    assert lnk.read_bytes() == b"original-working-shortcut"
    assert list(tmp_path.glob("*.tmp")) == []


def test_pass3_s1_pre_replace_commit_publish_failure_reports_release_activated_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTempSecurity:
        def __init__(self) -> None:
            self.fail_temp = False

        def verify_machine_json(self, path: Path, *_args) -> None:
            if self.fail_temp and path.name != "active.json":
                raise LifecycleViolation("machine_state_untrusted", "pre-replace temp ACL failed")

        def protect_machine_json(self, *_args) -> None:
            pass

        def grant_backend_binding_read(self, *_args) -> None:
            pass

        def verify_binding_json(self, *_args) -> None:
            pass

        def prepare_operation_store(self, *_args) -> None:
            pass

        def verify(self, *_args) -> None:
            pass

    sec = FailingTempSecurity()
    req, mem_stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    adapters.security = sec  # type: ignore[assignment]
    fs_stores = FilesystemStores(
        tmp_path / "programdata" / "machine",
        "TicketboxBackend",
        adapters,
        ThreadMutex(),
    )
    fs_stores.publish(mem_stores.read())

    orig_publish_active = fs_stores.publish_active

    def fail_temp_on_committed(op: ActiveOperation) -> None:
        if op.phase == "committed":
            sec.fail_temp = True
        orig_publish_active(op)

    monkeypatch.setattr(fs_stores, "publish_active", fail_temp_on_committed)

    lifecycle = replace(
        fs_stores.as_lifecycle_stores(),
        shipment=mem_stores,
        observer=mem_stores,
        operations_write=fs_stores,
        operations_read=fs_stores,
        binding_read=fs_stores,
        binding_write=fs_stores,
    )
    plat = FakeUpgradePlatform(stores=mem_stores, source_revision=src_rev, target_revision=tgt_rev)
    plat.stores = SimpleNamespace(  # type: ignore[assignment]
        mutex=SimpleNamespace(_lock=SimpleNamespace(locked=lambda: True)),
        read_active=fs_stores.read_active,
        adapters=adapters,
        bind_and_verify=mem_stores.bind_and_verify,
    )
    result = upgrade(lifecycle, req, plat)
    assert result.ok is False
    assert result.phase == "release_activated"
    assert result.installation_published is True
    sec.fail_temp = False
    persisted = fs_stores.read_active()
    assert persisted is not None
    assert persisted.phase == "release_activated"


def test_codex_ntfs_materialized_and_shared_program_acls_grant_users_and_local_service_rx(
    tmp_path: Path,
) -> None:
    import os
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows NTFS ACL verification only")

    from ticketbox_lifecycle.runtime import windows_dacl
    from ticketbox_lifecycle.runtime import windows_security_native as native

    current_sid = native.current_process_user_sid()
    assert current_sid is not None
    private_stage_dir_sddl = f"D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{current_sid})"
    private_stage_file_sddl = f"D:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{current_sid})"

    app, program_data, _stores, binding_a, _install_a = _build_physical_installation(
        tmp_path,
        release_id="1.2.1",
        schema_revision="20261029_0002",
        lifecycle_bytes=b"lifecycle-1.2.1",
    )
    stage_b, sha_b = _build_staged_release(
        app,
        release_id="1.3.0",
        schema_revision="20261101_0001",
        lifecycle_bytes=b"lifecycle-1.3.0",
        vcredist_bytes=b"vcredist-1.3.0",
        ico_bytes=b"ico-1.3.0",
    )
    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="upgrade",
        operation_id=f"upgrade-{sha_b}",
        request_hash="pending",
        target_release_id="1.3.0",
        app_dir=str(app),
        data_root=binding_a.data_root,
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=sha_b,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
    )

    def _reset_writable(root: Path) -> None:
        if not root.exists():
            return
        for current, dirs, files in os.walk(root, topdown=False, followlinks=False):
            current_path = Path(current)
            for name in files:
                windows_dacl.apply_protected_dacl(current_path / name, private_stage_file_sddl, code="cleanup")
            for name in dirs:
                windows_dacl.apply_protected_dacl(current_path / name, private_stage_dir_sddl, code="cleanup")
        windows_dacl.apply_protected_dacl(root, private_stage_dir_sddl, code="cleanup")

    try:
        windows_dacl.apply_protected_dacl(stage_b.parent, private_stage_dir_sddl, code="test")
        for current, dirs, files in os.walk(stage_b, topdown=True, followlinks=False):
            current_path = Path(current)
            windows_dacl.apply_protected_dacl(current_path, private_stage_dir_sddl, code="test")
            for name in dirs:
                windows_dacl.apply_protected_dacl(current_path / name, private_stage_dir_sddl, code="test")
            for name in files:
                windows_dacl.apply_protected_dacl(current_path / name, private_stage_file_sddl, code="test")

        probe_src = stage_b / "_raw_move_probe.tmp"
        probe_dst = app / "_raw_move_probe.dst"
        probe_src.write_bytes(b"probe")
        windows_dacl.apply_protected_dacl(probe_src, private_stage_file_sddl, code="test")
        os.replace(probe_src, probe_dst)
        raw_moved_sddl = native._object_dacl_sddl(probe_dst)
        assert ";;;BU)" not in raw_moved_sddl and ";;;LS)" not in raw_moved_sddl
        with pytest.raises(LifecycleViolation) as raw_exc:
            native.verify_installed_program_acl(probe_dst, is_dir=False, require_admin_owner=False)
        assert raw_exc.value.code == "installed_program_acl_untrusted"
        probe_dst.unlink()

        verifier = WindowsShipmentVerifier(app, program_data)

        def _verify_no_admin_owner(path: Path, *, is_dir: bool) -> None:
            native.verify_installed_program_acl(path, is_dir=is_dir, require_admin_owner=False)

        verifier.materialize_staged_release(
            request,
            staged_release_root=stage_b,
            publish_acl=native.publish_installed_program_acl,
            verify_acl=_verify_no_admin_owner,
        )
        verifier.sync_staged_shared_payload(
            request,
            staged_release_root=stage_b,
            allowed_sibling_releases=frozenset({"1.2.1"}),
            publish_acl=native.publish_installed_program_acl,
            verify_acl=_verify_no_admin_owner,
        )

        expected_dir = native._canonical_dacl_sddl(native.INSTALLED_PROGRAM_DIR_SDDL)
        expected_file = native._canonical_dacl_sddl(native.INSTALLED_PROGRAM_FILE_SDDL)
        for directory in (
            app / "releases" / "1.3.0",
            app / "releases" / "1.3.0" / "backend",
            app / "releases" / "1.3.0" / "manager",
            app / "releases" / "1.3.0" / "connector",
            app / "releases" / "1.3.0" / "lifecycle",
            app / "bin" / "lifecycle",
        ):
            observed = native._object_dacl_sddl(directory)
            assert observed == expected_dir
            assert "(A;OICI;0x1200a9;;;BU)" in observed
            assert "(A;OICI;0x1200a9;;;LS)" in observed
            assert "(A;OICI;0x1200a9;;;AC)" in observed

        for file_path in (
            app / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe",
            app / "releases" / "1.3.0" / "manager" / "ticketbox-manager.exe",
            app / "releases" / "1.3.0" / "connector" / "cloudflared.exe",
            app / "releases" / "1.3.0" / "lifecycle" / "TicketboxLifecycle.exe",
            app / "releases" / "1.3.0" / "release-manifest.json",
            app / "bin" / "lifecycle" / "TicketboxLifecycle.exe",
            app / "bin" / "vc_redist.x64.exe",
            app / "ticketbox.ico",
        ):
            observed = native._object_dacl_sddl(file_path)
            assert observed == expected_file
            assert "(A;;0x1200a9;;;BU)" in observed
            assert "(A;;0x1200a9;;;LS)" in observed
            assert "(A;;0x1200a9;;;AC)" in observed

        manager_exe = app / "releases" / "1.3.0" / "manager" / "ticketbox-manager.exe"
        windows_dacl.apply_protected_dacl(
            manager_exe,
            "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BU)(A;;0x1200a9;;;LS)(A;;0x1200a9;;;AC)",
            code="test",
        )
        with pytest.raises(LifecycleViolation) as write_exc:
            native.verify_installed_program_acl(manager_exe, is_dir=False, require_admin_owner=False)
        assert write_exc.value.code == "installed_program_acl_untrusted"
    finally:
        _reset_writable(app)
        _reset_writable(stage_b.parent)


def test_u1_migration_boundary_failure_rolls_back_to_121_and_reopens_services(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path, restore_epoch=2)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="migrate_before_commit",
    )

    result = upgrade(stores.as_lifecycle_stores(), request, platform, rollback_on_failure=True)

    assert result.ok is False
    assert result.phase == "rolled_back_to_previous"
    assert result.code == "upgrade_failed_restored_previous"
    assert result.installation_published is True
    assert result.restored_release_id == "1.2.1"
    assert result.restore_epoch == 3
    assert result.pairing_code == "87654321"
    assert result.quarantine_path and Path(result.quarantine_path).is_dir()
    assert stores.read_active() is None
    restored = stores.read()
    assert restored is not None
    assert restored.active_release_id == "1.2.1"
    assert restored.dataset_id == DATASET_ID
    assert restored.install_id != INSTALL_ID
    assert restored.expected_restore_epoch == 3
    assert adapters.scm.autostart_enabled is True
    assert platform.live_revision == src_rev
    assert "quarantine_failed_upgrade" in platform.events
    assert "restore_previous_from_backup" in platform.events
    assert "verify_previous_candidate_health" in platform.events
    assert "verify_previous_normal_health" in platform.events
    assert stores.history[-1].kind == "restore"


def test_u1_candidate_health_failure_rolls_back_to_121_and_preserves_backup(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    adapters.dataset.fail_on = "health"

    result = upgrade(stores.as_lifecycle_stores(), request, platform, rollback_on_failure=True)

    assert result.ok is False
    assert result.phase == "rolled_back_to_previous"
    assert result.code == "upgrade_failed_restored_previous"
    assert result.restored_release_id == "1.2.1"
    assert stores.read().active_release_id == "1.2.1"
    assert stores.read().expected_restore_epoch == 1
    assert adapters.scm.autostart_enabled is True
    assert Path(result.details["backup_path"]).is_file()


def test_u1_standalone_rollback_upgrade_recovers_fenced_pre_write_candidate(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="rebind_scm",
    )

    failed = upgrade(stores.as_lifecycle_stores(), request, platform, rollback_on_failure=False)
    assert failed.ok is False
    assert failed.phase == "failed_recoverable"
    active = stores.read_active()
    assert isinstance(active, UpgradeOperation)
    assert active.no_return_point is True
    assert active.business_writes_opened is False

    platform.fail_at = None
    rb_request = replace(request, command="rollback-upgrade")
    rolled_back = rollback_upgrade(stores.as_lifecycle_stores(), rb_request, platform)

    assert rolled_back.ok is False
    assert rolled_back.phase == "rolled_back_to_previous"
    assert rolled_back.code == "upgrade_failed_restored_previous"
    assert rolled_back.installation_published is True
    assert stores.read().active_release_id == "1.2.1"
    assert stores.read().expected_restore_epoch == 1
    assert stores.read_active() is None
    assert adapters.scm.autostart_enabled is True


@pytest.mark.parametrize("case", ["writes_opened", "committed_phase", "post_commit_health_fail", "unreadable_state"])
def test_u1_refuses_rollback_when_business_writes_may_have_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)

    if case == "post_commit_health_fail":
        orig_normal = platform.verify_normal_health

        def fail_normal(_req):
            raise LifecycleError("normal_health_timeout", "post-commit normal health failed")

        monkeypatch.setattr(platform, "verify_normal_health", fail_normal)
        post_fail = upgrade(stores.as_lifecycle_stores(), request, platform, rollback_on_failure=True)
        assert post_fail.ok is False
        assert post_fail.phase == "committed"
        assert post_fail.installation_published is True
        assert stores.read().active_release_id == "1.3.0"
        monkeypatch.setattr(platform, "verify_normal_health", orig_normal)
    elif case in {"writes_opened", "committed_phase"}:
        failed = upgrade(stores.as_lifecycle_stores(), request, FakeUpgradePlatform(
            stores=stores, source_revision=src_rev, target_revision=tgt_rev, fail_at="rebind_scm",
        ))
        assert failed.phase == "failed_recoverable"
        active = stores.read_active()
        assert isinstance(active, UpgradeOperation)
        mutated = (
            replace(active, business_writes_opened=True)
            if case == "writes_opened"
            else replace(active, phase="committed", completed_step="health", business_writes_opened=True)
        )
        stores.publish_active(mutated)
    else:
        monkeypatch.setattr(stores, "read_active", lambda: (_ for _ in ()).throw(OSError("disk unreadable")))

    refused = rollback_upgrade(
        stores.as_lifecycle_stores(),
        replace(request, command="rollback-upgrade"),
        platform,
    )
    assert refused.ok is False
    assert refused.code == "upgrade_rollback_refused_writes_may_have_opened"
    assert "restore_previous_from_backup" not in platform.events
    if case == "post_commit_health_fail":
        assert stores.read().active_release_id == "1.3.0"


def test_u1_rollback_midway_failure_stays_fenced_and_preserves_backup(tmp_path: Path) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="rollback_restore",
    )
    _adapters.dataset.fail_on = "health"

    result = upgrade(stores.as_lifecycle_stores(), request, platform, rollback_on_failure=True)

    assert result.ok is False
    assert result.code == "upgrade_failed_fenced"
    assert result.phase == "failed_recoverable"
    assert result.installation_published is False
    assert Path(platform.last_backup_path).is_file()


def test_u1_supported_source_release_policy_enforces_121_to_130_span(tmp_path: Path) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(
        tmp_path,
        old_release="1.2.0",
        new_release="1.3.0",
    )
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    with pytest.raises(LifecycleViolation) as exc_info:
        upgrade(stores.as_lifecycle_stores(), request, platform)
    assert exc_info.value.code == "upgrade_source_release_unsupported"


@pytest.mark.parametrize("subcommand", [
    "upgrade",
    "rollback-upgrade",
    "restore",
    "uninstall",
    "reinstall",
    "purge-data",
])
def test_rev32_lifecycle_cli_subcommands_expose_help(subcommand: str, capsys) -> None:
    with pytest.raises(SystemExit) as exited:
        lifecycle_main([subcommand, "--help"])
    assert exited.value.code == 0
    out = capsys.readouterr().out
    assert "usage: TicketboxLifecycle" in out


def test_u1_rollback_verifies_real_121_health_without_mode_headers_and_checks_restore_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.policy.health_attestation import sign_challenge
    from ticketbox_lifecycle.runtime import windows_dataset as wd_mod
    from ticketbox_lifecycle.runtime.command import CompletedCommand
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
    from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform

    request, stores, _adapters, src_rev, _tgt_rev = _make_upgrade_fixture(tmp_path)
    prev_req = replace(
        request,
        command="restore",
        target_release_id="1.2.1",
        install_id="33333333-3333-4333-8333-333333333333",
        dataset_id=DATASET_ID,
        schema_revision=src_rev,
        health_attestation_key="9" * 64,
    )

    # Real 1.2.1 /api/health signs X-Ticketbox-Health-Attestation ONLY (zero 1.3.0 mode headers).
    def fake_121_health(_port: int, *, challenge: str):
        body = json.dumps({
            "contract": "ticketbox-installation-health-v3",
            "status": "ok",
            "product": "Ticketbox",
            "backend_version": "1.2.1",
            "installation_id": prev_req.install_id,
            "runtime_access_state": "available",
            "owner_state": "configured",
            "owner_recovery_channel": "managed_host",
            "mobile_connectivity": {},
        }).encode("utf-8")
        return 200, body, sign_challenge(prev_req.health_attestation_key, challenge)

    def fail_mode_endpoint(*_args, **_kwargs):
        raise AssertionError("real 1.2.1 rollback must not require 1.3.0 mode headers")

    live_epoch = {"value": 1}

    def fake_run_psql(_runner, _req, query: str, **_kw):
        if "||" in query:
            return CompletedCommand(
                ("psql",),
                0,
                f"{DATASET_ID}|{prev_req.install_id}|{live_epoch['value']}\n",
                "",
            )
        return CompletedCommand(("psql",), 0, f"{DATASET_ID}\n", "")

    monkeypatch.setattr(wd_mod, "fetch_installation_health", fake_121_health)
    monkeypatch.setattr(wd_mod, "fetch_installation_health_with_mode", fail_mode_endpoint)
    monkeypatch.setattr(wd_mod, "run_psql", fake_run_psql)

    dataset = WindowsDatasetAdapter(SimpleNamespace(), SimpleNamespace())
    platform = WindowsUpgradePlatform(
        stores,  # type: ignore[arg-type]
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        dataset,
        expected_app_dir=Path(request.app_dir),
        expected_program_data_root=Path(request.program_data_root),
    )
    platform.verify_previous_candidate_health(prev_req, expected_restore_epoch=1)
    platform.verify_previous_normal_health(prev_req, expected_restore_epoch=1)

    live_epoch["value"] = 0
    with pytest.raises(LifecycleError) as epoch_exc:
        platform.verify_previous_normal_health(prev_req, expected_restore_epoch=1)
    assert epoch_exc.value.code == "health_identity_mismatch"


def test_u1_rollback_restores_partially_replaced_shared_payload_and_passes_verify_installed(
    tmp_path: Path,
) -> None:
    import zipfile

    from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
    from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier

    app_dir = tmp_path / "app"
    program_data = tmp_path / "programdata"
    a_files = {
        "postgresql/bin/postgres.exe": b"pg17-a",
        "bin/lifecycle/TicketboxLifecycle.exe": b"lifecycle-1.2.1-original",
        "bin/vc_redist.x64.exe": b"vcredist-1.2.1",
        "ticketbox.ico": b"icon-1.2.1",
        "releases/1.2.1/backend/ticketbox-backend.exe": b"backend-1.2.1",
    }
    for rel, content in a_files.items():
        path = app_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    manifest_a = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.2.1",
        "product_version": "1.2.1",
        "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261029_0002",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for rel, data in sorted(a_files.items())
            ],
        },
    }
    manifest_a_bytes = json.dumps(manifest_a).encode("utf-8")
    manifest_a_path = app_dir / "releases" / "1.2.1" / "release-manifest.json"
    manifest_a_path.write_bytes(manifest_a_bytes)
    manifest_a_sha = hashlib.sha256(manifest_a_bytes).hexdigest()

    # Build a verified pre-upgrade cold copy of A.
    archive_path = program_data / "backups" / "pre-upgrade.tbxcold"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    members: dict[str, bytes] = {
        "data/pgdata/PG_VERSION": b"17\n",
        "data/pgdata/global/pg_control": b"pg-ctrl",
        "data/app/.env": b"TICKETBOX_ENV=1\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "expected_restore_epoch": 0,
            "active_release_id": "1.2.1",
            "release_manifest_sha256": manifest_a_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"pw1",
        "machine/secrets/ticketbox_migrator.password": b"pw2",
        "machine/secrets/ticketbox_runtime.password": b"pw3",
        "machine/secrets/pgpass": b"pgpass",
        f"machine/operations/history/fresh-{manifest_a_sha}.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "operation_id": f"fresh-{manifest_a_sha}",
            "kind": "install",
            "phase": "committed",
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "target_release_id": "1.2.1",
            "release_manifest_sha256": manifest_a_sha,
        }).encode("utf-8"),
        "program/releases/1.2.1/release-manifest.json": manifest_a_bytes,
        **{f"program/{rel}": data for rel, data in a_files.items()},
    }
    entries: dict[str, dict[str, object] | None] = {
        "program/": None,
        "machine/": None,
        "data/pgdata/": None,
        "data/attachments/": None,
        "data/app/": None,
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for d in entries:
            zf.writestr(d, b"")
        for name, data in sorted(members.items()):
            zf.writestr(name, data)
            entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        zf.writestr("COLD_COPY.json", json.dumps({
            "schema": "ticketbox-beta-cold-copy-v2",
            "complete": True,
            "public_connectivity": {
                "excluded_directory": "machine/connectors/cloudflare/secrets",
                "credentials": "not_backed_up",
                "after_restore": "configure_again",
            },
            "identity": {
                "install_id": INSTALL_ID,
                "dataset_id": DATASET_ID,
                "restore_epoch": 0,
                "release_id": "1.2.1",
                "release_manifest_sha256": manifest_a_sha,
                "schema_revision": "20261029_0002",
                "postgres_major": 17,
            },
            "entries": entries,
        }).encode("utf-8"))
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    # Simulate partial shared-payload sync failure: B overwrote bin/lifecycle + icon and added extra DLL.
    (app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe").write_bytes(b"corrupted-1.3.0-half-sync")
    (app_dir / "bin" / "lifecycle" / "extra-b.dll").write_bytes(b"extra-from-b")
    (app_dir / "ticketbox.ico").write_bytes(b"icon-1.3.0")

    verifier = WindowsShipmentVerifier(app_dir, program_data)
    binding_a = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=0,
        data_root=str(program_data / "data"),
        active_release_id="1.2.1",
        previous_release_id=None,
        release_manifest_sha256=manifest_a_sha,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )
    with pytest.raises(LifecycleViolation):
        verifier.verify_installed(binding_a, allowed_sibling_releases=frozenset())

    prev_req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="restore",
        operation_id=f"restore-{manifest_a_sha}",
        request_hash="pending",
        target_release_id="1.2.1",
        app_dir=str(app_dir),
        data_root=str(program_data / "data"),
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=manifest_a_sha,
        schema_revision="20261029_0002",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    acl_calls: list[tuple[str, str]] = []
    with archive_path.open("rb") as stream:
        source = ColdRestoreSource(stream, archive_sha, prev_req)
        restored = source.restore_shared_program_files(
            app_dir,
            temp_root=program_data / "quarantine" / "shared-tmp",
            publish_acl=lambda p, *, is_dir=False: acl_calls.append(("publish", p.name)),
            verify_acl=lambda p, *, is_dir=False: acl_calls.append(("verify", p.name)),
        )

    assert "bin/lifecycle/TicketboxLifecycle.exe" in restored
    assert "ticketbox.ico" in restored
    assert not (app_dir / "bin" / "lifecycle" / "extra-b.dll").exists()
    assert (app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe").read_bytes() == b"lifecycle-1.2.1-original"
    assert (app_dir / "ticketbox.ico").read_bytes() == b"icon-1.2.1"
    assert any(kind == "publish" for kind, _ in acl_calls)
    assert any(kind == "verify" for kind, _ in acl_calls)
    verifier.verify_installed(binding_a, allowed_sibling_releases=frozenset())


def test_standalone_rollback_upgrade_rejects_mismatched_operation_id_and_request_hash(tmp_path: Path) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="rebind_scm",
    )
    failed = upgrade(stores.as_lifecycle_stores(), request, platform)
    assert failed.ok is False and failed.phase == "failed_recoverable"

    # Stale/different operation_id must be refused without touching active upgrade.
    wrong_op = rollback_upgrade(
        stores.as_lifecycle_stores(),
        replace(request, command="rollback-upgrade", operation_id="upgrade-stale-other-id"),
        platform,
    )
    assert wrong_op.ok is False
    assert wrong_op.code == "operation_conflict"
    assert "quarantine_failed_upgrade" not in platform.events

    # Tampered request field (e.g. pg_port / request_hash) must be refused with request_mismatch.
    tampered = rollback_upgrade(
        stores.as_lifecycle_stores(),
        replace(request, command="rollback-upgrade", pg_port=5439),
        platform,
    )
    assert tampered.ok is False
    assert tampered.code == "request_mismatch"
    assert "quarantine_failed_upgrade" not in platform.events


def test_cli_result_path_guard_refuses_backup_in_tree_and_existing_non_result_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle import command_io, purge_data_cli, upgrade_cli
    from ticketbox_lifecycle.schemas import CommandResult

    app_dir = tmp_path / "app"
    program_data = tmp_path / "programdata"
    data_root = program_data / "data"
    app_dir.mkdir(parents=True)
    data_root.mkdir(parents=True)

    backup_file = tmp_path / "external-backup.tbxcold"
    backup_bytes = b"UNIQUE-PRE-UPGRADE-BACKUP-DO-NOT-OVERWRITE"
    backup_file.write_bytes(backup_bytes)

    enc_backup = tmp_path / "cloud-copy.tbxenc"
    enc_bytes = b"ENCRYPTED-BACKUP-DO-NOT-OVERWRITE"
    enc_backup.write_bytes(enc_bytes)

    other_json = tmp_path / "user-config.json"
    other_json_bytes = b'{"my_app": "precious"}\n'
    other_json.write_bytes(other_json_bytes)

    req_file = tmp_path / "req.json"
    req_file.write_text(json.dumps({
        "schema": REQUEST_SCHEMA,
        "command": "upgrade",
        "operation_id": "upgrade-" + "a" * 64,
        "request_hash": "pending",
        "target_release_id": "1.3.0",
        "app_dir": str(app_dir),
        "data_root": str(data_root),
        "program_data_root": str(program_data),
        "pg_service_name": "TicketboxPg",
        "backend_service_name": "TicketboxBackend",
        "pg_port": 5432,
        "backend_port": 8000,
        "postgres_major": 17,
        "release_manifest_sha256": "a" * 64,
    }), encoding="utf-8")

    monkeypatch.setattr(upgrade_cli, "require_windows", lambda: None)
    monkeypatch.setattr(upgrade_cli.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    monkeypatch.setattr(upgrade_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(upgrade_cli, "ticketbox_program_data_root", lambda: program_data)

    for bad_target in (backup_file, enc_backup, other_json, data_root / "res.json"):
        rc = upgrade_cli.main(["upgrade", "--request", str(req_file), "--result", str(bad_target)])
        assert rc == 2

    monkeypatch.setattr(purge_data_cli, "require_windows", lambda: None)
    monkeypatch.setattr(purge_data_cli.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)), raising=False)
    monkeypatch.setattr(purge_data_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(purge_data_cli, "ticketbox_program_data_root", lambda: program_data)

    for bad_target in (backup_file, enc_backup, other_json, program_data / "backups" / "res.json"):
        rc = purge_data_cli.main([
            "purge-data",
            "--dataset-id", DATASET_ID,
            "--confirm-dataset-id", DATASET_ID,
            "--external-backups-status", "preserved_outside",
            "--confirm-permanent-delete",
            "--result", str(bad_target),
        ])
        assert rc == 2

    # Not a single protected file was overwritten or truncated!
    assert backup_file.read_bytes() == backup_bytes
    assert enc_backup.read_bytes() == enc_bytes
    assert other_json.read_bytes() == other_json_bytes
    assert not (data_root / "res.json").exists()
    assert not (program_data / "backups" / "res.json").exists()

    # Overwriting a previous lifecycle result JSON outside forbidden roots IS allowed.
    ok_result = tmp_path / "setup-result.json"
    command_io.require_safe_result_path(
        ok_result,
        forbidden_roots=(app_dir, program_data, data_root),
        protected_files=(backup_file,),
    )
    command_io.write_result(
        ok_result,
        CommandResult(
            schema="ticketbox-lifecycle-result-v2",
            ok=False,
            command="upgrade",
            operation_id="op-1",
            phase="prepared",
            code="running",
            message="started",
            installation_published=None,
        ),
    )
    assert ok_result.is_file()


def test_u1_space_precheck_fails_before_stopping_services_for_zero_downtime(tmp_path: Path) -> None:
    request, stores, _adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(
        stores=stores,
        source_revision=src_rev,
        target_revision=tgt_rev,
        fail_at="backup_disk_space",
    )
    with pytest.raises(LifecycleError) as exc_info:
        upgrade(stores.as_lifecycle_stores(), request, platform)
    assert exc_info.value.code == "cold_space_insufficient"
    assert "check_backup_disk_space" in platform.events
    assert "stop_services" not in platform.events
    assert stores.read_active() is None


def test_u1_second_space_precheck_failure_does_not_fence_or_stop_running_previous_backend(tmp_path: Path) -> None:
    request, stores, adapters, src_rev, tgt_rev = _make_upgrade_fixture(tmp_path)
    platform = FakeUpgradePlatform(stores=stores, source_revision=src_rev, target_revision=tgt_rev)
    space_calls = 0

    def fail_on_second_space_check(req: InstallRequest, binding: InstallationBinding) -> None:
        nonlocal space_calls
        del req, binding
        space_calls += 1
        platform.events.append(f"check_backup_disk_space:{space_calls}")
        if space_calls == 2:
            raise LifecycleError("cold_space_insufficient", "volume filled before stopping services")

    platform.check_backup_disk_space = fail_on_second_space_check  # type: ignore[method-assign]
    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is False
    assert result.code == "cold_space_insufficient"
    assert space_calls == 2
    assert "stop_services" not in platform.events
    assert adapters.scm.fence_calls == 0


def test_u1_shared_payload_restore_enforces_same_volume_temp_dir_on_app_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import zipfile

    from ticketbox_lifecycle.runtime import windows_upgrade as wu_mod
    from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource

    app_dir = tmp_path / "pf" / "Ticketbox"
    program_data = tmp_path / "pd" / "Ticketbox"
    a_files = {
        "postgresql/bin/postgres.exe": b"pg17-a",
        "bin/lifecycle/TicketboxLifecycle.exe": b"lifecycle-a",
        "releases/1.2.1/backend/ticketbox-backend.exe": b"backend-a",
    }
    for rel, content in a_files.items():
        path = app_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest_a = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.2.1",
        "product_version": "1.2.1",
        "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261029_0002",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for rel, data in sorted(a_files.items())
            ],
        },
    }
    manifest_a_bytes = json.dumps(manifest_a).encode("utf-8")
    (app_dir / "releases" / "1.2.1" / "release-manifest.json").write_bytes(manifest_a_bytes)
    manifest_a_sha = hashlib.sha256(manifest_a_bytes).hexdigest()

    archive_path = program_data / "backups" / "pre-upgrade.tbxcold"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    members = {
        "data/pgdata/PG_VERSION": b"17\n",
        "data/pgdata/global/pg_control": b"pg-ctrl",
        "data/app/.env": b"TICKETBOX_ENV=1\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "expected_restore_epoch": 0,
            "active_release_id": "1.2.1",
            "release_manifest_sha256": manifest_a_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"pw1",
        "machine/secrets/ticketbox_migrator.password": b"pw2",
        "machine/secrets/ticketbox_runtime.password": b"pw3",
        "machine/secrets/pgpass": b"pgpass",
        f"machine/operations/history/fresh-{manifest_a_sha}.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "operation_id": f"fresh-{manifest_a_sha}",
            "kind": "install",
            "phase": "committed",
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "target_release_id": "1.2.1",
            "release_manifest_sha256": manifest_a_sha,
        }).encode("utf-8"),
        "program/releases/1.2.1/release-manifest.json": manifest_a_bytes,
        **{f"program/{rel}": data for rel, data in a_files.items()},
    }
    entries: dict[str, dict[str, object] | None] = {
        "program/": None, "machine/": None, "data/pgdata/": None, "data/attachments/": None, "data/app/": None,
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for d in entries:
            zf.writestr(d, b"")
        for name, data in sorted(members.items()):
            zf.writestr(name, data)
            entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        zf.writestr("COLD_COPY.json", json.dumps({
            "schema": "ticketbox-beta-cold-copy-v2",
            "complete": True,
            "public_connectivity": {
                "excluded_directory": "machine/connectors/cloudflare/secrets",
                "credentials": "not_backed_up",
                "after_restore": "configure_again",
            },
            "identity": {
                "install_id": INSTALL_ID,
                "dataset_id": DATASET_ID,
                "restore_epoch": 0,
                "release_id": "1.2.1",
                "release_manifest_sha256": manifest_a_sha,
                "schema_revision": "20261029_0002",
                "postgres_major": 17,
            },
            "entries": entries,
        }).encode("utf-8"))
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    prev_req = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="restore",
        operation_id=f"restore-{manifest_a_sha}",
        request_hash="pending",
        target_release_id="1.2.1",
        app_dir=str(app_dir),
        data_root=str(program_data / "data"),
        program_data_root=str(program_data),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256=manifest_a_sha,
        schema_revision="20261029_0002",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )

    # Cross-drive temp_root is rejected explicitly by ColdRestoreSource.
    with archive_path.open("rb") as stream:
        source = ColdRestoreSource(stream, archive_sha, prev_req)
        orig_splitdrive = os.path.splitdrive

        def fake_splitdrive(value: str):
            if "cross-vol" in value:
                return ("Z:", value[2:])
            return ("C:", value[2:])

        monkeypatch.setattr(os.path, "splitdrive", fake_splitdrive)
        try:
            with pytest.raises(LifecycleError) as cross_exc:
                source.restore_shared_program_files(app_dir, temp_root=tmp_path / "cross-vol" / "tmp")
            assert cross_exc.value.code == "rollback_temp_cross_volume"
        finally:
            monkeypatch.setattr(os.path, "splitdrive", orig_splitdrive)

    # WindowsUpgradePlatform places rollback temp_root under app_dir.parent/Ticketbox-UpgradeStage (never program_data).
    observed_temp_roots: list[Path] = []
    monkeypatch.setattr(wu_mod, "protect_directory", lambda *_a, **_kw: None)

    class _RecordingSource:
        digest = archive_sha

        def restore_shared_program_files(self, _app, *, temp_root: Path, **_kw):
            observed_temp_roots.append(temp_root)
            raise LifecycleError("stop_after_check", "inspected temp_root")

    class _FakeColdRestore:
        def __init__(self, _runner):
            pass

        def open_source(self, _req, _path, _sha):
            from contextlib import nullcontext
            return nullcontext(_RecordingSource())

    monkeypatch.setattr(wu_mod, "WindowsColdRestore", _FakeColdRestore)
    binding_a = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=0,
        data_root=str(program_data / "data"),
        active_release_id="1.2.1",
        previous_release_id=None,
        release_manifest_sha256=manifest_a_sha,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key=OLD_KEY,
    )
    active = UpgradeOperation(
        schema=OPERATION_SCHEMA,
        operation_id="upgrade-" + "a" * 64,
        kind="upgrade",
        request_hash="b" * 64,
        target_release_id="1.3.0",
        data_root=str(program_data / "data"),
        release_manifest_sha256="a" * 64,
        backend_port=8000,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="alembic",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="7" * 64,
        expected_restore_epoch=0,
        previous_release_id="1.2.1",
        previous_release_manifest_sha256=manifest_a_sha,
        source_schema_revision="20261029_0002",
        backup_path=str(archive_path),
        backup_sha256=archive_sha,
        business_writes_opened=False,
    )
    platform = wu_mod.WindowsUpgradePlatform(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        expected_app_dir=app_dir,
        expected_program_data_root=program_data,
    )
    with pytest.raises(LifecycleError, match="inspected temp_root"):
        platform.restore_previous_from_backup(
            prev_req,
            active,
            binding_a,
            new_install_id="44444444-4444-4444-8444-444444444444",
            rollback_operation_id=f"restore-{manifest_a_sha}",
            new_health_key="8" * 64,
            target_restore_epoch=1,
        )
    assert len(observed_temp_roots) == 1
    assert observed_temp_roots[0].parent == app_dir.parent / "Ticketbox-UpgradeStage"
    assert not observed_temp_roots[0].is_relative_to(program_data)
    assert not observed_temp_roots[0].exists()


def test_cli_result_path_guard_rejects_existing_zero_byte_json_and_corrupt_request_into_managed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle import upgrade_cli

    app_dir = tmp_path / "app"
    program_data = tmp_path / "programdata"
    (program_data / "data").mkdir(parents=True)
    app_dir.mkdir(parents=True)

    zero_json = tmp_path / "existing-empty.json"
    zero_json.write_bytes(b"")

    bad_req = tmp_path / "corrupt-req.json"
    bad_req.write_text("{not-valid-json", encoding="utf-8")

    monkeypatch.setattr(upgrade_cli, "require_windows", lambda: None)
    monkeypatch.setattr(
        upgrade_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(upgrade_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(upgrade_cli, "ticketbox_program_data_root", lambda: program_data)

    assert upgrade_cli.main(["upgrade", "--request", str(bad_req), "--result", str(zero_json)]) == 2
    assert zero_json.read_bytes() == b""

    in_managed = program_data / "data" / "sneaky-result.json"
    assert upgrade_cli.main(["upgrade", "--request", str(bad_req), "--result", str(in_managed)]) == 2
    assert not in_managed.exists()


def test_all_clis_fail_closed_without_writing_result_when_any_known_root_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ticketbox_lifecycle import (
        cli,
        purge_data_cli,
        reinstall_cli,
        restore_cli,
        uninstall_cli,
        upgrade_cli,
    )

    app_dir = tmp_path / "app"
    program_data = tmp_path / "programdata"
    app_dir.mkdir(parents=True)
    program_data.mkdir(parents=True)
    req_file = tmp_path / "req.json"
    req_file.write_text('{"schema":"ticketbox-lifecycle-request-v1"}\n', encoding="utf-8")
    source_copy = tmp_path / "backup.tbxcold"
    source_copy.write_bytes(b"cold")

    def _fail_root() -> Path:
        raise LifecycleViolation("program_data_unavailable", "known folder lookup failed")

    cli_cases = [
        (upgrade_cli, ["upgrade", "--request", str(req_file), "--result"]),
        (uninstall_cli, ["uninstall", "--request", str(req_file), "--result"]),
        (reinstall_cli, ["reinstall", "--request", str(req_file), "--result"]),
        (
            restore_cli,
            [
                "restore",
                "--request",
                str(req_file),
                "--source",
                str(source_copy),
                "--sha256",
                "a" * 64,
                "--source-isolated",
                "--result",
            ],
        ),
        (
            purge_data_cli,
            [
                "purge-data",
                "--dataset-id",
                "22222222-2222-4222-8222-222222222222",
                "--confirm-dataset-id",
                "22222222-2222-4222-8222-222222222222",
                "--external-backups-status",
                "preserved_outside",
                "--confirm-permanent-delete",
                "--result",
            ],
        ),
        (cli, ["install", "--request", str(req_file), "--result"]),
    ]

    for mod, base_argv in cli_cases:
        if hasattr(mod, "require_windows"):
            monkeypatch.setattr(mod, "require_windows", lambda: None)
        if hasattr(mod, "ctypes"):
            monkeypatch.setattr(
                mod.ctypes,
                "windll",
                SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
                raising=False,
            )

        # Install root resolves, ProgramData fails: must NOT create result inside app_dir.
        monkeypatch.setattr(mod, "ticketbox_install_root", lambda: app_dir)
        monkeypatch.setattr(mod, "ticketbox_program_data_root", _fail_root)
        evil_in_app = app_dir / f"evil-{mod.__name__.split('.')[-1]}.json"
        rc = mod.main([*base_argv, str(evil_in_app)])
        assert rc == 2
        assert not evil_in_app.exists()
        assert "forbidden_roots_unavailable" in capsys.readouterr().err

        # ProgramData resolves, install root fails: must NOT create result inside program_data.
        monkeypatch.setattr(mod, "ticketbox_install_root", _fail_root)
        monkeypatch.setattr(mod, "ticketbox_program_data_root", lambda: program_data)
        evil_in_pd = program_data / f"evil-{mod.__name__.split('.')[-1]}.json"
        rc_pd = mod.main([*base_argv, str(evil_in_pd)])
        assert rc_pd == 2
        assert not evil_in_pd.exists()
        assert "forbidden_roots_unavailable" in capsys.readouterr().err


def test_all_six_clis_resolve_known_roots_only_once_without_secondary_resolution_in_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle import (
        cli,
        purge_data_cli,
        reinstall_cli,
        restore_cli,
        uninstall_cli,
        upgrade_cli,
    )
    from ticketbox_lifecycle.runtime import filesystem_stores
    from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult

    app_dir = tmp_path / "app"
    program_data = tmp_path / "programdata"
    control_dir = tmp_path / "control"
    app_dir.mkdir(parents=True)
    program_data.mkdir(parents=True)
    control_dir.mkdir(parents=True)
    source_copy = tmp_path / "backup.tbxcold"
    source_copy.write_bytes(b"cold")

    monkeypatch.setattr(filesystem_stores, "ticketbox_control_root", lambda: control_dir)
    monkeypatch.setattr(
        filesystem_stores,
        "ticketbox_install_root",
        lambda: (_ for _ in ()).throw(AssertionError("secondary ticketbox_install_root resolution forbidden")),
    )
    monkeypatch.setattr(
        filesystem_stores,
        "ticketbox_program_data_root",
        lambda: (_ for _ in ()).throw(AssertionError("secondary ticketbox_program_data_root resolution forbidden")),
    )

    def _ok_result(command: str) -> CommandResult:
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=True,
            command=command,  # type: ignore[arg-type]
            operation_id="op-single-shot",
            phase="committed",
            code="committed",
            message="ok",
            installation_published=True,
        )

    def _write_req(command: str) -> Path:
        req_file = tmp_path / f"req-{command}.json"
        req_file.write_text(
            json.dumps({
                "schema": "ticketbox-lifecycle-request-v1",
                "command": command,
                "operation_id": "op-single-shot",
                "request_hash": "a" * 64,
                "target_release_id": "1.3.0",
                "app_dir": str(app_dir),
                "data_root": str(program_data / "data"),
                "program_data_root": str(program_data),
                "pg_service_name": "TicketboxPg",
                "backend_service_name": "TicketboxBackend",
                "pg_port": 5432,
                "backend_port": 8000,
                "postgres_major": 17,
                "release_manifest_sha256": "b" * 64,
            }),
            encoding="utf-8",
        )
        return req_file

    monkeypatch.setattr(cli, "install_or_resume", lambda stores, _req: (assert_shipment(stores), _ok_result("install"))[1])
    monkeypatch.setattr(cli, "finalize_install_result", lambda res, _stores: res)
    monkeypatch.setattr(upgrade_cli.upgrade_action, "upgrade", lambda stores, _req, _plat, **_kw: (assert_shipment(stores), _ok_result("upgrade"))[1])
    monkeypatch.setattr(uninstall_cli.uninstall_action, "uninstall", lambda stores, _req, _plat: (assert_shipment(stores), _ok_result("uninstall"))[1])
    monkeypatch.setattr(reinstall_cli.reinstall_action, "reinstall", lambda stores, _req, _plat: (assert_shipment(stores), _ok_result("reinstall"))[1])
    monkeypatch.setattr(restore_cli.restore_action, "restore", lambda stores, *_args, **_kw: (assert_shipment(stores), _ok_result("restore"))[1])
    monkeypatch.setattr(purge_data_cli, "purge_data", lambda stores, _req, _plat: (assert_shipment(stores), _ok_result("purge-data"))[1])

    def assert_shipment(stores) -> None:
        assert stores.shipment._expected_app_dir == app_dir
        assert stores.shipment._expected_program_data_root == program_data

    cases = [
        (cli, ["install", "--request", str(_write_req("install")), "--result", str(tmp_path / "res-install.json")]),
        (upgrade_cli, ["upgrade", "--request", str(_write_req("upgrade")), "--result", str(tmp_path / "res-upgrade.json")]),
        (uninstall_cli, ["uninstall", "--request", str(_write_req("uninstall")), "--result", str(tmp_path / "res-uninstall.json")]),
        (reinstall_cli, ["reinstall", "--request", str(_write_req("reinstall")), "--result", str(tmp_path / "res-reinstall.json")]),
        (
            restore_cli,
            [
                "restore",
                "--request",
                str(_write_req("restore")),
                "--source",
                str(source_copy),
                "--sha256",
                "a" * 64,
                "--source-isolated",
                "--result",
                str(tmp_path / "res-restore.json"),
            ],
        ),
        (
            purge_data_cli,
            [
                "purge-data",
                "--dataset-id",
                "22222222-2222-4222-8222-222222222222",
                "--confirm-dataset-id",
                "22222222-2222-4222-8222-222222222222",
                "--external-backups-status",
                "preserved_outside",
                "--confirm-permanent-delete",
                "--result",
                str(tmp_path / "res-purge.json"),
            ],
        ),
    ]

    for mod, argv in cases:
        counts = {"install": 0, "program_data": 0}

        def _count_install(c=counts) -> Path:
            c["install"] += 1
            return app_dir

        def _count_pd(c=counts) -> Path:
            c["program_data"] += 1
            return program_data

        if hasattr(mod, "require_windows"):
            monkeypatch.setattr(mod, "require_windows", lambda: None)
        if hasattr(mod, "ctypes"):
            monkeypatch.setattr(
                mod.ctypes,
                "windll",
                SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
                raising=False,
            )
        monkeypatch.setattr(mod, "ticketbox_install_root", _count_install)
        monkeypatch.setattr(mod, "ticketbox_program_data_root", _count_pd)
        assert mod.main(argv) == 0
        assert counts == {"install": 1, "program_data": 1}, f"{mod.__name__} resolved roots more than once: {counts}"
