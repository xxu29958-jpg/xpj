"""Upgrade pre/post cold-backup archive, sibling shipment verification, and FilesystemStores persistence tests."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _upgrade_lifecycle_fixtures import (
    DATASET_ID,
    INSTALL_ID,
    OLD_KEY,
    OLD_MANIFEST_SHA,
    _build_physical_installation,
    _build_staged_release,
    _stopped_pg_runner,
)
from fakes import MemoryMutex, make_install_request
from ticketbox_lifecycle.domain.cold_copy import create_cold_copy_locked
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import cold_archive
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REQUEST_SCHEMA,
    ActiveOperation,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)
from ticketbox_lifecycle.upgrade_cli import _read_durable_failure_status


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
        cast(Any, FakeStores(upgrade_op)),
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=op_id,
    )
    allowed_source.require_stopped()

    disallowed_other = ColdInstallation(
        cast(Any, FakeStores(replace(upgrade_op, operation_id="upgrade-" + ("9" * 64)))),
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
        cast(Any, FakeStores(install_op)),
        StoppedRunner(),
        req,
        binding,
        control_sha,
        allowed_operation_id=op_id,
    )
    with pytest.raises(LifecycleError, match="changed or is busy"):
        disallowed_kind.require_stopped()

    disallowed_default = ColdInstallation(
        cast(Any, FakeStores(upgrade_op)),
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
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
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
