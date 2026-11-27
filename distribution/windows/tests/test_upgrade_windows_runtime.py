"""Windows upgrade runtime tests: WindowsUpgradePlatform, SCM start-type, connector rebind, shortcut COM, and NTFS ACLs."""

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
    OLD_KEY,
    OLD_MANIFEST_SHA,
    FakeUpgradePlatform,
    _build_physical_installation,
    _build_staged_release,
    _make_upgrade_fixture,
    _stopped_pg_runner,
)
from fakes import MemoryMutex, make_install_request
from ticketbox_lifecycle.domain.upgrade import upgrade
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
)
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.runtime.windows_shortcut import (
    MANAGER_APP_ID,
    read_shortcut,
    update_manager_start_menu_shortcut,
)
from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REQUEST_SCHEMA,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)


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
        cast(Any, SimpleNamespace(_mutex=ThreadMutex())),
        runner,
        cast(Any, FakeSecurity()),
        cast(Any, FakeScm()),
        cast(Any, FakeObserver()),
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
        cast(Any, SimpleNamespace(_mutex=ThreadMutex())),
        _stopped_pg_runner(),
        cast(Any, SimpleNamespace()),
        cast(Any, NoopScm()),
        cast(Any, DemandPgObserver()),
        expected_app_dir=Path(request.app_dir),
        expected_program_data_root=Path(request.program_data_root),
    )
    with pytest.raises(LifecycleError):
        platform.stop_services_for_backup(request, binding)
    with pytest.raises(LifecycleError):
        platform.verify_pg_service_for_upgrade(request)


def test_pass2_f6_removed_connector_rebinds_and_reconfigures_on_b_and_shortcut_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ticketbox_lifecycle.connector_schema import (
        PROFILE,
        ConnectorState,
        parse_request,
        parse_state,
    )
    from ticketbox_lifecycle.connector_schema import (
        REQUEST_SCHEMA as CONN_REQ_SCHEMA,
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
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
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


def test_pass3_m2_preflight_blocks_residual_connector_secrets_and_bad_state_dacl_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.connector_schema import (
        PROFILE,
        STATE_SCHEMA,
        ConnectorState,
    )
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
