"""Upgrade execution state transitions, migration recovery, switchover, commit, and replay tests."""

from __future__ import annotations

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
    _build_physical_installation,
    _build_staged_release,
    _make_upgrade_fixture,
)
from ticketbox_lifecycle.domain.binding import upgrade_binding
from ticketbox_lifecycle.domain.upgrade import upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import (
    sign_challenge,
    sign_runtime_mode,
)
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import (
    REQUEST_SCHEMA,
    ActiveOperation,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)


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
        cast(Any, SimpleNamespace()),
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
    setattr(adapters, "security", sec)
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
    setattr(
        plat,
        "stores",
        SimpleNamespace(
            mutex=SimpleNamespace(_lock=SimpleNamespace(locked=lambda: True)),
            read_active=fs_stores.read_active,
            adapters=adapters,
            bind_and_verify=mem_stores.bind_and_verify,
        ),
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
    setattr(adapters, "security", sec)
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
    setattr(
        plat,
        "stores",
        SimpleNamespace(
            mutex=SimpleNamespace(_lock=SimpleNamespace(locked=lambda: True)),
            read_active=fs_stores.read_active,
            adapters=adapters,
            bind_and_verify=mem_stores.bind_and_verify,
        ),
    )
    result = upgrade(lifecycle, req, plat)
    assert result.ok is False
    assert result.phase == "release_activated"
    assert result.installation_published is True
    sec.fail_temp = False
    persisted = fs_stores.read_active()
    assert persisted is not None
    assert persisted.phase == "release_activated"
