"""Tests for Rev3.2 §9.6 controlled default uninstall lifecycle and release manifest verification."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _uninstall_reinstall_fixtures import (
    DATASET_ID,
    INSTALL_ID,
    _installed_fixture,
    _make_uninstall_operation,
    _NoopMachineSecurity,
    _write_release_manifest,
)
from ticketbox_lifecycle.domain.uninstall import uninstall
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.schemas import OPERATION_SCHEMA, ActiveOperation


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


def test_windows_uninstall_verifies_connector_config_and_state_and_cleans_u1_releases(tmp_path: Path) -> None:
    from ticketbox_lifecycle.policy.connector_profile import (
        SERVICE_NAME as CONNECTOR_SERVICE_NAME,
    )
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform

    req, _stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    binding = replace(binding, previous_release_id="1.2.1")
    app_dir = Path(req.app_dir)

    # Create valid manifest-backed release 1.2.1 and U1-materialized release 1.3.0, plus shared bin/lifecycle.
    shared_lc = app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe"
    shared_lc.parent.mkdir(parents=True, exist_ok=True)
    shared_lc.write_bytes(b"shared-lifecycle-exe")
    manifest_shas = {rid: _write_release_manifest(app_dir, rid) for rid in ("1.2.1", "1.3.0")}
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
    manifest_shas = {rid: _write_release_manifest(app_dir, rid) for rid in ("1.2.1", "1.3.0")}

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

    setattr(real_platform, "stop_and_unregister_services", guarded_stop)
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
    assert _write_release_manifest(app_dir, "1.2.1") == manifest_shas["1.2.1"]

    stores.operation_store_prepared = True
    stores.publish_active(
        _make_uninstall_operation(
            operation_id="uninstall-active-already-gone",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
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
        _make_uninstall_operation(
            operation_id="uninstall-empty-after-manifest-unlink",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
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
        _make_uninstall_operation(
            operation_id="uninstall-releases-is-file",
            data_root=req.data_root,
            release_manifest_sha256=manifest_shas["1.3.0"],
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
    sha_130 = _write_release_manifest(app_dir, "1.3.0")
    stores._binding = replace(valid_binding, release_manifest_sha256=sha_130)
    result_absent_prev = uninstall(
        stores.as_lifecycle_stores(),
        replace(req, command="uninstall", operation_id="uninstall-absent-prev", release_manifest_sha256=sha_130),
        real_platform,
    )
    assert result_absent_prev.ok is True
    assert result_absent_prev.details["removed_releases"] == ["1.3.0"]


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
        return UninstallOperation(**cast(dict[str, Any], fields))

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

    machine_root = tmp_path / "fs-dup-keys" / "machine"
    fs_stores = FilesystemStores(
        machine_root,
        binding.backend_service_name,
        SimpleNamespace(security=_NoopMachineSecurity()),
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


def test_uninstall_replays_matching_committed_operation_after_release_cleanup_and_fails_closed_after_reinstall(
    tmp_path: Path,
) -> None:
    from ticketbox_lifecycle.policy.windows_scm_contract import (
        SERVICE_DEMAND_START,
        expected_backend_service,
    )
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform

    req, stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_sha = _write_release_manifest(app_dir, "1.3.0")
    binding = replace(binding, release_manifest_sha256=manifest_sha)
    stores._binding = binding
    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id=f"uninstall-{manifest_sha}",
        release_manifest_sha256=manifest_sha,
    )

    def make_platform(*, foreign_service: bool = False) -> WindowsUninstallPlatform:
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                present = foreign_service and argv[2] == binding.backend_service_name
                return CompletedCommand(tuple(argv), 0 if present else 1060, "STATE : 1 STOPPED", "")
            return CompletedCommand(tuple(argv), 0, "", "")

        foreign_cfg = replace(
            expected_backend_service(uninstall_req, start_type=SERVICE_DEMAND_START),
            argv=(str(tmp_path / "foreign" / "backend.exe"),),
        )
        observer = SimpleNamespace(observe=lambda _name: foreign_cfg)
        return WindowsUninstallPlatform(SimpleNamespace(run=run), observer, shortcut_remover=lambda: False)

    # First uninstall succeeds, deletes releases/1.3.0, and archives the committed operation.
    first = uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert first.ok is True
    assert first.phase == "committed"
    assert first.code == "uninstalled_data_preserved"
    assert first.details["removed_releases"] == ["1.3.0"]
    assert not (app_dir / "releases").exists()
    assert stores.read_active() is None
    assert len(stores.history) == 1
    archived_before_replay = stores.history[-1]

    # Exact replay (e.g. lost result receipt or Inno early exit) must succeed without tripping
    # uninstall_release_manifest_missing, while preserving committed history and user data.
    replay = uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert replay.ok is True
    assert replay.phase == "committed"
    assert replay.code == "uninstalled_data_preserved"
    assert replay.details["removed_releases"] == []
    assert stores.read_active() is None
    assert stores.history == [archived_before_replay]
    assert (Path(req.data_root) / "pgdata" / "base" / "facts").read_bytes() == b"preserved-financial-facts"

    # Security checks still run on committed replay: foreign services and unregistered release dirs fail closed.
    with pytest.raises(LifecycleViolation) as foreign_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform(foreign_service=True))
    assert foreign_exc.value.code == "uninstall_foreign_service_refused"

    unregistered = app_dir / "releases" / "9.9.9"
    unregistered.mkdir(parents=True, exist_ok=True)
    with pytest.raises(LifecycleViolation) as unregistered_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert unregistered_exc.value.code == "uninstall_unregistered_release_present"
    unregistered.rmdir()
    (app_dir / "releases").rmdir()

    # After /REINSTALL=YES rotates health_attestation_key for the same release, the older committed
    # uninstall history must NOT waive strict release-manifest verification on a new uninstall attempt.
    reinstalled_binding = replace(binding, health_attestation_key="f" * 64)
    stores.publish(reinstalled_binding)
    with pytest.raises(LifecycleViolation) as post_reinstall_missing:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert post_reinstall_missing.value.code == "uninstall_release_manifest_missing"

    # Non-uninstall committed history sharing operation_id must fail closed with uninstall_operation_conflict.
    stores._history[-1] = ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id=uninstall_req.operation_id,
        kind="install",
        request_hash="a" * 64,
        target_release_id="1.3.0",
        data_root=req.data_root,
        release_manifest_sha256=manifest_sha,
        backend_port=8000,
        phase="committed",
        no_return_point=True,
        completed_step="health",
        install_id=INSTALL_ID,
        dataset_id=DATASET_ID,
        schema_revision="20261101_0001",
        health_attestation_key="f" * 64,
    )
    with pytest.raises(LifecycleViolation) as conflict_exc:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert conflict_exc.value.code == "uninstall_operation_conflict"


def test_uninstall_baseline_legacy_archive_and_real_reinstall_end_to_end(tmp_path: Path) -> None:
    from ticketbox_lifecycle.domain.reinstall import reinstall
    from ticketbox_lifecycle.domain.uninstall import (
        _legacy_uninstall_request_hash,
        check_uninstall_preflight,
    )
    from ticketbox_lifecycle.policy.windows_scm_contract import (
        SERVICE_DEMAND_START,
        expected_backend_service,
    )
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform
    from ticketbox_lifecycle.schemas import UninstallOperation

    req, stores, adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_sha = _write_release_manifest(app_dir, "1.3.0")
    binding = replace(binding, release_manifest_sha256=manifest_sha)
    stores._binding = binding
    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id=f"uninstall-{manifest_sha}",
        release_manifest_sha256=manifest_sha,
    )

    def make_platform() -> WindowsUninstallPlatform:
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                return CompletedCommand(tuple(argv), 1060, "", "")
            return CompletedCommand(tuple(argv), 0, "", "")

        foreign_cfg = replace(
            expected_backend_service(uninstall_req, start_type=SERVICE_DEMAND_START),
            argv=(str(tmp_path / "foreign" / "backend.exe"),),
        )
        return WindowsUninstallPlatform(
            SimpleNamespace(run=run),
            SimpleNamespace(observe=lambda _name: foreign_cfg),
            shortcut_remover=lambda: False,
        )

    # Simulate an archive written by baseline 5efe8c08e: random health_attestation_key + legacy request_hash,
    # with releases/1.3.0 already deleted by the baseline uninstall.
    (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").unlink()
    (app_dir / "releases" / "1.3.0" / "backend").rmdir()
    (app_dir / "releases" / "1.3.0" / "release-manifest.json").unlink()
    (app_dir / "releases" / "1.3.0").rmdir()
    (app_dir / "releases").rmdir()
    legacy_committed = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=uninstall_req.operation_id,
        kind="uninstall",
        request_hash=_legacy_uninstall_request_hash(binding),
        target_release_id=binding.active_release_id,
        data_root=binding.data_root,
        release_manifest_sha256=binding.release_manifest_sha256,
        backend_port=binding.backend_port,
        phase="committed",
        no_return_point=True,
        completed_step="remove_shortcut",
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key="9" * 64,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    stores._history.append(legacy_committed)

    # Preflight + replay of baseline legacy archive succeeds cleanly.
    check_uninstall_preflight(stores.as_lifecycle_stores())
    legacy_replay = uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert legacy_replay.ok is True
    assert legacy_replay.phase == "committed"
    assert legacy_replay.details["removed_releases"] == []

    # Same-incarnation mismatched request_hash on committed history must fail closed (both preflight & uninstall).
    tampered_same_incarnation = replace(
        legacy_committed,
        health_attestation_key=binding.health_attestation_key,
        request_hash="0" * 64,
    )
    stores._history[-1] = tampered_same_incarnation
    with pytest.raises(LifecycleViolation) as preflight_conflict:
        check_uninstall_preflight(stores.as_lifecycle_stores())
    assert preflight_conflict.value.code == "uninstall_operation_conflict"
    with pytest.raises(LifecycleViolation) as uninstall_conflict:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert uninstall_conflict.value.code == "uninstall_operation_conflict"
    stores._history[-1] = legacy_committed

    # Real end-to-end: uninstall (legacy committed above) -> real reinstall() -> second uninstall!
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha
    stores.pg_service_present = False
    stores.backend_service_present = False
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")

    class FakeReinstallPlatform:
        def publish_and_verify_program_acls(self, _req): ...
        def verify_preserved_dataset(self, _req, _binding):
            return {"verified_originals": 1}
        def verify_candidate_health(self, _req): ...
        def verify_normal_health(self, _req): ...
        def update_start_menu_shortcut(self, _req): ...

    reinstall_req = replace(
        req,
        command="reinstall",
        operation_id=f"reinstall-{manifest_sha}",
        release_manifest_sha256=manifest_sha,
    )
    reinstalled = reinstall(stores.as_lifecycle_stores(), reinstall_req, FakeReinstallPlatform())
    assert reinstalled.ok is True
    new_binding = stores.read()
    assert new_binding is not None
    assert new_binding.health_attestation_key != binding.health_attestation_key

    # After real reinstall, if release files are missing, second uninstall MUST fail closed (strict check).
    (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").unlink()
    (app_dir / "releases" / "1.3.0" / "backend").rmdir()
    (app_dir / "releases" / "1.3.0" / "release-manifest.json").unlink()
    (app_dir / "releases" / "1.3.0").rmdir()
    (app_dir / "releases").rmdir()
    with pytest.raises(LifecycleViolation) as strict_missing:
        uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert strict_missing.value.code == "uninstall_release_manifest_missing"

    # With release files present, second uninstall succeeds, overwrites history with new key, and replays cleanly.
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha
    second = uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert second.ok is True
    assert second.phase == "committed"
    assert second.details["removed_releases"] == ["1.3.0"]
    archived_second = stores.read_committed(uninstall_req.operation_id)
    assert archived_second is not None
    assert archived_second.health_attestation_key == new_binding.health_attestation_key

    second_replay = uninstall(stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert second_replay.ok is True
    assert second_replay.phase == "committed"
    assert second_replay.details["removed_releases"] == []


def test_uninstall_recovers_interrupted_committed_active_and_rejects_tampered_failed_recoverable(
    tmp_path: Path,
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle.domain.uninstall import check_uninstall_preflight
    from ticketbox_lifecycle.policy.windows_scm_contract import (
        SERVICE_DEMAND_START,
        expected_backend_service,
    )
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform

    class _NoopMachineSecurity:
        def prepare_operation_store(self, _request) -> None: ...
        def require_fresh_inputs(self, _request) -> None: ...
        def protect_machine_json(self, _path, _svc) -> None: ...
        def verify_machine_json(self, _path, _svc) -> None: ...
        def grant_backend_binding_read(self, _path, _svc) -> None: ...
        def verify_binding_json(self, _path, _svc) -> None: ...

    req, _mem_stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_sha = _write_release_manifest(app_dir, "1.3.0")
    binding = replace(binding, release_manifest_sha256=manifest_sha)
    op_id = f"uninstall-{manifest_sha}"
    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id=op_id,
        release_manifest_sha256=manifest_sha,
    )

    machine_root = tmp_path / "fs-committed-active" / "machine"
    fs_stores = FilesystemStores(
        machine_root,
        binding.backend_service_name,
        SimpleNamespace(security=_NoopMachineSecurity()),
        ThreadMutex(),
    )
    fs_stores.publish(binding)

    def make_platform(*, fail_cleanup: bool = False) -> WindowsUninstallPlatform:
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                return CompletedCommand(tuple(argv), 1060, "", "")
            return CompletedCommand(tuple(argv), 0, "", "")

        foreign_cfg = replace(
            expected_backend_service(uninstall_req, start_type=SERVICE_DEMAND_START),
            argv=(str(tmp_path / "foreign" / "backend.exe"),),
        )
        plat = WindowsUninstallPlatform(
            SimpleNamespace(run=run),
            SimpleNamespace(observe=lambda _name: foreign_cfg),
            shortcut_remover=lambda: False,
        )
        if fail_cleanup:
            def _boom(*_a, **_kw):
                raise LifecycleError("uninstall_cleanup_io", "simulated transient cleanup failure")

            plat.cleanup_registered_release_payloads = _boom  # type: ignore[method-assign]
        return plat

    committed_active = _make_uninstall_operation(
        operation_id=op_id,
        data_root=binding.data_root,
        release_manifest_sha256=manifest_sha,
        phase="committed",
        no_return_point=True,
        completed_step="remove_shortcut",
        health_attestation_key=binding.health_attestation_key,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    # Remove releases/1.3.0 as if first uninstall already cleaned up before crashing prior to archiving.
    (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").unlink()
    (app_dir / "releases" / "1.3.0" / "backend").rmdir()
    (app_dir / "releases" / "1.3.0" / "release-manifest.json").unlink()
    (app_dir / "releases" / "1.3.0").rmdir()
    (app_dir / "releases").rmdir()

    # Crash point 1: active.json is committed, history/{op_id}.json not written yet.
    fs_stores.publish_active(committed_active)
    assert fs_stores.read_committed(op_id) is None
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())

    # If a transient error occurs while finishing a committed active.json, active.json MUST NOT downgrade!
    failed_finish = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform(fail_cleanup=True))
    assert failed_finish.ok is False
    assert failed_finish.phase == "committed"
    still_active = fs_stores.read_active()
    assert still_active is not None and still_active.phase == "committed"

    # Retrying finishes idempotently: writes history/{op_id}.json and unlinks active.json.
    finished_cp1 = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert finished_cp1.ok is True
    assert finished_cp1.phase == "committed"
    assert fs_stores.read_active() is None
    assert fs_stores.read_committed(op_id) == committed_active

    # Crash point 2: history/{op_id}.json ALREADY written AND active.json still present (unlink interrupted).
    fs_stores.publish_active(committed_active)
    assert fs_stores.read_active() == committed_active
    assert fs_stores.read_committed(op_id) == committed_active
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    finished_cp2 = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert finished_cp2.ok is True
    assert finished_cp2.phase == "committed"
    assert fs_stores.read_active() is None
    assert fs_stores.read_committed(op_id) == committed_active

    # Blocker 8: tampered failed_recoverable active MUST fail closed:
    # - same-incarnation request_hash mismatch -> uninstall_operation_conflict
    # - wrong epoch/release/data_root/key/port (including legacy random-key fallback!) -> uninstall_operation_active
    from ticketbox_lifecycle.domain.uninstall import _legacy_uninstall_request_hash

    (machine_root / "operations" / "history" / f"{op_id}.json").unlink()
    valid_failed = _make_uninstall_operation(
        operation_id=op_id,
        data_root=binding.data_root,
        release_manifest_sha256=manifest_sha,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="unregister_services",
        health_attestation_key=binding.health_attestation_key,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    active_path = machine_root / "operations" / "active.json"
    tampered_cases: tuple[tuple[dict[str, object], str], ...] = (
        ({"expected_restore_epoch": 99}, "uninstall_operation_active"),
        ({"target_release_id": "1.2.1"}, "uninstall_operation_active"),
        ({"data_root": str(tmp_path / "other-data")}, "uninstall_operation_active"),
        ({"health_attestation_key": "e" * 64}, "uninstall_operation_active"),
        (
            {
                "health_attestation_key": "e" * 64,
                "request_hash": _legacy_uninstall_request_hash(binding),
            },
            "uninstall_operation_active",
        ),
        ({"request_hash": "b" * 64}, "uninstall_operation_conflict"),
        ({"backend_port": 9999}, "uninstall_operation_active"),
    )
    for tampered_fields, expected_code in tampered_cases:
        tampered = replace(valid_failed, **tampered_fields)
        active_path.write_text(json.dumps(asdict(tampered), sort_keys=True), encoding="utf-8")
        with pytest.raises(LifecycleViolation) as pref_exc:
            check_uninstall_preflight(fs_stores.as_lifecycle_stores())
        assert pref_exc.value.code == expected_code
        with pytest.raises(LifecycleViolation) as uninst_exc:
            uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
        assert uninst_exc.value.code == expected_code


def test_uninstall_first_commit_publish_io_failure_stays_recoverable_and_retries(
    tmp_path: Path,
) -> None:
    from ticketbox_lifecycle.domain.uninstall import check_uninstall_preflight
    from ticketbox_lifecycle.policy.windows_scm_contract import (
        SERVICE_DEMAND_START,
        expected_backend_service,
    )
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform

    class _NoopMachineSecurity:
        def prepare_operation_store(self, _request) -> None: ...
        def require_fresh_inputs(self, _request) -> None: ...
        def protect_machine_json(self, _path, _svc) -> None: ...
        def verify_machine_json(self, _path, _svc) -> None: ...
        def grant_backend_binding_read(self, _path, _svc) -> None: ...
        def verify_binding_json(self, _path, _svc) -> None: ...

    req, _mem_stores, _adapters, binding = _installed_fixture(tmp_path, release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_sha = _write_release_manifest(app_dir, "1.3.0")
    binding = replace(binding, release_manifest_sha256=manifest_sha)
    op_id = f"uninstall-{manifest_sha}"
    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id=op_id,
        release_manifest_sha256=manifest_sha,
    )

    machine_root = tmp_path / "fs-commit-fail" / "machine"
    fs_stores = FilesystemStores(
        machine_root,
        binding.backend_service_name,
        SimpleNamespace(security=_NoopMachineSecurity()),
        ThreadMutex(),
    )
    fs_stores.publish(binding)

    def make_platform() -> WindowsUninstallPlatform:
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                return CompletedCommand(tuple(argv), 1060, "", "")
            return CompletedCommand(tuple(argv), 0, "", "")

        foreign_cfg = replace(
            expected_backend_service(uninstall_req, start_type=SERVICE_DEMAND_START),
            argv=(str(tmp_path / "foreign" / "backend.exe"),),
        )
        return WindowsUninstallPlatform(
            SimpleNamespace(run=run),
            SimpleNamespace(observe=lambda _name: foreign_cfg),
            shortcut_remover=lambda: False,
        )

    # Fault injection: first publish_active(phase="committed") raises transient OSError BEFORE replacing active.json.
    real_publish = fs_stores.publish_active
    injected = {"triggered": False}

    def flaky_publish(operation):
        if operation.phase == "committed" and not injected["triggered"]:
            injected["triggered"] = True
            raise OSError("simulated transient replace failure before commit publish")
        real_publish(operation)

    fs_stores.publish_active = flaky_publish  # type: ignore[method-assign]

    first = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert injected["triggered"] is True
    assert first.ok is False
    assert first.phase == "failed_recoverable"
    assert fs_stores.read_committed(op_id) is None
    persisted = fs_stores.read_active()
    assert persisted is not None
    assert persisted.phase == "failed_recoverable"
    assert persisted.no_return_point is True

    # Preflight and retry recover cleanly even though releases/1.3.0 was already removed before the OSError.
    fs_stores.publish_active = real_publish  # type: ignore[method-assign]
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    recovered = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert recovered.ok is True
    assert recovered.phase == "committed"
    assert fs_stores.read_active() is None
    archived = fs_stores.read_committed(op_id)
    assert archived is not None and archived.phase == "committed"

    # Sub-case B2: os.replace already persisted phase="committed" to active.json, then post-replace verify failed.
    (machine_root / "operations" / "history" / f"{op_id}.json").unlink()
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha
    post_replace = {"triggered": False}

    def post_replace_fail(operation):
        real_publish(operation)
        if operation.phase == "committed" and not post_replace["triggered"]:
            post_replace["triggered"] = True
            raise OSError("simulated transient post-replace verify failure after commit persisted")

    fs_stores.publish_active = post_replace_fail  # type: ignore[method-assign]
    partial = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert post_replace["triggered"] is True
    assert partial.ok is False
    assert partial.phase == "committed"
    persisted_commit = fs_stores.read_active()
    assert persisted_commit is not None and persisted_commit.phase == "committed"

    fs_stores.publish_active = real_publish  # type: ignore[method-assign]
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    finished = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert finished.ok is True
    assert finished.phase == "committed"
    assert fs_stores.read_active() is None
    assert fs_stores.read_committed(op_id) is not None

    # Sub-case B3a: commit publish fails before os.replace AND fallback failed_recoverable publish succeeds at
    # os.replace then raises on post-replace verify -> readback matches disk ("failed_recoverable") and retry works.
    (machine_root / "operations" / "history" / f"{op_id}.json").unlink()
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha

    def commit_fail_fallback_post_verify_fail(operation):
        if operation.phase == "committed":
            raise OSError("simulated replace failure before commit publish")
        real_publish(operation)
        if operation.phase == "failed_recoverable":
            raise OSError("simulated transient post-replace verify failure after failed_recoverable persisted")

    fs_stores.publish_active = commit_fail_fallback_post_verify_fail  # type: ignore[method-assign]
    double_transient = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert double_transient.ok is False
    assert double_transient.phase == "failed_recoverable"
    persisted_b3a = fs_stores.read_active()
    assert persisted_b3a is not None
    assert persisted_b3a.phase == "failed_recoverable"
    assert persisted_b3a.no_return_point is True

    fs_stores.publish_active = real_publish  # type: ignore[method-assign]
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    recovered_b3a = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert recovered_b3a.ok is True
    assert recovered_b3a.phase == "committed"
    assert fs_stores.read_active() is None

    # Sub-case B3b: both commit and fallback fail BEFORE os.replace -> disk & receipt both stay "prepared"
    # and preflight intentionally blocks as uninstall_operation_active.
    (machine_root / "operations" / "history" / f"{op_id}.json").unlink()
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha

    def both_fail_before_replace(operation):
        if operation.phase in ("committed", "failed_recoverable"):
            raise OSError("simulated persistent disk I/O failure before replace")
        real_publish(operation)

    fs_stores.publish_active = both_fail_before_replace  # type: ignore[method-assign]
    double_pre_replace = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert double_pre_replace.ok is False
    assert double_pre_replace.phase == "prepared"
    persisted_b3b = fs_stores.read_active()
    assert persisted_b3b is not None and persisted_b3b.phase == "prepared"
    fs_stores.publish_active = real_publish  # type: ignore[method-assign]
    with pytest.raises(LifecycleViolation) as prepared_exc:
        check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    assert prepared_exc.value.code == "uninstall_operation_active"

    # Sub-case B3c: fallback publish raises OSError AND readback sees corrupt JSON (JSONDecodeError/ValueError) ->
    # uninstall still returns a sanitized CommandResult(ok=False) instead of leaking JSONDecodeError.
    (machine_root / "operations" / "active.json").unlink()
    assert _write_release_manifest(app_dir, "1.3.0") == manifest_sha

    def fail_and_corrupt_active(operation):
        if operation.phase == "committed":
            raise OSError("simulated replace failure before commit publish")
        if operation.phase == "failed_recoverable":
            (machine_root / "operations" / "active.json").write_text("{", encoding="utf-8")
            raise OSError("simulated post-replace verify failure leaving corrupt json")
        real_publish(operation)

    fs_stores.publish_active = fail_and_corrupt_active  # type: ignore[method-assign]
    corrupt_readback = uninstall(fs_stores.as_lifecycle_stores(), uninstall_req, make_platform())
    assert corrupt_readback.ok is False
    assert corrupt_readback.phase == "prepared"
    fs_stores.publish_active = real_publish  # type: ignore[method-assign]


def test_uninstall_reinstall_then_baseline_uninstall_immediate_replay_succeeds_and_ties_fail_closed(
    tmp_path: Path,
) -> None:
    import os

    from ticketbox_lifecycle.domain.reinstall import reinstall
    from ticketbox_lifecycle.domain.uninstall import (
        _legacy_uninstall_request_hash,
        check_uninstall_preflight,
    )
    from ticketbox_lifecycle.policy.windows_scm_contract import (
        SERVICE_DEMAND_START,
        expected_backend_service,
    )
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex
    from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform
    from ticketbox_lifecycle.schemas import ReinstallOperation, UninstallOperation

    # 1. MemoryStores: real reinstall() -> baseline 5efe8c08e uninstall -> immediate replay SUCCEEDS.
    req, mem_stores, adapters, binding = _installed_fixture(tmp_path / "mem", release_id="1.3.0")
    app_dir = Path(req.app_dir)
    manifest_sha = _write_release_manifest(app_dir, "1.3.0")
    binding = replace(binding, release_manifest_sha256=manifest_sha)
    mem_stores._binding = binding
    mem_stores.pg_service_present = False
    mem_stores.backend_service_present = False
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")

    class FakeReinstallPlatform:
        def publish_and_verify_program_acls(self, _req): ...
        def verify_preserved_dataset(self, _req, _binding):
            return {"verified_originals": 1}
        def verify_candidate_health(self, _req): ...
        def verify_normal_health(self, _req): ...
        def update_start_menu_shortcut(self, _req): ...

    reinstall_req = replace(
        req,
        command="reinstall",
        operation_id=f"reinstall-{manifest_sha}",
        release_manifest_sha256=manifest_sha,
    )
    assert reinstall(mem_stores.as_lifecycle_stores(), reinstall_req, FakeReinstallPlatform()).ok is True
    reinstalled_binding = mem_stores.read()
    assert reinstalled_binding is not None

    uninstall_req = replace(
        req,
        command="uninstall",
        operation_id=f"uninstall-{manifest_sha}",
        release_manifest_sha256=manifest_sha,
    )

    def make_platform(target_req) -> WindowsUninstallPlatform:
        def run(argv, **_kw):
            if argv[0] == "sc.exe" and argv[1] == "query":
                return CompletedCommand(tuple(argv), 1060, "", "")
            return CompletedCommand(tuple(argv), 0, "", "")

        foreign_cfg = replace(
            expected_backend_service(target_req, start_type=SERVICE_DEMAND_START),
            argv=(str(tmp_path / "foreign" / "backend.exe"),),
        )
        return WindowsUninstallPlatform(
            SimpleNamespace(run=run),
            SimpleNamespace(observe=lambda _name: foreign_cfg),
            shortcut_remover=lambda: False,
        )

    # Simulate baseline 5efe8c08e uninstall committed AFTER reinstall (removes release dirs + writes random key + legacy hash).
    (app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").unlink()
    (app_dir / "releases" / "1.3.0" / "backend").rmdir()
    (app_dir / "releases" / "1.3.0" / "release-manifest.json").unlink()
    (app_dir / "releases" / "1.3.0").rmdir()
    (app_dir / "releases").rmdir()
    baseline_after_reinstall = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=uninstall_req.operation_id,
        kind="uninstall",
        request_hash=_legacy_uninstall_request_hash(reinstalled_binding),
        target_release_id=reinstalled_binding.active_release_id,
        data_root=reinstalled_binding.data_root,
        release_manifest_sha256=reinstalled_binding.release_manifest_sha256,
        backend_port=reinstalled_binding.backend_port,
        phase="committed",
        no_return_point=True,
        completed_step="remove_shortcut",
        install_id=reinstalled_binding.install_id,
        dataset_id=reinstalled_binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key="7" * 64,
        expected_restore_epoch=reinstalled_binding.expected_restore_epoch,
    )
    mem_stores._history.append(baseline_after_reinstall)

    check_uninstall_preflight(mem_stores.as_lifecycle_stores())
    mem_replay = uninstall(mem_stores.as_lifecycle_stores(), uninstall_req, make_platform(uninstall_req))
    assert mem_replay.ok is True
    assert mem_replay.phase == "committed"
    assert mem_replay.details["removed_releases"] == []

    # 2. Real FilesystemStores: verify strict mtime ordering (after succeeds, tie fails closed, before fails closed).
    class _NoopMachineSecurity:
        def prepare_operation_store(self, _request) -> None: ...
        def require_fresh_inputs(self, _request) -> None: ...
        def protect_machine_json(self, _path, _svc) -> None: ...
        def verify_machine_json(self, _path, _svc) -> None: ...
        def grant_backend_binding_read(self, _path, _svc) -> None: ...
        def verify_binding_json(self, _path, _svc) -> None: ...

    fs_req, _m, _a, fs_binding = _installed_fixture(tmp_path / "fs", release_id="1.3.0")
    fs_app_dir = Path(fs_req.app_dir)
    fs_manifest_sha = _write_release_manifest(fs_app_dir, "1.3.0")
    fs_binding = replace(fs_binding, release_manifest_sha256=fs_manifest_sha, health_attestation_key="c" * 64)
    fs_uninstall_req = replace(
        fs_req,
        command="uninstall",
        operation_id=f"uninstall-{fs_manifest_sha}",
        release_manifest_sha256=fs_manifest_sha,
    )
    machine_root = tmp_path / "fs-order" / "machine"
    fs_stores = FilesystemStores(
        machine_root,
        fs_binding.backend_service_name,
        SimpleNamespace(security=_NoopMachineSecurity()),
        ThreadMutex(),
    )
    fs_stores.publish(fs_binding)
    reinstall_op = ReinstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=f"reinstall-{fs_manifest_sha}",
        kind="reinstall",
        request_hash="1" * 64,
        target_release_id=fs_binding.active_release_id,
        data_root=fs_binding.data_root,
        release_manifest_sha256=fs_manifest_sha,
        backend_port=fs_binding.backend_port,
        phase="committed",
        no_return_point=True,
        completed_step="health",
        install_id=fs_binding.install_id,
        dataset_id=fs_binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key=fs_binding.health_attestation_key,
        expected_restore_epoch=fs_binding.expected_restore_epoch,
    )
    fs_stores.archive_committed(reinstall_op)
    fs_legacy_uninstall = replace(
        baseline_after_reinstall,
        operation_id=fs_uninstall_req.operation_id,
        request_hash=_legacy_uninstall_request_hash(fs_binding),
        data_root=fs_binding.data_root,
        release_manifest_sha256=fs_manifest_sha,
        install_id=fs_binding.install_id,
        dataset_id=fs_binding.dataset_id,
        expected_restore_epoch=fs_binding.expected_restore_epoch,
    )
    fs_stores.archive_committed(fs_legacy_uninstall)

    (fs_app_dir / "releases" / "1.3.0" / "backend" / "ticketbox-backend.exe").unlink()
    (fs_app_dir / "releases" / "1.3.0" / "backend").rmdir()
    (fs_app_dir / "releases" / "1.3.0" / "release-manifest.json").unlink()
    (fs_app_dir / "releases" / "1.3.0").rmdir()
    (fs_app_dir / "releases").rmdir()

    binding_file = machine_root / "installation.json"
    reinstall_file = machine_root / "operations" / "history" / f"{reinstall_op.operation_id}.json"
    uninstall_file = machine_root / "operations" / "history" / f"{fs_uninstall_req.operation_id}.json"

    # Case 2a: uninstall strictly AFTER reinstall & binding -> replay SUCCEEDS.
    os.utime(binding_file, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    os.utime(reinstall_file, ns=(1_700_000_010_000_000_000, 1_700_000_010_000_000_000))
    os.utime(uninstall_file, ns=(1_700_000_020_000_000_000, 1_700_000_020_000_000_000))
    check_uninstall_preflight(fs_stores.as_lifecycle_stores())
    fs_replay = uninstall(fs_stores.as_lifecycle_stores(), fs_uninstall_req, make_platform(fs_uninstall_req))
    assert fs_replay.ok is True
    assert fs_replay.phase == "committed"

    # Case 2b: tie timestamp (uninstall == reinstall) -> FAILS CLOSED (strict manifest check).
    os.utime(uninstall_file, ns=(1_700_000_010_000_000_000, 1_700_000_010_000_000_000))
    with pytest.raises(LifecycleViolation) as tie_exc:
        uninstall(fs_stores.as_lifecycle_stores(), fs_uninstall_req, make_platform(fs_uninstall_req))
    assert tie_exc.value.code == "uninstall_release_manifest_missing"

    # Case 2c: uninstall strictly BEFORE reinstall -> FAILS CLOSED (strict manifest check).
    os.utime(uninstall_file, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    os.utime(binding_file, ns=(1_700_000_010_000_000_000, 1_700_000_010_000_000_000))
    os.utime(reinstall_file, ns=(1_700_000_020_000_000_000, 1_700_000_020_000_000_000))
    with pytest.raises(LifecycleViolation) as before_exc:
        uninstall(fs_stores.as_lifecycle_stores(), fs_uninstall_req, make_platform(fs_uninstall_req))
    assert before_exc.value.code == "uninstall_release_manifest_missing"

    # Case 2d: reinstall history file MISSING while legacy uninstall predates installation.json -> FAILS CLOSED.
    reinstall_file.unlink()
    with pytest.raises(LifecycleViolation) as missing_reinstall_exc:
        uninstall(fs_stores.as_lifecycle_stores(), fs_uninstall_req, make_platform(fs_uninstall_req))
    assert missing_reinstall_exc.value.code == "uninstall_release_manifest_missing"

    # Case 2e: reinstall history file MISSING and legacy uninstall ties installation.json -> FAILS CLOSED.
    os.utime(uninstall_file, ns=(1_700_000_010_000_000_000, 1_700_000_010_000_000_000))
    with pytest.raises(LifecycleViolation) as binding_tie_exc:
        uninstall(fs_stores.as_lifecycle_stores(), fs_uninstall_req, make_platform(fs_uninstall_req))
    assert binding_tie_exc.value.code == "uninstall_release_manifest_missing"
