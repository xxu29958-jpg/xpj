"""Shared fakes, fixtures, and physical-installation builders for Windows upgrade lifecycle tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

from fakes import MemoryStores, RecordingAdapterBundle
from ticketbox_lifecycle.adapters.upgrade import (
    PreUpgradeBackup,
    RollbackRestoreResult,
    UpgradeMigrationResult,
)
from ticketbox_lifecycle.domain.binding import binding_from_request
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_shipment import expected_upgrade_stage_root
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

        setattr(stores.adapters.scm, "apply", tracking_scm_apply)
        setattr(stores.adapters.scm, "fence_backend", tracking_fence)

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
            outcome=cast(Literal["target_committed", "target_observed_after_interruption"], outcome),
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
