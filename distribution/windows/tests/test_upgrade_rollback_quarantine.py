"""Upgrade rollback, post-write fencing, quarantine, and previous-release restoration tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _upgrade_lifecycle_fixtures import (
    DATASET_ID,
    INSTALL_ID,
    OLD_KEY,
    FakeUpgradePlatform,
    _make_upgrade_fixture,
)
from ticketbox_lifecycle.domain.upgrade import rollback_upgrade, upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REQUEST_SCHEMA,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)


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
        cast(Any, stores),
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
        cast(Any, SimpleNamespace()),
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
