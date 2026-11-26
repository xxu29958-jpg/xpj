"""Tests for Rev3.2 §9.6–§9.8: controlled default uninstall, preserved-data reinstall, and standalone purge-data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.domain.planner import plan_fresh_install
from ticketbox_lifecycle.domain.purge_data import PurgeDataRequest, purge_data
from ticketbox_lifecycle.domain.reinstall import reinstall
from ticketbox_lifecycle.domain.restore import restore
from ticketbox_lifecycle.domain.uninstall import uninstall
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_purge_data import WindowsPurgeDataPlatform
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    ActiveOperation,
    InstallationBinding,
    InstallRequest,
)

INSTALL_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "22222222-2222-4222-8222-222222222222"


def _installed_fixture(tmp_path: Path, *, release_id: str = "1.3.0") -> tuple[InstallRequest, MemoryStores, RecordingAdapterBundle, InstallationBinding]:
    import shutil

    base = make_install_request(tmp_path)
    app_dir = Path(base.app_dir)
    if base.target_release_id != release_id:
        stale_default = app_dir / "releases" / base.target_release_id
        if stale_default.exists():
            shutil.rmtree(stale_default)
    manifest_path = app_dir / "releases" / release_id / "release-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
    }).encode("utf-8")
    manifest_path.write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()

    program_data = Path(base.program_data_root)
    data_root = Path(base.data_root)
    for rel, content in (
        ("pgdata/PG_VERSION", b"17\n"),
        ("pgdata/base/facts", b"preserved-financial-facts"),
        ("attachments/originals/receipt.jpg", b"preserved-receipt-original"),
        ("app/uploads/receipt.jpg", b"preserved-upload-original"),
        ("app/.env", b"TICKETBOX_ENV=1\n"),
    ):
        target = data_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (program_data / "backups").mkdir(parents=True, exist_ok=True)
    (program_data / "backups" / "pre-upgrade.tbxcold").write_bytes(b"pre-upgrade-backup")
    (program_data / "machine" / "secrets").mkdir(parents=True, exist_ok=True)
    (program_data / "machine" / "secrets" / "postgres.password").write_bytes(b"secret")
    (program_data / "machine" / "operations" / "history").mkdir(parents=True, exist_ok=True)
    (program_data / "machine" / "installation.json").write_text('{"placeholder":true}', encoding="utf-8")

    adapters = RecordingAdapterBundle()
    stores = MemoryStores(adapters, str(app_dir), str(data_root))
    stores.pgdata_present = True
    stores.pg_service_present = True
    stores.backend_service_present = True
    binding = InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        expected_restore_epoch=1,
        data_root=str(data_root),
        active_release_id=release_id,
        previous_release_id=None,
        release_manifest_sha256=sha,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key="c" * 64,
    )
    stores.publish(binding)
    req = replace(
        base,
        target_release_id=release_id,
        release_manifest_sha256=sha,
        schema_revision="20261101_0001",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )
    return req, stores, adapters, binding


def test_default_uninstall_unregisters_owned_services_and_preserves_all_data_backups_and_identity(tmp_path: Path) -> None:
    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    events: list[str] = []

    class FakeUninstallPlatform:
        def verify_owned_services(self, _req, _binding):
            events.append("verify_owned")

        def verify_registered_release_manifests(
            self,
            _req,
            _binding,
            *,
            release_ids,
            expected_manifests,
            resuming_cleanup=False,
        ):
            del resuming_cleanup
            assert expected_manifests["1.3.0"] == binding.release_manifest_sha256
            events.append(f"verify_manifests:{','.join(release_ids)}")

        def stop_and_unregister_services(self, _req, _binding):
            events.append("unregister_services")
            stores.pg_service_present = False
            stores.backend_service_present = False
            return ["TicketboxBackend", "TicketboxPg"]

        def remove_start_menu_shortcut(self, _req):
            events.append("remove_shortcut")
            return True

        def cleanup_registered_release_payloads(
            self,
            _req,
            _binding,
            *,
            release_ids,
            expected_manifests=None,
            resuming_cleanup=False,
        ):
            del expected_manifests, resuming_cleanup
            events.append(f"cleanup_releases:{','.join(release_ids)}")
            return list(release_ids)

    uninstall_req = replace(req, command="uninstall", operation_id=f"uninstall-{req.release_manifest_sha256}")
    result = uninstall(stores.as_lifecycle_stores(), uninstall_req, FakeUninstallPlatform())

    assert result.ok is True
    assert result.code == "uninstalled_data_preserved"
    assert result.phase == "committed"
    assert events == [
        "verify_owned",
        "verify_manifests:1.3.0",
        "unregister_services",
        "remove_shortcut",
        "cleanup_releases:1.3.0",
    ]
    assert result.details["removed_releases"] == ["1.3.0"]
    assert stores.read() == binding
    assert stores.read_active() is None
    assert stores.history[-1].kind == "uninstall"
    data_root = Path(req.data_root)
    assert (data_root / "pgdata" / "base" / "facts").read_bytes() == b"preserved-financial-facts"
    assert (data_root / "attachments" / "originals" / "receipt.jpg").read_bytes() == b"preserved-receipt-original"
    assert (Path(req.program_data_root) / "backups" / "pre-upgrade.tbxcold").read_bytes() == b"pre-upgrade-backup"


def test_uninstall_fails_closed_on_active_operation_missing_binding_or_foreign_service(tmp_path: Path) -> None:
    req, stores, _adapters, _binding = _installed_fixture(tmp_path)
    uninstall_req = replace(req, command="uninstall", operation_id=f"uninstall-{req.release_manifest_sha256}")

    class ForeignServicePlatform:
        def verify_owned_services(self, _req, _binding):
            raise LifecycleViolation("uninstall_foreign_service_refused", "foreign service")

        def verify_registered_release_manifests(
            self,
            _req,
            _binding,
            *,
            release_ids,
            expected_manifests,
            resuming_cleanup=False,
        ):
            del release_ids, expected_manifests, resuming_cleanup
            raise AssertionError("must not verify manifests after foreign service refusal")

        def stop_and_unregister_services(self, _req, _binding):
            raise AssertionError("must not unregister foreign services")

        def remove_start_menu_shortcut(self, _req):
            raise AssertionError("must not remove shortcut on foreign service")

        def cleanup_registered_release_payloads(
            self,
            _req,
            _binding,
            *,
            release_ids,
            expected_manifests=None,
            resuming_cleanup=False,
        ):
            del expected_manifests, resuming_cleanup
            raise AssertionError("must not clean releases on foreign service")

    with pytest.raises(LifecycleViolation) as foreign_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, ForeignServicePlatform())
    assert foreign_exc.value.code == "uninstall_foreign_service_refused"

    stores.operation_store_prepared = True
    stores.publish_active(ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id="other-op",
        kind="install",
        request_hash="a" * 64,
        target_release_id="1.3.0",
        data_root=req.data_root,
        release_manifest_sha256=req.release_manifest_sha256,
        backend_port=8000,
        phase="prepared",
        no_return_point=False,
        completed_step=None,
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="d" * 64,
    ))
    with pytest.raises(LifecycleViolation) as busy_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, ForeignServicePlatform())
    assert busy_exc.value.code == "uninstall_operation_active"

    stores._active = None
    stores._binding = None
    with pytest.raises(LifecycleViolation) as missing_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, ForeignServicePlatform())
    assert missing_exc.value.code == "uninstall_binding_missing"


def test_reinstall_preserves_data_and_identity_without_initdb_while_fresh_and_restore_stay_strict(tmp_path: Path) -> None:
    req, stores, adapters, binding = _installed_fixture(tmp_path)
    stores.pg_service_present = False
    stores.backend_service_present = False
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")
    events: list[str] = []

    class FakeReinstallPlatform:
        def publish_and_verify_program_acls(self, _req):
            events.append("program_acls")

        def verify_preserved_dataset(self, _req, _binding):
            events.append("verify_preserved_dataset")
            return {"verified_originals": 2}

        def verify_candidate_health(self, _req):
            events.append("candidate_health")

        def verify_normal_health(self, _req):
            events.append("normal_health")

        def update_start_menu_shortcut(self, _req):
            events.append("update_shortcut")

    # Fresh install MUST still refuse existing binding/pgdata.
    with pytest.raises(LifecycleViolation) as fresh_exc:
        plan_fresh_install(replace(req, command="install"), stores.observe(req))
    assert fresh_exc.value.code == "already_installed"

    # R1/R2 restore MUST still refuse non-empty target.
    with pytest.raises(LifecycleError) as restore_exc:
        restore(
            stores.as_lifecycle_stores(),
            replace(req, command="restore"),
            tmp_path / "copy.tbxcold",
            "a" * 64,
            SimpleNamespace(),
        )
    assert restore_exc.value.code == "restore_target_not_empty"

    # Narrow reinstall succeeds without initdb and preserves dataset_id, install_id, restore_epoch.
    reinstall_req = replace(req, command="reinstall", operation_id=f"reinstall-{req.release_manifest_sha256}")
    result = reinstall(stores.as_lifecycle_stores(), reinstall_req, FakeReinstallPlatform())

    assert result.ok is True
    assert result.code == "reinstalled_data_preserved"
    assert result.phase == "committed"
    assert result.client_generation == INSTALL_ID
    assert result.restore_epoch == 1
    assert "postgres_initdb" not in adapters.applied
    assert events == [
        "program_acls",
        "verify_preserved_dataset",
        "candidate_health",
        "update_shortcut",
        "normal_health",
    ]
    assert stores.read().install_id == binding.install_id
    assert stores.read().dataset_id == binding.dataset_id
    assert stores.read().expected_restore_epoch == binding.expected_restore_epoch
    assert adapters.scm.autostart_enabled is True
    assert stores.history[-1].kind == "reinstall"


def test_reinstall_refuses_orphan_pgdata_and_version_mismatch(tmp_path: Path) -> None:
    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    platform = SimpleNamespace()
    reinstall_req = replace(req, command="reinstall", operation_id=f"reinstall-{req.release_manifest_sha256}")

    # Version/manifest mismatch refused.
    stores._binding = replace(binding, active_release_id="1.2.1")
    with pytest.raises(LifecycleViolation) as ver_exc:
        reinstall(stores.as_lifecycle_stores(), reinstall_req, platform)
    assert ver_exc.value.code == "reinstall_version_mismatch"

    # Orphan pgdata without verified installation.json refused.
    stores._binding = None
    with pytest.raises(LifecycleViolation) as orphan_exc:
        reinstall(stores.as_lifecycle_stores(), reinstall_req, platform)
    assert orphan_exc.value.code == "reinstall_binding_missing"


def test_standalone_purge_data_requires_explicit_double_confirmation_and_never_touches_external_backups(
    tmp_path: Path,
) -> None:
    req, stores, _adapters, _binding = _installed_fixture(tmp_path)
    external_backup = tmp_path / "external-usb" / "keep-safe.tbxcold"
    external_backup.parent.mkdir(parents=True)
    external_backup.write_bytes(b"external-backup-must-survive")

    stopped_runner = SimpleNamespace(
        run=lambda argv, **_kw: CompletedCommand(tuple(argv), 1060, "", "service does not exist"),
    )
    running_runner = SimpleNamespace(
        run=lambda argv, **_kw: CompletedCommand(tuple(argv), 0, "STATE : 4 RUNNING", ""),
    )

    class MatchingDatasetVerifier:
        def verify_stopped_pgdata_dataset_id(self, binding, *, app_dir, program_data_root):
            del app_dir, program_data_root
            return {
                "dataset_id": binding.dataset_id,
                "client_generation": binding.install_id,
                "restore_epoch": binding.expected_restore_epoch,
            }

    class SwappedDatasetVerifier:
        def verify_stopped_pgdata_dataset_id(self, binding, *, app_dir, program_data_root):
            del app_dir, program_data_root
            return {
                "dataset_id": "99999999-9999-4999-8999-999999999999",
                "client_generation": binding.install_id,
                "restore_epoch": binding.expected_restore_epoch,
            }

    # Add undeclared user subdirs inside data_root and machine_root to prove no wildcard deletion.
    undeclared_data = Path(req.data_root) / "user-notes" / "keep.txt"
    undeclared_data.parent.mkdir(parents=True)
    undeclared_data.write_text("do-not-delete-user-dir", encoding="utf-8")
    undeclared_machine = Path(req.program_data_root) / "machine" / "custom-audit" / "keep.txt"
    undeclared_machine.parent.mkdir(parents=True)
    undeclared_machine.write_text("do-not-delete-audit", encoding="utf-8")

    # Mismatched double confirmation refused.
    with pytest.raises(LifecycleViolation) as mismatch_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-1",
                dataset_id=DATASET_ID,
                confirm_dataset_id=INSTALL_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert mismatch_exc.value.code == "purge_confirmation_mismatch"

    # Running services refused.
    with pytest.raises(LifecycleViolation) as running_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-2",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(running_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert running_exc.value.code == "purge_services_running"

    # Swapped pgdata belonging to dataset B refused even when installation.json says dataset A!
    with pytest.raises(LifecycleViolation) as swapped_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-swapped",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=SwappedDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert swapped_exc.value.code == "purge_dataset_identity_mismatch"
    assert (Path(req.data_root) / "pgdata" / "base" / "facts").is_file()

    # Valid standalone purge deletes ONLY declared subtrees and preserves undeclared subdirs & backups.
    result = purge_data(
        stores.as_lifecycle_stores(),
        PurgeDataRequest(
            operation_id="purge-3",
            dataset_id=DATASET_ID,
            confirm_dataset_id=DATASET_ID,
            external_backups_status="preserved_outside",
            confirm_permanent_delete=True,
            program_data_root=req.program_data_root,
        ),
        WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
    )
    assert result.ok is True
    assert result.code == "data_permanently_purged"
    assert result.installation_published is False
    assert result.details["external_backups_untouched"] is True
    assert result.details["verified_dataset_identity"]["dataset_id"] == DATASET_ID
    assert not (Path(req.data_root) / "pgdata").exists()
    assert not (Path(req.data_root) / "attachments").exists()
    assert not (Path(req.data_root) / "app").exists()
    assert not (Path(req.program_data_root) / "machine" / "installation.json").exists()
    assert not (Path(req.program_data_root) / "machine" / "secrets").exists()
    assert undeclared_data.read_text(encoding="utf-8") == "do-not-delete-user-dir"
    assert undeclared_machine.read_text(encoding="utf-8") == "do-not-delete-audit"
    assert (Path(req.program_data_root) / "backups" / "pre-upgrade.tbxcold").read_bytes() == b"pre-upgrade-backup"
    assert external_backup.read_bytes() == b"external-backup-must-survive"

    # Re-running without verified binding fails closed (stale registry/dir name cannot authorize).
    stores._binding = None
    with pytest.raises(LifecycleViolation) as unbound_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-4",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="none_confirmed",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert unbound_exc.value.code == "purge_binding_missing"


def test_windows_uninstall_verifies_connector_config_and_state_and_cleans_u1_releases(tmp_path: Path) -> None:
    from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform

    req, _stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    binding = replace(binding, previous_release_id="1.2.1")
    app_dir = Path(req.app_dir)

    # Create valid manifest-backed release 1.2.1 and U1-materialized release 1.3.0, plus shared bin/lifecycle.
    shared_lc = app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe"
    shared_lc.parent.mkdir(parents=True, exist_ok=True)
    shared_lc.write_bytes(b"shared-lifecycle-exe")
    manifest_shas: dict[str, str] = {}
    for rid in ("1.2.1", "1.3.0"):
        backend = app_dir / "releases" / rid / "backend" / "ticketbox-backend.exe"
        backend.parent.mkdir(parents=True, exist_ok=True)
        backend.write_bytes(f"backend-{rid}".encode())
        rel_path = f"releases/{rid}/backend/ticketbox-backend.exe"
        manifest = {
            "schema": "ticketbox-release-manifest-v1",
            "release_id": rid,
            "product_version": rid,
            "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
            "min_schema_revision": "20260722_0001",
            "max_schema_revision": "20261101_0001",
            "min_semantic_revision": "ticketbox-dataset-semantics-v1",
            "signing_state": "release-bound",
            "immutable_payload": {
                "algorithm": "SHA-256",
                "files": [
                    {
                        "path": rel_path,
                        "size": backend.stat().st_size,
                        "sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
                    },
                ],
            },
        }
        raw_manifest = json.dumps(manifest).encode("utf-8")
        (app_dir / "releases" / rid / "release-manifest.json").write_bytes(raw_manifest)
        manifest_shas[rid] = hashlib.sha256(raw_manifest).hexdigest()
    binding = replace(binding, release_manifest_sha256=manifest_shas["1.3.0"])

    conn_dir = Path(req.program_data_root) / "machine" / "connectors" / "cloudflare"
    secret_dir = conn_dir / "secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    owned_token = secret_dir / "credential-g2.token"
    owned_token.write_text("token", encoding="utf-8")
    conn_exe = app_dir / "releases" / "1.3.0" / "connector" / "cloudflared.exe"
    conn_cfg = app_dir / "releases" / "1.3.0" / "connector" / "config.json"

    def make_runner(present: set[str]):
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                return CompletedCommand(tuple(argv), 0 if argv[2] in present else 1060, "STATE : 1 STOPPED", "")
            return CompletedCommand(tuple(argv), 0, "", "")
        return SimpleNamespace(run=run)

    # Foreign connector using the SAME cloudflared.exe but a different config/token must be refused!
    foreign_observer = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(
            argv=(str(conn_exe), "--config", str(tmp_path / "other" / "config.json"), "tunnel", "run", "--token-file", str(tmp_path / "other.token")),
        )
    )
    platform_foreign = WindowsUninstallPlatform(make_runner({CONNECTOR_SERVICE_NAME}), foreign_observer)
    with pytest.raises(LifecycleViolation) as foreign_exc:
        platform_foreign.verify_owned_services(req, binding)
    assert foreign_exc.value.code == "uninstall_foreign_service_refused"

    # Connector with right argv but mismatched state.json dataset_id must also be refused!
    (conn_dir / "state.json").write_text(
        json.dumps({
            "install_id": INSTALL_ID,
            "dataset_id": "99999999-9999-4999-8999-999999999999",
            "expected_restore_epoch": 1,
            "credential_generation": 2,
        }),
        encoding="utf-8",
    )
    owned_observer = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(
            argv=(str(conn_exe), "--config", str(conn_cfg), "tunnel", "run", "--token-file", str(owned_token)),
        )
    )
    platform_owned = WindowsUninstallPlatform(make_runner({CONNECTOR_SERVICE_NAME}), owned_observer)
    with pytest.raises(LifecycleViolation) as bad_state_exc:
        platform_owned.verify_owned_services(req, binding)
    assert bad_state_exc.value.code == "uninstall_foreign_service_refused"

    # Missing, None, boolean, zero, or string credential_generation must be refused (never skipped).
    for bad_gen in (None, False, 0, "2"):
        bad_state: dict[str, object] = {
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "expected_restore_epoch": 1,
        }
        if bad_gen is not None:
            bad_state["credential_generation"] = bad_gen
        (conn_dir / "state.json").write_text(json.dumps(bad_state), encoding="utf-8")
        with pytest.raises(LifecycleViolation) as bad_gen_exc:
            platform_owned.verify_owned_services(req, binding)
        assert bad_gen_exc.value.code == "uninstall_foreign_service_refused"

    # Matching state.json passes connector ownership check!
    (conn_dir / "state.json").write_text(
        json.dumps({
            "install_id": INSTALL_ID,
            "dataset_id": DATASET_ID,
            "expected_restore_epoch": 1,
            "credential_generation": 2,
        }),
        encoding="utf-8",
    )
    platform_owned.verify_owned_services(req, binding)

    # Mismatched active manifest digest fails closed without deleting any release files.
    with pytest.raises(LifecycleViolation) as bad_manifest_exc:
        platform_owned.cleanup_registered_release_payloads(
            req,
            replace(binding, release_manifest_sha256="0" * 64),
            release_ids=("1.3.0", "1.2.1"),
            expected_manifests={"1.3.0": "0" * 64, "1.2.1": manifest_shas["1.2.1"]},
        )
    assert bad_manifest_exc.value.code == "uninstall_release_manifest_mismatch"
    assert (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").is_file()
    assert (app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe").is_file()

    # Cleanup with verified manifest digests removes non-active 1.2.1 FIRST, then active 1.3.0, while keeping bin/lifecycle & data.
    removed = platform_owned.cleanup_registered_release_payloads(
        req,
        binding,
        release_ids=("1.3.0", "1.2.1"),
        expected_manifests=manifest_shas,
    )
    assert removed == ["1.2.1", "1.3.0"]
    assert not (app_dir / "releases" / "1.3.0").exists()
    assert not (app_dir / "releases" / "1.2.1").exists()
    assert shared_lc.read_bytes() == b"shared-lifecycle-exe"
    assert (Path(req.data_root) / "pgdata" / "base" / "facts").is_file()

    # Missing active release manifest fails closed rather than silently succeeding.
    with pytest.raises(LifecycleViolation) as missing_manifest_exc:
        platform_owned.cleanup_registered_release_payloads(
            req,
            binding,
            release_ids=("1.3.0",),
            expected_manifests=manifest_shas,
        )
    assert missing_manifest_exc.value.code == "uninstall_release_manifest_missing"


def test_uninstall_verifies_manifests_before_unregistering_services_and_never_cleans_unverified_previous_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform
    from ticketbox_lifecycle.schemas import UpgradeOperation

    req, stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_shas: dict[str, str] = {}
    for rid in ("1.2.1", "1.3.0"):
        backend = app_dir / "releases" / rid / "backend" / "ticketbox-backend.exe"
        backend.parent.mkdir(parents=True, exist_ok=True)
        backend.write_bytes(f"backend-{rid}".encode())
        manifest = {
            "schema": "ticketbox-release-manifest-v1",
            "release_id": rid,
            "product_version": rid,
            "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
            "min_schema_revision": "20260722_0001",
            "max_schema_revision": "20261101_0001",
            "min_semantic_revision": "ticketbox-dataset-semantics-v1",
            "signing_state": "release-bound",
            "immutable_payload": {
                "algorithm": "SHA-256",
                "files": [
                    {
                        "path": f"releases/{rid}/backend/ticketbox-backend.exe",
                        "size": backend.stat().st_size,
                        "sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
                    },
                ],
            },
        }
        raw = json.dumps(manifest).encode("utf-8")
        (app_dir / "releases" / rid / "release-manifest.json").write_bytes(raw)
        manifest_shas[rid] = hashlib.sha256(raw).hexdigest()

    # Case 1: Active manifest mismatch MUST fail closed BEFORE stop_and_unregister_services runs!
    tampered_binding = replace(binding, release_manifest_sha256="f" * 64, previous_release_id="1.2.1")
    stores._binding = tampered_binding
    service_actions: list[tuple[str, ...]] = []

    def recording_run(argv, **_kw):
        if argv[0] == "sc.exe" and argv[1] == "query":
            return CompletedCommand(tuple(argv), 1060, "", "missing")
        service_actions.append(tuple(argv))
        return CompletedCommand(tuple(argv), 0, "", "")

    real_platform = WindowsUninstallPlatform(
        SimpleNamespace(run=recording_run),
        SimpleNamespace(observe=lambda _name: None),
        shortcut_remover=lambda: False,
    )
    unregister_called = False
    orig_stop = real_platform.stop_and_unregister_services

    def guarded_stop(*args, **kwargs):
        nonlocal unregister_called
        unregister_called = True
        return orig_stop(*args, **kwargs)

    real_platform.stop_and_unregister_services = guarded_stop  # type: ignore[method-assign]
    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id="uninstall-tampered",
        release_manifest_sha256="f" * 64,
    )
    with pytest.raises(LifecycleViolation) as mismatch_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, real_platform)
    assert mismatch_exc.value.code == "uninstall_release_manifest_mismatch"
    assert unregister_called is False
    assert service_actions == []
    assert stores.read_active() is None
    assert (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").is_file()
    assert (app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe").is_file()

    # Case 2: Direct call with a release ID lacking an expected SHA-256 MUST fail closed (never skip digest check).
    valid_binding = replace(binding, release_manifest_sha256=manifest_shas["1.3.0"], previous_release_id="1.2.1")
    stores._binding = valid_binding
    req = replace(req, release_manifest_sha256=manifest_shas["1.3.0"])
    with pytest.raises(LifecycleViolation) as unverified_exc:
        real_platform.verify_registered_release_manifests(
            req,
            valid_binding,
            release_ids=("1.3.0", "1.2.1"),
            expected_manifests={"1.3.0": manifest_shas["1.3.0"]},
        )
    assert unverified_exc.value.code == "uninstall_release_manifest_unverified"
    assert (app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe").is_file()

    # Case 3: Uninstall with previous_release_id in binding, NO history digest, and 1.2.1 STILL ON DISK
    # MUST fail closed BEFORE unregistering services so Inno's uninstall log cannot delete unverified 1.2.1!
    unregister_called = False
    with pytest.raises(LifecycleViolation) as prev_unverified_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-no-prev-digest"),
            real_platform,
        )
    assert prev_unverified_exc.value.code == "uninstall_release_manifest_unverified"
    assert unregister_called is False
    assert (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").is_file()
    assert (app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe").is_file()

    # Case 3b: An unregistered release directory on disk under {app}/releases MUST fail closed BEFORE unregistering services!
    rogue_dir = app_dir / "releases" / "orphan-1.0.0"
    rogue_dir.mkdir(parents=True)
    (rogue_dir / "stale.txt").write_text("unregistered", encoding="utf-8")
    with pytest.raises(LifecycleViolation) as rogue_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-rogue-release"),
            real_platform,
        )
    assert rogue_exc.value.code == "uninstall_unregistered_release_present"
    assert unregister_called is False
    (rogue_dir / "stale.txt").unlink()
    rogue_dir.rmdir()

    # Case 3c: Conflicting history digests for the same release MUST fail closed BEFORE unregistering services!
    stores._history.append(
        UpgradeOperation(
            schema=OPERATION_SCHEMA,
            operation_id="upgrade-conflict-1",
            kind="upgrade",
            request_hash="a" * 64,
            target_release_id="1.3.0",
            data_root=req.data_root,
            release_manifest_sha256="e" * 64,
            backend_port=8000,
            phase="committed",
            no_return_point=True,
            completed_step="post_upgrade_health",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="d" * 64,
            previous_release_id="1.2.1",
            previous_release_manifest_sha256=manifest_shas["1.2.1"],
        )
    )
    with pytest.raises(LifecycleViolation) as conflict_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-conflict-digest"),
            real_platform,
        )
    assert conflict_exc.value.code == "uninstall_release_manifest_mismatch"
    assert unregister_called is False
    stores._history.clear()

    # Case 4: When committed upgrade history provides previous_release_manifest_sha256:
    stores._history.append(
        UpgradeOperation(
            schema=OPERATION_SCHEMA,
            operation_id="upgrade-121-to-130",
            kind="upgrade",
            request_hash="a" * 64,
            target_release_id="1.3.0",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
            backend_port=8000,
            phase="committed",
            no_return_point=True,
            completed_step="post_upgrade_health",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="d" * 64,
            previous_release_id="1.2.1",
            previous_release_manifest_sha256=manifest_shas["1.2.1"],
        )
    )

    # Case 4a: Tampered payload file inside old release 1.2.1 MUST fail closed BEFORE unregistering services!
    old_backend = app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe"
    orig_old_bytes = old_backend.read_bytes()
    old_backend.write_bytes(b"tampered-1.2.1")
    unregister_called = False
    with pytest.raises(LifecycleViolation) as file_hash_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-tampered-file"),
            real_platform,
        )
    assert file_hash_exc.value.code == "uninstall_release_file_hash_mismatch"
    assert unregister_called is False
    assert old_backend.is_file()

    # Case 4a-ii: Missing manifest-listed payload file on FIRST uninstall (resuming_cleanup=False)
    # MUST fail closed BEFORE unregistering services!
    old_backend.unlink()
    unregister_called = False
    with pytest.raises(LifecycleViolation) as missing_payload_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-missing-payload-file"),
            real_platform,
        )
    assert missing_payload_exc.value.code == "uninstall_release_file_missing"
    assert unregister_called is False
    old_backend.write_bytes(orig_old_bytes)

    # Case 4b: Unexpected extra file outside manifest inside 1.2.1 MUST fail closed BEFORE unregistering services!
    extra_file = app_dir / "releases" / "1.2.1" / "unexpected-extra.txt"
    extra_file.write_text("untracked-by-manifest", encoding="utf-8")
    unregister_called = False
    with pytest.raises(LifecycleViolation) as extra_file_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-unexpected-file"),
            real_platform,
        )
    assert extra_file_exc.value.code == "uninstall_release_unexpected_file"
    assert unregister_called is False
    assert extra_file.is_file()
    extra_file.unlink()

    # Case 4b-ii: Unreadable subdirectory during os.walk MUST invoke onerror and fail closed BEFORE unregistering services!
    import os as _os
    import sys as _sys

    from ticketbox_lifecycle.runtime import windows_uninstall as wu_mod

    real_walk = _os.walk

    def failing_walk(top, *args, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "locked-subdir")))
        return iter(())

    monkeypatch.setattr(wu_mod.os, "walk", failing_walk)
    unregister_called = False
    with pytest.raises(LifecycleViolation) as unreadable_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-unreadable-subdir"),
            real_platform,
        )
    assert unreadable_exc.value.code == "uninstall_release_unreadable"
    assert unregister_called is False
    monkeypatch.setattr(wu_mod.os, "walk", real_walk)

    # Case 4b-iii: Running uninstall from inside releases/<rid> (including 8.3 short-path / samefile alias)
    # MUST fail closed BEFORE unregistering services!
    monkeypatch.setattr(_sys, "executable", str(app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe"))
    unregister_called = False
    with pytest.raises(LifecycleViolation) as from_rel_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-from-release"),
            real_platform,
        )
    assert from_rel_exc.value.code == "uninstall_running_from_release_dir"
    assert unregister_called is False

    # Alias path that differs lexically from release_dir (modeling Windows 8.3 short name) but matches via samefile:
    alias_dir = tmp_path / "SHORT~1"
    alias_dir.mkdir(exist_ok=True)
    alias_exe = alias_dir / "backend" / "ticketbox-backend.exe"
    alias_exe.parent.mkdir(parents=True, exist_ok=True)
    alias_exe.write_bytes(b"alias")
    real_samefile = _os.path.samefile
    release_130 = app_dir / "releases" / "1.3.0"

    def alias_samefile(a, b):
        if Path(a) == alias_dir and Path(b) == release_130:
            return True
        return real_samefile(a, b)

    monkeypatch.setattr(_sys, "executable", str(alias_exe))
    monkeypatch.setattr(wu_mod.os.path, "samefile", alias_samefile)
    unregister_called = False
    with pytest.raises(LifecycleViolation) as alias_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-from-short-alias"),
            real_platform,
        )
    assert alias_exc.value.code == "uninstall_running_from_release_dir"
    assert unregister_called is False
    monkeypatch.undo()

    # Case 4b-iv: Non-active 1.2.1 cleans FIRST; if active 1.3.0 fails during bottom-up subdir walk,
    # 1.2.1 is already removed and 1.3.0's release-manifest.json stays intact on disk so retrying with
    # the SAME operation_id after permission recovery succeeds and commits!
    def fail_active_bottom_up_walk(top, *args, topdown=True, onerror=None, **kwargs):
        if not topdown and Path(top).name == "1.3.0" and onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "backend")))
            return iter(())
        return real_walk(top, *args, topdown=topdown, onerror=onerror, **kwargs)

    monkeypatch.setattr(wu_mod.os, "walk", fail_active_bottom_up_walk)
    first_try = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-retryable-walk"),
        real_platform,
    )
    assert first_try.ok is False
    assert first_try.phase == "failed_recoverable"
    assert first_try.code == "uninstall_release_unreadable"
    assert not (app_dir / "releases" / "1.2.1").exists()
    assert (app_dir / "releases" / "1.3.0" / "release-manifest.json").is_file()
    monkeypatch.setattr(wu_mod.os, "walk", real_walk)

    # Case 4c: Retrying with the SAME operation_id after permission recovery cleans remaining 1.3.0 and commits!
    result_with_history = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-retryable-walk"),
        real_platform,
    )
    assert result_with_history.ok is True
    assert result_with_history.phase == "committed"
    assert result_with_history.details["removed_releases"] == ["1.3.0"]
    assert not (app_dir / "releases" / "1.3.0").exists()
    assert not (app_dir / "releases" / "1.2.1").exists()

    # Case 4d: Even if active 1.3.0 was already removed before a mid-cleanup failure on 1.2.1 (no_return_point=True),
    # retrying with the SAME operation_id verifies and removes remaining 1.2.1 and commits!
    backend_121 = app_dir / "releases" / "1.2.1" / "backend" / "ticketbox-backend.exe"
    backend_121.parent.mkdir(parents=True, exist_ok=True)
    backend_121.write_bytes(b"backend-1.2.1")
    manifest_121 = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.2.1",
        "product_version": "1.2.1",
        "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                {
                    "path": "releases/1.2.1/backend/ticketbox-backend.exe",
                    "size": backend_121.stat().st_size,
                    "sha256": hashlib.sha256(backend_121.read_bytes()).hexdigest(),
                },
            ],
        },
    }
    raw_121 = json.dumps(manifest_121).encode("utf-8")
    (app_dir / "releases" / "1.2.1" / "release-manifest.json").write_bytes(raw_121)
    assert hashlib.sha256(raw_121).hexdigest() == manifest_shas["1.2.1"]
    from ticketbox_lifecycle.schemas import UninstallOperation

    stores.operation_store_prepared = True
    stores.publish_active(
        UninstallOperation(
            schema=OPERATION_SCHEMA,
            operation_id="uninstall-active-already-gone",
            kind="uninstall",
            request_hash="a" * 64,
            target_release_id="1.3.0",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
            backend_port=8000,
            phase="failed_recoverable",
            no_return_point=True,
            completed_step="unregister_services",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="d" * 64,
            expected_restore_epoch=1,
        )
    )
    resumed_after_active_gone = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-active-already-gone"),
        real_platform,
    )
    assert resumed_after_active_gone.ok is True
    assert resumed_after_active_gone.phase == "committed"
    assert resumed_after_active_gone.details["removed_releases"] == ["1.2.1"]
    assert not (app_dir / "releases" / "1.2.1").exists()

    # Case 4e: Single-version release where release-manifest.json was unlinked right before rmdir() failed,
    # leaving an empty release_dir under no_return_point=True -> SAME operation_id retry rmdirs and commits!
    empty_active = app_dir / "releases" / "1.3.0"
    empty_active.mkdir(parents=True, exist_ok=True)
    stores.publish_active(
        UninstallOperation(
            schema=OPERATION_SCHEMA,
            operation_id="uninstall-empty-after-manifest-unlink",
            kind="uninstall",
            request_hash="a" * 64,
            target_release_id="1.3.0",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
            backend_port=8000,
            phase="failed_recoverable",
            no_return_point=True,
            completed_step="unregister_services",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="d" * 64,
            expected_restore_epoch=1,
        )
    )
    resumed_empty = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-empty-after-manifest-unlink"),
        real_platform,
    )
    assert resumed_empty.ok is True
    assert resumed_empty.phase == "committed"
    assert resumed_empty.details["removed_releases"] == ["1.3.0"]
    assert not empty_active.exists()

    # Case 4f: When {app}/releases exists as a REGULAR FILE (not a directory), resuming_cleanup=True
    # MUST fail closed rather than returning [] and committing!
    releases_as_file = app_dir / "releases"
    assert not releases_as_file.exists()
    releases_as_file.write_text("not-a-directory", encoding="utf-8")
    stores.publish_active(
        UninstallOperation(
            schema=OPERATION_SCHEMA,
            operation_id="uninstall-releases-is-file",
            kind="uninstall",
            request_hash="a" * 64,
            target_release_id="1.3.0",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
            backend_port=8000,
            phase="failed_recoverable",
            no_return_point=True,
            completed_step="unregister_services",
            install_id=INSTALL_ID,
            dataset_id=DATASET_ID,
            schema_revision="20261101_0001",
            health_attestation_key="d" * 64,
            expected_restore_epoch=1,
        )
    )
    with pytest.raises(LifecycleViolation) as releases_file_exc:
        uninstall(
            stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id="uninstall-releases-is-file"),
            real_platform,
        )
    assert releases_file_exc.value.code == "uninstall_release_manifest_missing"
    assert releases_as_file.is_file()
    releases_as_file.unlink()
    stores._active = None

    # Case 5: When previous_release_id has no history digest and 1.2.1 is ALREADY absent on disk, uninstall succeeds for 1.3.0.
    stores._history.clear()
    backend_130 = app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe"
    backend_130.parent.mkdir(parents=True, exist_ok=True)
    backend_130.write_bytes(b"backend-1.3.0")
    manifest_130 = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": "1.3.0",
        "product_version": "1.3.0",
        "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                {
                    "path": "releases/1.3.0/backend/ticketbox-backend.exe",
                    "size": backend_130.stat().st_size,
                    "sha256": hashlib.sha256(backend_130.read_bytes()).hexdigest(),
                },
            ],
        },
    }
    raw_130 = json.dumps(manifest_130).encode("utf-8")
    (app_dir / "releases" / "1.3.0" / "release-manifest.json").write_bytes(raw_130)
    sha_130 = hashlib.sha256(raw_130).hexdigest()
    stores._binding = replace(valid_binding, release_manifest_sha256=sha_130)
    result_absent_prev = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-absent-prev", release_manifest_sha256=sha_130),
        real_platform,
    )
    assert result_absent_prev.ok is True
    assert result_absent_prev.details["removed_releases"] == ["1.3.0"]


def test_purge_data_stopped_pgdata_probe_writes_ephemeral_port_matched_pgpass_and_cleans_up(
    tmp_path: Path,
) -> None:
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    runtime_secret = "rt-pass:with\\colon-001"
    (secrets_dir / "ticketbox_runtime.password").write_text(runtime_secret + "\n", encoding="ascii")
    static_pgpass = secrets_dir / "pgpass"
    static_pgpass.write_text(
        f"127.0.0.1:5432:ticketbox:ticketbox_runtime:{runtime_secret}\n",
        encoding="ascii",
    )

    observed: dict[str, object] = {}
    returned_dataset = {"id": DATASET_ID}

    def fake_run(argv, *, env=None, **_kw):
        exe_name = Path(argv[0]).name.lower()
        if exe_name == "pg_controldata.exe":
            return CompletedCommand(
                tuple(argv),
                0,
                "Database cluster state:               shut down\n"
                "Database system identifier:           7123456789012345678\n",
                "",
            )
        if exe_name == "pg_ctl.exe":
            if "start" in argv:
                opts = argv[argv.index("-o") + 1]
                observed["pg_ctl_opts"] = opts
                assert "default_transaction_read_only=on" in opts
            elif "stop" in argv:
                observed["stopped"] = True
            return CompletedCommand(tuple(argv), 0, "", "")
        if exe_name == "psql.exe":
            port = argv[argv.index("-p") + 1]
            pgpass_path = Path(env["PGPASSFILE"])
            observed["psql_port"] = port
            observed["pgpass_path"] = pgpass_path
            observed["pgpass_text"] = pgpass_path.read_text(encoding="ascii")
            assert "PGPASSWORD" not in env
            assert runtime_secret not in " ".join(argv)
            assert pgpass_path != static_pgpass
            return CompletedCommand(
                tuple(argv),
                0,
                f"{returned_dataset['id']}|{binding.install_id}|{binding.expected_restore_epoch}\n",
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(SimpleNamespace(run=fake_run), SimpleNamespace())
    verified = adapter.verify_stopped_pgdata_dataset_id(
        binding,
        app_dir=app_dir,
        program_data_root=program_data,
    )
    assert verified == {
        "dataset_id": DATASET_ID,
        "client_generation": binding.install_id,
        "restore_epoch": binding.expected_restore_epoch,
    }
    ephemeral_port = observed["psql_port"]
    assert f"-p {ephemeral_port}" in str(observed["pg_ctl_opts"])
    expected_entry = f"127.0.0.1:{ephemeral_port}:ticketbox:ticketbox_runtime:rt-pass\\:with\\\\colon-001"
    assert expected_entry in str(observed["pgpass_text"])
    assert observed["stopped"] is True
    assert not Path(observed["pgpass_path"]).exists()
    assert not Path(observed["pgpass_path"]).parent.exists()

    # Swapped dataset B in stopped pgdata must fail closed and still clean up ephemeral pgpass!
    returned_dataset["id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(LifecycleViolation) as mismatch_exc:
        adapter.verify_stopped_pgdata_dataset_id(
            binding,
            app_dir=app_dir,
            program_data_root=program_data,
        )
    assert mismatch_exc.value.code == "purge_dataset_identity_mismatch"
    assert not Path(observed["pgpass_path"]).exists()
    assert not Path(observed["pgpass_path"]).parent.exists()


def test_purge_data_probe_creates_pgpass_before_start_and_stops_on_psql_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    # 1) If mkdtemp fails, pg_ctl start must NEVER be invoked.
    events: list[str] = []

    class TrackingRunner:
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    events.append(f"start:{Path(argv[0]).name}")
                    return CompletedCommand(tuple(argv), 0, "", "")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

        def run(self, argv, **_kw):
            exe = Path(argv[0]).name.lower()
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            if exe == "psql.exe":
                events.append("psql_raise")
                raise LifecycleError("command_outcome_unknown", "psql timed out")
            if exe == "pg_ctl.exe" and "stop" in argv:
                events.append("pg_ctl_stop")
                return CompletedCommand(tuple(argv), 0, "", "")
            raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(TrackingRunner(), SimpleNamespace())
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kw: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert events == []

    # 2) If psql raises, pg_ctl stop STILL runs, job closes, and ephemeral pgpass dir is removed.
    monkeypatch.setattr(tempfile, "mkdtemp", real_mkdtemp)
    with pytest.raises(LifecycleError) as exc_info:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert exc_info.value.code == "command_outcome_unknown"
    assert events == ["job_enter", "start:pg_ctl.exe", "psql_raise", "pg_ctl_stop", "job_exit"]
    assert list(secrets_dir.glob("purge-probe-*")) == []


def test_purge_data_probe_stops_on_pg_ctl_start_failure_or_timeout_and_temporarily_grants_then_restores_pgdata_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime import windows_security_native as native
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    caller_sid = "S-1-5-21-1000-2000-3000-1001"
    sealed_dacl = (
        "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )
    events: list[str] = []
    start_mode = {"value": "nonzero"}

    monkeypatch.setattr(pgdata_security.os, "name", "nt")
    monkeypatch.setattr(native, "current_process_user_sid", lambda: caller_sid)
    monkeypatch.setattr(native, "_object_dacl_sddl", lambda _p: sealed_dacl)
    monkeypatch.setattr(native, "file_owner_sid", lambda _p: native.ADMINISTRATORS_SID)
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda _p, sddl, *, code: events.append(f"dacl:{code}:{sddl}"),
    )

    class ProbeRunner:
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    events.append("pg_ctl_start")
                    if start_mode["value"] == "nonzero":
                        return CompletedCommand(tuple(argv), 1, "", "timed out waiting for server")
                    if start_mode["value"] == "timeout":
                        raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")
                    return CompletedCommand(tuple(argv), 0, "", "")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

        def run(self, argv, **_kw):
            exe = Path(argv[0]).name.lower()
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            if exe == "pg_ctl.exe" and "stop" in argv:
                events.append("pg_ctl_stop")
                return CompletedCommand(tuple(argv), 0, "", "")
            if exe == "psql.exe":
                events.append("psql_ok")
                return CompletedCommand(
                    tuple(argv),
                    0,
                    f"{DATASET_ID}|{binding.install_id}|{binding.expected_restore_epoch}\n",
                    "",
                )
            raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(ProbeRunner(), SimpleNamespace())

    # 1) pg_ctl start returns non-zero (e.g. -w -t 30 wait timeout): MUST still run pg_ctl stop before job_exit AND restore exact DACL!
    with pytest.raises(LifecycleViolation) as nonzero_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert nonzero_exc.value.code == "purge_dataset_identity_unverifiable"
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]

    # 2) pg_ctl start raises timeout exception: MUST still run pg_ctl stop before job_exit AND restore exact DACL!
    events.clear()
    start_mode["value"] = "timeout"
    with pytest.raises(LifecycleError) as timeout_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert timeout_exc.value.code == "command_outcome_unknown"
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]

    # 3) Success path: temporary user SID granted before start, exact original DACL restored after stop + job_exit.
    events.clear()
    start_mode["value"] = "ok"
    verified = adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert verified["dataset_id"] == DATASET_ID
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "psql_ok",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]
    assert list(secrets_dir.glob("purge-probe-*")) == []


def test_temporary_probe_access_restores_probe_created_owners_and_fails_closed_on_any_restore_or_verify_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime import windows_security_native as native

    pgdata = tmp_path / "pgdata"
    (pgdata / "global").mkdir(parents=True)
    pg_control = pgdata / "global" / "pg_control"
    pg_control.write_bytes(b"pg-control")
    postmaster_opts = pgdata / "postmaster.opts"

    caller_sid = "S-1-5-21-1000-2000-3000-1001"
    sealed_dacl = (
        "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )

    state_dacl: dict[Path, str] = {pgdata: sealed_dacl, pgdata / "global": sealed_dacl, pg_control: sealed_dacl}
    state_owner: dict[Path, str] = {
        pgdata: native.ADMINISTRATORS_SID,
        pgdata / "global": native.ADMINISTRATORS_SID,
        pg_control: native.ADMINISTRATORS_SID,
    }
    owner_restores: list[tuple[Path, str]] = []

    def fake_apply_dacl(path: Path, sddl: str, *, code: str) -> None:
        del code
        state_dacl[path] = sddl
        for parent, dirs, files in __import__("os").walk(path, followlinks=False):
            for name in (*dirs, *files):
                state_dacl[Path(parent) / name] = sddl

    def fake_set_owner(path: Path, owner: str, *, code: str) -> None:
        del code
        owner_restores.append((path, owner))
        state_owner[path] = owner

    monkeypatch.setattr(pgdata_security.os, "name", "nt")
    monkeypatch.setattr(native, "current_process_user_sid", lambda: caller_sid)
    monkeypatch.setattr(native, "_object_dacl_sddl", lambda p: state_dacl[p])
    monkeypatch.setattr(native, "file_owner_sid", lambda p: state_owner[p])
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 1) Probe creates a new file owned by caller_sid: owner is restored to Administrators and full-tree check passes.
    with pgdata_security.temporary_probe_access(pgdata):
        postmaster_opts.write_text("opts", encoding="ascii")
        state_dacl[postmaster_opts] = f"{sealed_dacl}(A;OICI;FA;;;{caller_sid})"
        state_owner[postmaster_opts] = caller_sid
    assert owner_restores == [(postmaster_opts, native.ADMINISTRATORS_SID)]
    assert state_owner[postmaster_opts] == native.ADMINISTRATORS_SID
    assert caller_sid not in state_dacl[postmaster_opts]

    # 2) Reading root owner fails before grant -> fail-closed with purge_probe_acl_failed (never skipped).
    monkeypatch.setattr(native, "file_owner_sid", lambda _p: (_ for _ in ()).throw(OSError(5, "denied")))
    with pytest.raises(LifecycleError) as root_owner_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when root owner cannot be read")
    assert root_owner_exc.value.code == "purge_probe_acl_failed"
    monkeypatch.setattr(native, "file_owner_sid", lambda p: state_owner[p])

    # 3) Restoring a probe-created file owner fails -> never silently suppressed (merges with body error if any).
    monkeypatch.setattr(
        pgdata_security,
        "set_owner_sid",
        lambda _p, _o, *, code: (_ for _ in ()).throw(LifecycleError(code, "owner restore denied")),
    )
    with pytest.raises(LifecycleError) as owner_fail_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[postmaster_opts] = caller_sid
            raise LifecycleViolation("purge_dataset_identity_mismatch", "dataset mismatch")
    assert owner_fail_exc.value.code == "purge_probe_owner_restore_failed"
    assert "purge_dataset_identity_mismatch" in owner_fail_exc.value.message
    state_owner[postmaster_opts] = native.ADMINISTRATORS_SID
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 4) Residual caller_sid ACE left on a child file after restore -> full-tree verification fails closed!
    def leaky_apply_dacl(path: Path, sddl: str, *, code: str) -> None:
        del code
        state_dacl[path] = sddl
        if caller_sid in sddl:
            state_dacl[pg_control] = sddl

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", leaky_apply_dacl)
    with pytest.raises(LifecycleError) as residual_ace_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert residual_ace_exc.value.code == "purge_probe_acl_restore_failed"

    # 5) Residual caller_sid owner left on a child file after restore -> full-tree verification fails closed!
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)
    monkeypatch.setattr(pgdata_security, "set_owner_sid", lambda _p, _o, *, code: None)
    with pytest.raises(LifecycleError) as residual_owner_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[postmaster_opts] = caller_sid
    assert residual_owner_exc.value.code == "purge_probe_owner_restore_failed"
    state_owner[postmaster_opts] = native.ADMINISTRATORS_SID
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 6) Untrusted root owner (neither SYSTEM nor Administrators) -> refuse before touching DACL or running body!
    state_owner[pgdata] = "S-1-5-21-1000-2000-3000-1099"
    with pytest.raises(LifecycleError) as untrusted_root_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when root owner is untrusted")
    assert untrusted_root_exc.value.code == "purge_probe_owner_untrusted"
    state_owner[pgdata] = native.ADMINISTRATORS_SID

    # 6b) Unprotected (inheriting) root DACL (D:AI...) lacking caller_sid -> refuse WITHOUT mutating DACL!
    applied_calls: list[str] = []
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda _p, sddl, *, code: applied_calls.append(f"{code}:{sddl}"),
    )
    state_dacl[pgdata] = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
    with pytest.raises(LifecycleError) as unprotected_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run on unprotected inheriting pgdata root DACL")
    assert unprotected_exc.value.code == "purge_probe_acl_unprotected"
    assert applied_calls == []
    state_dacl[pgdata] = sealed_dacl
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)

    # 7) Root owner drifts during probe -> post-exit verification catches it and fails closed!
    with pytest.raises(LifecycleError) as root_drift_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[pgdata] = caller_sid
    assert root_drift_exc.value.code == "purge_probe_acl_restore_failed"
    state_owner[pgdata] = native.ADMINISTRATORS_SID

    # 7b) Readback root DACL control flag drifts from D:PAI to D:P -> fails closed!
    def ctrl_drift_apply(path: Path, sddl: str, *, code: str) -> None:
        fake_apply_dacl(path, sddl, code=code)
        if code == "purge_probe_acl_restore_failed":
            state_dacl[path] = sddl.replace("D:PAI(", "D:P(", 1)

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", ctrl_drift_apply)
    with pytest.raises(LifecycleError) as ctrl_drift_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert ctrl_drift_exc.value.code == "purge_probe_acl_restore_failed"
    state_dacl[pgdata] = sealed_dacl

    # 7c) Readback root DACL preserves ACE set but swaps ACE order (e.g. Allow/Deny reordering) -> fails closed!
    def order_swap_apply(path: Path, sddl: str, *, code: str) -> None:
        fake_apply_dacl(path, sddl, code=code)
        if code == "purge_probe_acl_restore_failed":
            state_dacl[path] = (
                "D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
                "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
            )

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", order_swap_apply)
    with pytest.raises(LifecycleError) as order_swap_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert order_swap_exc.value.code == "purge_probe_acl_restore_failed"
    state_dacl[pgdata] = sealed_dacl
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)

    # 8) Unreadable subdirectory during os.walk triggers onerror -> fails closed (never silently skips subtree)!
    import os as _os

    real_walk = _os.walk

    def unreadable_walk(top, *args, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "locked-pg-sub")))
        return iter(())

    monkeypatch.setattr(pgdata_security.os, "walk", unreadable_walk)
    with pytest.raises(LifecycleError) as walk_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when pgdata tree is unreadable")
    assert walk_exc.value.code == "pgdata_tree_unreadable"

    # Also verify onerror during exit restore/verify when unreadable subdir appears after entry:
    walk_calls = {"count": 0}

    def fail_on_restore_walk(top, *args, onerror=None, **kwargs):
        walk_calls["count"] += 1
        if walk_calls["count"] >= 2 and onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "locked-during-restore")))
            return iter(())
        return real_walk(top, *args, onerror=onerror, **kwargs)

    monkeypatch.setattr(pgdata_security.os, "walk", fail_on_restore_walk)
    with pytest.raises(LifecycleError) as restore_walk_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert restore_walk_exc.value.code == "pgdata_tree_unreadable"
    monkeypatch.setattr(pgdata_security.os, "walk", real_walk)


def test_purge_data_probe_retries_stop_until_clean_shutdown_verified_and_never_swallows_stop_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime import windows_security_native as native
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    monkeypatch.setattr(native, "current_process_user_sid", lambda: None)

    events: list[str] = []
    stop_calls = {"count": 0}
    stop_succeeds_on = {"attempt": 2}
    cluster_running = {"value": False}

    class RetryStopRunner:
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, *, on_timeout=None, **_kw):
                    del argv
                    events.append("pg_ctl_start_timeout")
                    cluster_running["value"] = True
                    (pgdata / "postmaster.pid").write_text("12345\n", encoding="ascii")
                    if on_timeout is not None:
                        on_timeout()
                    raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

        def run(self, argv, **_kw):
            exe = Path(argv[0]).name.lower()
            if exe == "pg_controldata.exe":
                state = "in production" if cluster_running["value"] else "shut down"
                return CompletedCommand(
                    tuple(argv),
                    0,
                    f"Database cluster state:               {state}\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            if exe == "pg_ctl.exe" and "stop" in argv:
                stop_calls["count"] += 1
                events.append(f"pg_ctl_stop_{stop_calls['count']}")
                if stop_calls["count"] >= stop_succeeds_on["attempt"]:
                    cluster_running["value"] = False
                    if (pgdata / "postmaster.pid").exists():
                        (pgdata / "postmaster.pid").unlink()
                    return CompletedCommand(tuple(argv), 0, "", "")
                return CompletedCommand(tuple(argv), 1, "", "stop timed out")
            raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(RetryStopRunner(), SimpleNamespace())

    # 1) First stop in on_timeout fails -> outer finally retries BEFORE job_exit and verifies clean shutdown!
    with pytest.raises(LifecycleError) as retry_ok_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert retry_ok_exc.value.code == "command_outcome_unknown"
    assert events == ["job_enter", "pg_ctl_start_timeout", "pg_ctl_stop_1", "pg_ctl_stop_2", "job_exit"]

    # 2) Both stop attempts fail to verify clean shutdown -> raises purge_probe_stop_failed with primary error context!
    events.clear()
    stop_calls["count"] = 0
    stop_succeeds_on["attempt"] = 99
    with pytest.raises(LifecycleError) as stop_fail_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert stop_fail_exc.value.code == "purge_probe_stop_failed"
    assert "command_outcome_unknown" in stop_fail_exc.value.message
    assert events == ["job_enter", "pg_ctl_start_timeout", "pg_ctl_stop_1", "pg_ctl_stop_2", "job_exit"]
    if (pgdata / "postmaster.pid").exists():
        (pgdata / "postmaster.pid").unlink()
    cluster_running["value"] = False

    # 3) Delayed PID race: on_timeout sees pre-start shut down + no PID, then postmaster.pid appears BEFORE starter exits;
    # outer finally MUST re-check AFTER starter exit and run pg_ctl stop before job_exit!
    class DelayedPidRunner(RetryStopRunner):
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, *, on_timeout=None, **_kw):
                    del argv
                    events.append("pg_ctl_start_timeout_before_pid")
                    # on_timeout runs while cluster still looks shut down and no postmaster.pid exists yet!
                    if on_timeout is not None:
                        on_timeout()
                    # Delayed grandchild startup writes postmaster.pid after on_timeout returns, before starter exits.
                    cluster_running["value"] = True
                    (pgdata / "postmaster.pid").write_text("54321\n", encoding="ascii")
                    events.append("delayed_pid_created")
                    raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

    events.clear()
    stop_calls["count"] = 0
    stop_succeeds_on["attempt"] = 2
    delayed_adapter = WindowsDatasetAdapter(DelayedPidRunner(), SimpleNamespace())
    with pytest.raises(LifecycleError) as delayed_exc:
        delayed_adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert delayed_exc.value.code == "command_outcome_unknown"
    assert not (pgdata / "postmaster.pid").exists()
    assert cluster_running["value"] is False
    assert events == [
        "job_enter",
        "pg_ctl_start_timeout_before_pid",
        "pg_ctl_stop_1",
        "delayed_pid_created",
        "pg_ctl_stop_2",
        "job_exit",
    ]

    # 4) If starter process failed to confirm exit (starter_process_not_exited), outer finally MUST NEVER
    # accept pre-start shut down / absent postmaster.pid as stop_verified=True; MUST raise purge_probe_stop_failed!
    class UnconfirmedStarterExitRunner(RetryStopRunner):
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, *, on_timeout=None, **_kw):
                    del argv, on_timeout
                    events.append("starter_not_exited")
                    raise LifecycleError("starter_process_not_exited", "pg_ctl.exe did not confirm exit")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

    events.clear()
    stop_calls["count"] = 0
    stop_succeeds_on["attempt"] = 1
    cluster_running["value"] = False
    unconfirmed_adapter = WindowsDatasetAdapter(UnconfirmedStarterExitRunner(), SimpleNamespace())
    with pytest.raises(LifecycleError) as unconfirmed_exc:
        unconfirmed_adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert unconfirmed_exc.value.code == "purge_probe_stop_failed"
    assert isinstance(unconfirmed_exc.value.__cause__, LifecycleError)
    assert unconfirmed_exc.value.__cause__.code == "starter_process_not_exited"
    assert events == ["job_enter", "starter_not_exited", "pg_ctl_stop_1", "job_exit"]


def test_run_windows_process_raises_termination_unconfirmed_when_process_survives_kill_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from ticketbox_lifecycle.runtime import command as command_mod
    from ticketbox_lifecycle.runtime import windows_process

    class StuckProcess:
        pid = 99999
        stdin = None
        stdout = None
        stderr = None
        returncode = None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["pg_ctl.exe"], timeout or 1)

        def kill(self):
            return None

        def poll(self):
            return None

    class FakeJob:
        def assign(self, _pid: int) -> None:
            return None

        def terminate(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(windows_process.os, "name", "nt")
    monkeypatch.setattr(windows_process.subprocess, "Popen", lambda *a, **kw: StuckProcess())
    monkeypatch.setattr(windows_process, "_resume_suspended_process", lambda _pid: None)

    with pytest.raises(windows_process.ProcessTerminationUnconfirmedError):
        windows_process.run_windows_process(
            ["pg_ctl.exe", "start"],
            env={},
            timeout_s=1,
            input_text=None,
            job=FakeJob(),  # type: ignore[arg-type]
            capture_output=False,
        )

    # Verify _SubprocessManagedJob.run_background_starter maps it to starter_process_not_exited!
    managed_job = command_mod._SubprocessManagedJob()
    managed_job._job = SimpleNamespace(
        run=lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("stuck")
        )
    )
    with pytest.raises(LifecycleError) as mapped_exc:
        managed_job.run_background_starter(["pg_ctl.exe", "start"], env={}, timeout_s=1)
    assert mapped_exc.value.code == "starter_process_not_exited"

    # Verify SubprocessCommandRunner.run ALSO maps ProcessTerminationUnconfirmedError to LifecycleError!
    monkeypatch.setattr(
        command_mod,
        "_run_process",
        lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("stuck stop")
        ),
    )
    with pytest.raises(LifecycleError) as run_mapped_exc:
        command_mod.SubprocessCommandRunner().run(["pg_ctl.exe", "stop"], env={}, timeout_s=1)
    assert run_mapped_exc.value.code == "command_termination_unconfirmed"


def test_purge_data_cli_reports_purge_probe_stop_failed_not_unhandled_on_dual_termination_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle import purge_data_cli
    from ticketbox_lifecycle.runtime import command as command_mod
    from ticketbox_lifecycle.runtime import windows_dataset, windows_process
    from ticketbox_lifecycle.runtime import windows_security_native as native

    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    monkeypatch.setattr(native, "current_process_user_sid", lambda: None)

    class DualUnconfirmedRunner(command_mod.SubprocessCommandRunner):
        def open_managed_job(self):
            class StuckStarterJob:
                def __enter__(self_job):
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    del argv
                    raise LifecycleError("starter_process_not_exited", "pg_ctl start stuck")

                def __exit__(self_job, *_exc):
                    return None

            return StuckStarterJob()

        def run(self, argv, *, env=None, timeout_s=120, input_text=None):
            exe = Path(argv[0]).name.lower()
            if exe == "sc.exe":
                return CompletedCommand(tuple(argv), 1060, "", "missing")
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            return super().run(argv, env=env, timeout_s=timeout_s, input_text=input_text)

    # Make SubprocessCommandRunner.run -> _run_process raise ProcessTerminationUnconfirmedError on pg_ctl stop!
    monkeypatch.setattr(
        command_mod,
        "_run_process",
        lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("pg_ctl stop stuck")
        ),
    )

    dual_runner = DualUnconfirmedRunner()
    real_dataset = windows_dataset.WindowsDatasetAdapter(dual_runner, SimpleNamespace())
    stores._adapters = SimpleNamespace(dataset=real_dataset)  # type: ignore[attr-defined]

    result_file = tmp_path / "purge-dual-result.json"
    monkeypatch.setattr(purge_data_cli, "require_windows", lambda: None)
    monkeypatch.setattr(
        purge_data_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(purge_data_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(purge_data_cli, "ticketbox_program_data_root", lambda: program_data)
    monkeypatch.setattr(purge_data_cli.FilesystemStores, "from_installed", lambda **_kw: stores)
    monkeypatch.setattr(purge_data_cli, "SubprocessCommandRunner", lambda: dual_runner)

    rc = purge_data_cli.main([
        "purge-data",
        "--dataset-id",
        DATASET_ID,
        "--confirm-dataset-id",
        DATASET_ID,
        "--external-backups-status",
        "preserved_outside",
        "--confirm-permanent-delete",
        "--result",
        str(result_file),
    ])
    assert rc == 2
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "purge_probe_stop_failed"
    assert "starter_process_not_exited" in payload["message"]


def test_windows_managed_job_timeout_runs_on_timeout_before_killing_starter_or_closing_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes
    import os
    import socket
    import subprocess
    import sys
    import time
    from ctypes import wintypes

    if os.name != "nt":
        pytest.skip("Windows Job Object timeout ordering test requires Windows")

    from ticketbox_lifecycle.runtime import windows_process

    monkeypatch.setattr(windows_process, "_TERMINATION_TIMEOUT_S", 1)

    # Sub-case 1: Real starter exits cleanly when on_timeout signals stop -> process.kill() is NEVER needed!
    stop_flag = tmp_path / "stop.flag"
    cooperative_script = tmp_path / "coop_starter.py"
    cooperative_script.write_text(
        "import pathlib, sys, time\n"
        "flag = pathlib.Path(sys.argv[1])\n"
        "while not flag.exists():\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    events: list[str] = []
    orig_popen_kill = subprocess.Popen.kill
    orig_job_close = windows_process.PersistentKillOnCloseJob.close

    def tracked_kill(self):
        events.append("starter_kill")
        return orig_popen_kill(self)

    def tracked_close(self):
        events.append("job_close")
        return orig_job_close(self)

    monkeypatch.setattr(subprocess.Popen, "kill", tracked_kill)
    monkeypatch.setattr(windows_process.PersistentKillOnCloseJob, "close", tracked_close)

    def _signal_stop() -> None:
        events.append("on_timeout")
        stop_flag.write_text("stop", encoding="ascii")

    with pytest.raises(subprocess.TimeoutExpired):
        with windows_process.PersistentKillOnCloseJob() as job:
            job.run(
                [sys.executable, str(cooperative_script), str(stop_flag)],
                timeout_s=1,
                capture_output=False,
                on_timeout=_signal_stop,
            )
    assert events == ["on_timeout", "job_close"]

    # Sub-case 2: Stubborn starter + real grandchild daemon (modeling pg_ctl start + postgres.exe):
    # on_timeout gracefully shuts down the grandchild and waits on its Win32 process handle to prove
    # exit_code == 0 BEFORE starter_kill and job_close!
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    clean_exit_marker = tmp_path / "grandchild_clean_exit.txt"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    grandchild_script = tmp_path / "grandchild_pg.py"
    grandchild_script.write_text(
        "import os, pathlib, socket, sys\n"
        "port = int(sys.argv[1])\n"
        "marker = pathlib.Path(sys.argv[2])\n"
        "pid_file = pathlib.Path(sys.argv[3])\n"
        "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', port))\n"
        "srv.listen(5)\n"
        "pid_file.write_text(str(os.getpid()), encoding='ascii')\n"
        "conn, _ = srv.accept()\n"
        "with conn:\n"
        "    cmd = conn.recv(16)\n"
        "    if cmd == b'FAST_STOP':\n"
        "        marker.write_text('clean_shutdown', encoding='ascii')\n"
        "        conn.sendall(b'STOPPED')\n"
        "srv.close()\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stubborn_starter = tmp_path / "stubborn_starter.py"
    stubborn_starter.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def _graceful_stop_grandchild() -> None:
        events.append("on_timeout_begin")
        deadline = time.monotonic() + 5.0
        while not grandchild_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        grandchild_pid = int(grandchild_pid_file.read_text(encoding="ascii").strip())
        proc_handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, grandchild_pid)
        assert proc_handle
        try:
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1.0) as client:
                        client.sendall(b"FAST_STOP")
                        assert client.recv(16) == b"STOPPED"
                        break
                except OSError:
                    time.sleep(0.05)
            assert clean_exit_marker.read_text(encoding="ascii") == "clean_shutdown"
            wait_res = kernel32.WaitForSingleObject(proc_handle, 5000)
            assert wait_res == 0
            exit_code = wintypes.DWORD(0xFFFFFFFF)
            assert kernel32.GetExitCodeProcess(proc_handle, ctypes.byref(exit_code))
            assert exit_code.value == 0
        finally:
            kernel32.CloseHandle(proc_handle)
        events.append("grandchild_clean_exit")

    events.clear()
    with pytest.raises(subprocess.TimeoutExpired):
        with windows_process.PersistentKillOnCloseJob() as job:
            job.run(
                [
                    sys.executable,
                    str(stubborn_starter),
                    str(grandchild_script),
                    str(port),
                    str(clean_exit_marker),
                    str(grandchild_pid_file),
                ],
                timeout_s=1,
                capture_output=False,
                on_timeout=_graceful_stop_grandchild,
            )
    assert events == ["on_timeout_begin", "grandchild_clean_exit", "starter_kill", "job_close"]


def test_windows_managed_job_keeps_grandchild_daemon_alive_across_starter_exit_and_kills_on_close(
    tmp_path: Path,
) -> None:
    import os
    import socket
    import sys
    import time

    if os.name != "nt":
        pytest.skip("Windows Job Object lifecycle test requires Windows")

    from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    pid_file = tmp_path / "daemon.pid"
    daemon_script = tmp_path / "daemon.py"
    starter_script = tmp_path / "starter.py"
    client_script = tmp_path / "client.py"

    daemon_script.write_text(
        "import pathlib, socket, sys\n"
        "port = int(sys.argv[1])\n"
        "pid_path = pathlib.Path(sys.argv[2])\n"
        "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', port))\n"
        "srv.listen(5)\n"
        "pid_path.write_text(str(__import__('os').getpid()), encoding='ascii')\n"
        "while True:\n"
        "    conn, _ = srv.accept()\n"
        "    with conn:\n"
        "        conn.sendall(b'DATASET_OK\\n')\n",
        encoding="utf-8",
    )
    starter_script.write_text(
        "import socket, subprocess, sys, time\n"
        "port = int(sys.argv[1])\n"
        "proc = subprocess.Popen([sys.executable, sys.argv[2], str(port), sys.argv[3]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "deadline = time.monotonic() + 10\n"
        "while time.monotonic() < deadline:\n"
        "    try:\n"
        "        with socket.create_connection(('127.0.0.1', port), timeout=0.5):\n"
        "            sys.exit(0)\n"
        "    except OSError:\n"
        "        time.sleep(0.05)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    client_script.write_text(
        "import socket, sys\n"
        "with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=5) as c:\n"
        "    print(c.recv(64).decode('ascii').strip())\n",
        encoding="utf-8",
    )

    runner = SubprocessCommandRunner()
    with runner.open_managed_job() as job:
        started = job.run_background_starter(
            [sys.executable, str(starter_script), str(port), str(daemon_script), str(pid_file)],
            timeout_s=20,
        )
        assert started.returncode == 0
        # Starter process has already exited, yet grandchild daemon MUST remain alive for a separate runner.run call!
        queried = runner.run([sys.executable, str(client_script), str(port)], timeout_s=15)
        assert queried.returncode == 0
        assert queried.stdout.strip() == "DATASET_OK"

    # Exiting the managed job context MUST terminate the grandchild via JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE!
    deadline = time.monotonic() + 5.0
    stopped = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                time.sleep(0.05)
        except OSError:
            stopped = True
            break
    assert stopped is True


def test_uninstall_rejects_ambiguous_or_non_recoverable_active_operation_before_service_unregister(
    tmp_path: Path,
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex
    from ticketbox_lifecycle.schemas import UninstallOperation

    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    op_id = f"uninstall-{binding.release_manifest_sha256}"

    class SpyUninstallPlatform:
        def __init__(self) -> None:
            self.verify_called = False
            self.unregister_called = False

        def verify_owned_services(self, _request, _binding) -> None:
            self.verify_called = True

        def verify_registered_release_manifests(self, _request, _binding, **_kw) -> None:
            self.verify_called = True

        def stop_and_unregister_services(self, _request, _binding) -> list[str]:
            self.unregister_called = True
            return []

        def remove_start_menu_shortcut(self, _request) -> bool:
            return False

        def cleanup_registered_release_payloads(self, _request, _binding, **_kw) -> list[str]:
            return []

    def _base_active(**overrides: object) -> UninstallOperation:
        fields: dict[str, object] = {
            "schema": OPERATION_SCHEMA,
            "operation_id": op_id,
            "kind": "uninstall",
            "request_hash": "a" * 64,
            "target_release_id": binding.active_release_id,
            "data_root": binding.data_root,
            "release_manifest_sha256": binding.release_manifest_sha256,
            "backend_port": binding.backend_port,
            "phase": "failed_recoverable",
            "no_return_point": False,
            "completed_step": None,
            "install_id": binding.install_id,
            "dataset_id": binding.dataset_id,
            "schema_revision": "20261101_0001",
            "health_attestation_key": "d" * 64,
            "expected_restore_epoch": binding.expected_restore_epoch,
        }
        fields.update(overrides)
        return UninstallOperation(**fields)  # type: ignore[arg-type]

    for bad_overrides in (
        {"phase": "prepared"},
        {"phase": "committed"},
        {"release_manifest_sha256": "not-a-sha256"},
        {"release_manifest_sha256": "z" * 64},
        {"release_manifest_sha256": "e" * 64},
    ):
        stores.operation_store_prepared = True
        stores.publish_active(_base_active(**bad_overrides))
        spy = SpyUninstallPlatform()
        with pytest.raises(LifecycleViolation) as exc:
            uninstall(
                stores.as_lifecycle_stores(),
                replace(req, command="uninstall", operation_id=op_id),
                spy,
            )
        assert exc.value.code == "uninstall_operation_active"
        assert spy.verify_called is False
        assert spy.unregister_called is False

    class NoopSecurity:
        def verify_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def verify_binding_json(self, _path: Path, _service: str) -> None:
            return None

        def protect_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def grant_backend_binding_read(self, _path: Path, _service: str) -> None:
            return None

    machine_root = tmp_path / "fs-dup-keys" / "machine"
    fs_stores = FilesystemStores(
        machine_root,
        binding.backend_service_name,
        SimpleNamespace(security=NoopSecurity()),
        ThreadMutex(),
    )
    fs_stores.publish(binding)
    active_path = machine_root / "operations" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    valid_json = json.dumps(asdict(_base_active()), sort_keys=True)

    for tampered_json in (
        valid_json[:-1] + ', "phase": "prepared"}',
        valid_json[:-1] + r', "phas\u0065": "prepared"}',
    ):
        active_path.write_text(tampered_json, encoding="utf-8")
        spy = SpyUninstallPlatform()
        with pytest.raises(LifecycleError) as dup_exc:
            uninstall(
                fs_stores.as_lifecycle_stores(),
                replace(req, command="uninstall", operation_id=op_id),
                spy,
            )
        assert dup_exc.value.code == "machine_state_invalid"
        assert spy.verify_called is False
        assert spy.unregister_called is False

    active_path.unlink()
    active_path.mkdir()
    spy = SpyUninstallPlatform()
    with pytest.raises(LifecycleError) as dir_exc:
        uninstall(
            fs_stores.as_lifecycle_stores(),
            replace(req, command="uninstall", operation_id=op_id),
            spy,
        )
    assert dir_exc.value.code == "machine_state_invalid"
    assert spy.verify_called is False
    assert spy.unregister_called is False
    active_path.rmdir()

    binding_path = machine_root / "installation.json"
    binding_json = json.dumps(asdict(binding), sort_keys=True)
    binding_path.write_text(
        binding_json[:-1] + ', "release_manifest_sha256": "' + ("f" * 64) + '"}',
        encoding="utf-8",
    )
    with pytest.raises(LifecycleError) as binding_dup_exc:
        fs_stores.read()
    assert binding_dup_exc.value.code == "machine_state_invalid"

    binding_path.unlink()
    binding_path.mkdir()
    with pytest.raises(LifecycleError) as binding_dir_exc:
        fs_stores.read()
    assert binding_dir_exc.value.code == "machine_state_invalid"


def test_uninstall_cli_check_preflight_single_authority_admission_and_zero_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle import cli, uninstall_cli
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.schemas import UninstallOperation

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    program_data = tmp_path / "中文路径" / "Ticketbox"
    machine_root = program_data / "machine"
    machine_root.mkdir(parents=True)
    chinese_data_root = str(program_data / "data")

    _, _mem, _adapters, base_binding = _installed_fixture(tmp_path)
    binding = replace(base_binding, data_root=chinese_data_root)
    op_id = f"uninstall-{binding.release_manifest_sha256}"

    class NoopSecurity:
        def verify_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def verify_binding_json(self, _path: Path, _service: str) -> None:
            return None

        def protect_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def grant_backend_binding_read(self, _path: Path, _service: str) -> None:
            return None

    class PoisonMutex:
        def acquire(self) -> None:
            raise AssertionError("read-only --check-preflight must never acquire lifecycle mutex")

        def release(self) -> None:
            raise AssertionError("read-only --check-preflight must never release lifecycle mutex")

    def _from_installed(*, install_root: Path | None = None, program_data_root: Path | None = None) -> FilesystemStores:
        resolved_pd = program_data_root if program_data_root is not None else program_data
        return FilesystemStores(
            resolved_pd / "machine",
            binding.backend_service_name,
            SimpleNamespace(security=NoopSecurity()),
            PoisonMutex(),
            install_root=install_root,
            program_data_root=resolved_pd,
        )

    monkeypatch.setattr(uninstall_cli, "require_windows", lambda: None)
    monkeypatch.setattr(uninstall_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(uninstall_cli, "ticketbox_program_data_root", lambda: program_data)
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(uninstall_cli.FilesystemStores, "from_installed", staticmethod(_from_installed))

    def _snapshot(root: Path) -> list[tuple[str, bool, bytes | None]]:
        entries: list[tuple[str, bool, bytes | None]] = []
        for item in sorted(root.rglob("*")):
            rel = str(item.relative_to(root))
            entries.append((rel, item.is_dir(), item.read_bytes() if item.is_file() else None))
        return entries

    binding_path = machine_root / "installation.json"
    active_path = machine_root / "operations" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Missing installation.json -> refused (exit 2), zero disk writes.
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "uninstall_binding_missing" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # Write valid installation.json with Chinese data_root serialized as \uXXXX by json.dump(..., ensure_ascii=True).
    binding_raw = json.dumps(asdict(binding), indent=2, sort_keys=True) + "\n"
    assert r"\u" in binding_raw
    binding_path.write_text(binding_raw, encoding="utf-8")

    # 2. Absent active.json + valid installation.json -> allowed (exit 0) via both uninstall_cli and cli.main.
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0
    assert cli.main(["uninstall", "--check-preflight"]) == 0
    assert _snapshot(tmp_path) == before

    # 3. Valid failed_recoverable uninstall record with Chinese data_root (\uXXXX) -> allowed (exit 0)!
    valid_active = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=op_id,
        kind="uninstall",
        request_hash="a" * 64,
        target_release_id=binding.active_release_id,
        data_root=chinese_data_root,
        release_manifest_sha256=binding.release_manifest_sha256,
        backend_port=binding.backend_port,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="unregister_services",
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key="d" * 64,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    active_dict = asdict(valid_active)
    valid_active_raw = json.dumps(active_dict, indent=2, sort_keys=True) + "\n"
    assert r"\u" in valid_active_raw
    active_path.write_text(valid_active_raw, encoding="utf-8")
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0
    assert _snapshot(tmp_path) == before

    # 4. Nested object containing "phase": "failed_recoverable" while top-level lacks "phase" -> refused (exit 2)!
    nested_missing_top_phase = dict(active_dict)
    del nested_missing_top_phase["phase"]
    nested_missing_top_phase["nested"] = {"phase": "failed_recoverable"}
    active_path.write_text(json.dumps(nested_missing_top_phase, indent=2, sort_keys=True), encoding="utf-8")
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "bad_operation_fields" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # 5. Duplicate "phase" key and unicode-escaped duplicate key -> refused (exit 2)!
    compact_valid = json.dumps(active_dict, sort_keys=True)
    for tampered in (
        compact_valid[:-1] + ', "phase": "prepared"}',
        compact_valid[:-1] + r', "phas\u0065": "prepared"}',
    ):
        active_path.write_text(tampered, encoding="utf-8")
        before = _snapshot(tmp_path)
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        assert "machine_state_invalid" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    # 6. Non-recoverable phase, invalid/mismatched manifest digest, or wrong operation_id -> refused (exit 2)!
    for bad_overrides in (
        {"phase": "prepared"},
        {"release_manifest_sha256": "not-hex"},
        {"release_manifest_sha256": "z" * 64},
        {"release_manifest_sha256": "e" * 64},
        {"operation_id": "uninstall-other"},
    ):
        bad_payload = {**active_dict, **bad_overrides}
        active_path.write_text(json.dumps(bad_payload, indent=2, sort_keys=True), encoding="utf-8")
        before = _snapshot(tmp_path)
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        assert "uninstall_operation_active" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    # 7. Directory occupying active.json -> refused (exit 2), zero disk writes!
    active_path.unlink()
    active_path.mkdir()
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "machine_state_invalid" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before
    active_path.rmdir()

    # 8. Non-admin caller -> refused (exit 2) with zero disk writes!
    active_path.write_text(valid_active_raw, encoding="utf-8")
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 0)),
        raising=False,
    )
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "uninstall_admin_required" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # 9. Explicit empty/incompatible flags with --check-preflight MUST be rejected (exit 2) with zero disk writes!
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    for bad_argv in (
        ["uninstall", "--check-preflight", "--result="],
        ["uninstall", "--check-preflight", "--request="],
        ["uninstall", "--check-preflight", "--from-installed"],
    ):
        before = _snapshot(tmp_path)
        with pytest.raises(SystemExit) as arg_exc:
            uninstall_cli.main(bad_argv)
        assert arg_exc.value.code == 2
        capsys.readouterr()
        assert _snapshot(tmp_path) == before


def test_uninstall_cli_from_installed_single_authority_flow_and_forbidden_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle import uninstall_cli
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex
    from ticketbox_lifecycle.schemas import UninstallOperation

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    program_data = tmp_path / "中文路径" / "Ticketbox"
    machine_root = program_data / "machine"
    machine_root.mkdir(parents=True)
    chinese_data_root = str(program_data / "data")

    _, _mem, _adapters, base_binding = _installed_fixture(tmp_path)
    binding = replace(base_binding, data_root=chinese_data_root)
    manifest_sha = binding.release_manifest_sha256.lower()
    expected_op_id = f"uninstall-{manifest_sha}"

    class NoopSecurity:
        def verify_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def verify_binding_json(self, _path: Path, _service: str) -> None:
            return None

        def protect_machine_json(self, _path: Path, _service: str) -> None:
            return None

        def grant_backend_binding_read(self, _path: Path, _service: str) -> None:
            return None

        def prepare_operation_store(self, _request: InstallRequest) -> None:
            return None

    mutex_on_acquire: list[object] = []

    class HookableMutex(ThreadMutex):
        def acquire(self) -> None:
            super().acquire()
            if mutex_on_acquire:
                hook = mutex_on_acquire.pop(0)
                hook()  # type: ignore[operator]

    def _from_installed(*, install_root: Path | None = None, program_data_root: Path | None = None) -> FilesystemStores:
        resolved_pd = program_data_root if program_data_root is not None else program_data
        return FilesystemStores(
            resolved_pd / "machine",
            binding.backend_service_name,
            SimpleNamespace(security=NoopSecurity()),
            HookableMutex(),
            install_root=install_root,
            program_data_root=resolved_pd,
        )

    root_calls = {"install": 0, "program_data": 0}

    def _counted_install_root() -> Path:
        root_calls["install"] += 1
        return app_dir

    def _counted_program_data_root() -> Path:
        root_calls["program_data"] += 1
        return program_data

    class RecordingUninstallPlatform:
        def __init__(self) -> None:
            self.requests: list[InstallRequest] = []
            self.verify_called = False
            self.unregister_called = False
            self.cleanup_called = False

        def verify_owned_services(self, request: InstallRequest, _binding: InstallationBinding) -> None:
            self.verify_called = True
            self.requests.append(request)

        def verify_registered_release_manifests(self, _request, _binding, **_kw) -> None:
            self.verify_called = True

        def stop_and_unregister_services(self, _request, _binding) -> list[str]:
            self.unregister_called = True
            return ["TicketboxBackend", "TicketboxPg"]

        def remove_start_menu_shortcut(self, _request) -> bool:
            return True

        def cleanup_registered_release_payloads(self, _request, _binding, **_kw) -> list[str]:
            self.cleanup_called = True
            return [binding.active_release_id]

    platform_box = [RecordingUninstallPlatform()]

    monkeypatch.setattr(uninstall_cli, "require_windows", lambda: None)
    monkeypatch.setattr(uninstall_cli, "ticketbox_install_root", _counted_install_root)
    monkeypatch.setattr(uninstall_cli, "ticketbox_program_data_root", _counted_program_data_root)
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(uninstall_cli.FilesystemStores, "from_installed", staticmethod(_from_installed))
    monkeypatch.setattr(
        uninstall_cli,
        "WindowsUninstallPlatform",
        lambda *_args, **_kw: platform_box[0],
    )

    binding_path = machine_root / "installation.json"
    active_path = machine_root / "operations" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)

    # Case 1: installation.json has a single Unicode-escaped top-level key ("active_releas\u0065_id")
    # AND Chinese \uXXXX data_root AND matching failed_recoverable active.json.
    # Both --check-preflight AND --from-installed MUST run through REAL uninstall_action.uninstall()
    # with the exact binding digest and archive committed history!
    binding_raw = json.dumps(asdict(binding), indent=2, sort_keys=True) + "\n"
    escaped_key_binding = binding_raw.replace('"active_release_id"', r'"active_releas\u0065_id"', 1)
    assert r'"active_releas\u0065_id"' in escaped_key_binding
    assert r"\u" in binding_raw
    binding_path.write_text(escaped_key_binding, encoding="utf-8")

    active_op = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=expected_op_id,
        kind="uninstall",
        request_hash="a" * 64,
        target_release_id=binding.active_release_id,
        data_root=chinese_data_root,
        release_manifest_sha256=manifest_sha,
        backend_port=binding.backend_port,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="unregister_services",
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key="d" * 64,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    active_path.write_text(json.dumps(asdict(active_op), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0

    root_calls["install"] = 0
    root_calls["program_data"] = 0
    safe_result = tmp_path / "private-result" / "uninstall-result.json"
    safe_result.parent.mkdir(parents=True)
    rc = uninstall_cli.main(["uninstall", "--from-installed", "--result", str(safe_result)])
    assert rc == 0
    assert root_calls == {"install": 1, "program_data": 1}
    assert platform_box[0].unregister_called is True
    assert platform_box[0].cleanup_called is True
    assert len(platform_box[0].requests) == 1
    assert platform_box[0].requests[0].operation_id == expected_op_id
    assert platform_box[0].requests[0].target_release_id == binding.active_release_id
    assert platform_box[0].requests[0].release_manifest_sha256 == manifest_sha
    assert platform_box[0].requests[0].install_id == binding.install_id
    assert platform_box[0].requests[0].dataset_id == binding.dataset_id
    assert not active_path.exists()
    assert (machine_root / "operations" / "history" / f"{expected_op_id}.json").is_file()
    result_payload = json.loads(safe_result.read_text(encoding="utf-8"))
    assert result_payload["ok"] is True
    assert result_payload["phase"] == "committed"
    assert result_payload["operation_id"] == expected_op_id
    assert result_payload["code"] == "uninstalled_data_preserved"

    # Case 1b: TOCTOU race — binding upgrades from release A (digest A) to release B (digest B)
    # AFTER --from-installed constructs uninstall-A and BEFORE uninstall_action.uninstall acquires the lock.
    # Real _uninstall_locked MUST reject with uninstall_identity_mismatch, zero service unregister, zero active.json!
    binding_path.write_text(binding_raw, encoding="utf-8")
    assert not active_path.exists()
    upgraded_binding = replace(
        binding,
        active_release_id="1.4.0",
        previous_release_id=binding.active_release_id,
        release_manifest_sha256="b" * 64,
    )
    platform_box[0] = RecordingUninstallPlatform()
    mutex_on_acquire.append(
        lambda: binding_path.write_text(
            json.dumps(asdict(upgraded_binding), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    )
    race_result = tmp_path / "private-result" / "race-result.json"
    assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(race_result)]) == 2
    assert "uninstall_identity_mismatch" in capsys.readouterr().err
    assert platform_box[0].verify_called is False
    assert platform_box[0].unregister_called is False
    assert not active_path.exists()
    race_payload = json.loads(race_result.read_text(encoding="utf-8"))
    assert race_payload["ok"] is False
    assert race_payload["code"] == "uninstall_identity_mismatch"

    # Case 2: Duplicate top-level data_root or pure bracket syntax mismatch (closing } -> ]) in installation.json ->
    # BOTH --check-preflight AND --from-installed MUST reject BEFORE uninstall()/service unregister!
    platform_box[0] = RecordingUninstallPlatform()
    compact_binding = json.dumps(asdict(binding), sort_keys=True)
    for bad_binding_text in (
        compact_binding[:-1] + ', "data_root": "C:/evil/data"}',
        compact_binding[:-1] + "]",
    ):
        binding_path.write_text(bad_binding_text, encoding="utf-8")
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        capsys.readouterr()
        err_result = tmp_path / "private-result" / "bad-binding-result.json"
        if err_result.exists():
            err_result.unlink()
        assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(err_result)]) == 2
        capsys.readouterr()
        assert platform_box[0].verify_called is False
        assert platform_box[0].unregister_called is False
        err_payload = json.loads(err_result.read_text(encoding="utf-8"))
        assert err_payload["ok"] is False

    # Case 3: Forbidden result paths inside app_dir or program_data_root -> refused with zero file writes!
    binding_path.write_text(binding_raw, encoding="utf-8")
    platform_box[0] = RecordingUninstallPlatform()
    for evil_result in (app_dir / "evil.json", program_data / "evil.json"):
        assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(evil_result)]) == 2
        assert "unsafe_result_path" in capsys.readouterr().err
        assert not evil_result.exists()
        assert platform_box[0].verify_called is False
        assert platform_box[0].unregister_called is False

    # Case 3b: Invalid manifest digest with custom external binding.data_root MUST STILL protect
    # binding.data_root before raising uninstall_binding_missing (zero failure receipt written into it)!
    external_data_root = tmp_path / "external-binding-data"
    external_data_root.mkdir(parents=True)
    bad_digest_external_binding = replace(
        binding,
        data_root=str(external_data_root),
        release_manifest_sha256="not-a-valid-sha256",
    )
    binding_path.write_text(
        json.dumps(asdict(bad_digest_external_binding), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evil_external_result = external_data_root / "evil-failure.json"
    assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(evil_external_result)]) == 2
    assert "unsafe_result_path" in capsys.readouterr().err
    assert not evil_external_result.exists()
    assert list(external_data_root.iterdir()) == []

    # Case 4: Incompatible flags with --from-installed -> exit 2!
    for bad_argv in (
        ["uninstall", "--from-installed"],
        ["uninstall", "--from-installed", "--result="],
        ["uninstall", "--from-installed", "--request=", "--result", str(safe_result)],
    ):
        with pytest.raises(SystemExit) as arg_exc:
            uninstall_cli.main(bad_argv)
        assert arg_exc.value.code == 2
        capsys.readouterr()
