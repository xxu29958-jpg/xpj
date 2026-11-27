"""Core upgrade admission, preflight, CLI, and error-reporting contract tests."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _upgrade_lifecycle_fixtures import (
    DATASET_ID,
    INSTALL_ID,
    FakeUpgradePlatform,
    _build_physical_installation,
    _build_staged_release,
    _make_upgrade_fixture,
    _stopped_pg_runner,
)
from ticketbox_lifecycle.cli import main as lifecycle_main
from ticketbox_lifecycle.domain.upgrade import upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation
from ticketbox_lifecycle.runtime.filesystem_stores import _managed_connector_present
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform
from ticketbox_lifecycle.schemas import (
    REQUEST_SCHEMA,
    InstallationBinding,
    InstallRequest,
)
from ticketbox_lifecycle.upgrade_cli import _read_durable_failure_status


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
        cast(Any, SimpleNamespace(_mutex=ThreadMutex())),
        _stopped_pg_runner(),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
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
        from ticketbox_lifecycle.runtime.windows_file_security import (
            WindowsFileSecurity,
        )
        from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter

        user_writable_stage = real_app.parent / "Ticketbox-UpgradeStage" / "1.3.0"
        user_writable_stage.mkdir(parents=True, exist_ok=True)
        real_sec = WindowsSecurityAdapter(_stopped_pg_runner(), WindowsFileSecurity())
        with pytest.raises(LifecycleViolation) as stage_acl_exc:
            real_sec.verify_upgrade_stage_directory(user_writable_stage)
        assert stage_acl_exc.value.code == "untrusted_stage_root"

        req_real = replace(req_spoof, app_dir=str(real_app), data_root=str(real_pd / "data"), program_data_root=str(real_pd))
        plat_real = WindowsUpgradePlatform(
            cast(Any, SimpleNamespace(_mutex=ThreadMutex())),
            _stopped_pg_runner(),
            real_sec,
            cast(Any, SimpleNamespace()),
            cast(Any, SimpleNamespace()),
            staged_release_root=user_writable_stage,
            expected_app_dir=real_app,
            expected_program_data_root=real_pd,
        )
        with pytest.raises(LifecycleViolation) as plat_acl_exc:
            plat_real.verify_staged_release(req_real)
        assert plat_acl_exc.value.code == "untrusted_stage_root"


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

    setattr(platform, "check_backup_disk_space", fail_on_second_space_check)
    result = upgrade(stores.as_lifecycle_stores(), request, platform)

    assert result.ok is False
    assert result.code == "cold_space_insufficient"
    assert space_calls == 2
    assert "stop_services" not in platform.events
    assert adapters.scm.fence_calls == 0


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
            command=cast(Any, command),
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
