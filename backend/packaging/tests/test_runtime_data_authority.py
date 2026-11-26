from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

INSTALL_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "22222222-2222-4222-8222-222222222222"
OPERATION_ID = "33333333-3333-4333-8333-333333333333"
RELEASE_ID = "1.2.0"
MANIFEST_SHA = "a" * 64
HEALTH_ATTESTATION_KEY = "c" * 64


def _load_launch_module():
    launch_path = Path(__file__).resolve().parents[1] / "launch.py"
    spec = importlib.util.spec_from_file_location("ticketbox_runtime_authority", launch_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(data_root: Path) -> dict[str, object]:
    return {
        "schema": "ticketbox-installed-instance-v1",
        "install_id": INSTALL_ID,
        "dataset_id": DATASET_ID,
        "expected_restore_epoch": 0,
        "data_root": str(data_root),
        "active_release_id": RELEASE_ID,
        "previous_release_id": None,
        "release_manifest_sha256": MANIFEST_SHA,
        "postgres_major": 17,
        "pg_service_name": "TicketboxPg",
        "backend_service_name": "TicketboxBackend",
        "pg_port": 5432,
        "backend_port": 8000,
        "health_attestation_key": HEALTH_ATTESTATION_KEY,
    }


def _active(data_root: Path) -> dict[str, object]:
    return {
        "schema": "ticketbox-lifecycle-operation-v2",
        "operation_id": OPERATION_ID,
        "kind": "install",
        "request_hash": "b" * 64,
        "target_release_id": RELEASE_ID,
        "data_root": str(data_root),
        "release_manifest_sha256": MANIFEST_SHA,
        "backend_port": 8000,
        "phase": "data_ready",
        "no_return_point": True,
        "completed_step": "owner_claim",
        "install_id": INSTALL_ID,
        "dataset_id": DATASET_ID,
        "schema_revision": "20260821_0001",
        "health_attestation_key": HEALTH_ATTESTATION_KEY,
    }


def _connector_operation() -> dict[str, object]:
    request = {
        "schema": "ticketbox-connector-request-v1", "profile": "cloudflare-tunnel-v1", "action": "configure",
        "operation_id": OPERATION_ID, "install_id": INSTALL_ID, "dataset_id": DATASET_ID,
        "expected_restore_epoch": 0, "release_manifest_sha256": MANIFEST_SHA,
        "expected_revision": 0, "expected_credential_generation": 0, "expected_enabled": False,
        "expected_public_origin_revision": 3, "initiator_sid": "S-1-5-21-1-2-3-1001", "desired_enabled": True,
        "closing_operation_id": None, "closing_request_hash": None,
    }
    return {
        "schema": "ticketbox-lifecycle-operation-v3", "kind": "connector", "impact": "connector_only",
        "operation_id": OPERATION_ID,
        "request_hash": hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "request": request, "phase": "prepared", "completed_step": None, "result_code": "running",
        "replaced_operation": None,
    }


@pytest.mark.parametrize("phase", ["prepared", "applying", "failed_recoverable", "manual_intervention", "committed"])
def test_exact_connector_operation_preserves_binding_without_becoming_startup_authority(monkeypatch, tmp_path, phase):
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    binding = _binding(data_root)
    active = _connector_operation()
    active["phase"] = phase
    if phase == "committed":
        active["completed_step"] = "host_applied"
    _write_authority(program_data, "installation.json", binding)
    _write_authority(program_data, "operations/active.json", active)
    assert launch._closed_authorities(binding, active) == [binding]
    assert launch._assert_vnext_runtime_authority(data_dir) == HEALTH_ATTESTATION_KEY
    assert os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] == "0"


@pytest.mark.parametrize("change", ["install_id", "dataset_id", "epoch", "manifest", "kind", "impact", "schema", "hash", "extra", "action", "binding_missing"])
def test_connector_mismatch_never_unfences_backend(monkeypatch, tmp_path, change):
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    active = _connector_operation()
    request = active["request"]
    if change in {"install_id", "dataset_id"}:
        request[change] = OPERATION_ID
    elif change == "epoch":
        request["expected_restore_epoch"] = 1
    elif change == "manifest":
        request["release_manifest_sha256"] = "d" * 64
    elif change in {"kind", "impact", "schema"}:
        active[change] = "unrecognized"
    elif change == "extra":
        request["exe"] = "arbitrary.exe"
    elif change == "action":
        request["action"] = "repair"
    active["request_hash"] = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if change == "hash":
        active["request_hash"] = "e" * 64
    if change != "binding_missing":
        _write_authority(program_data, "installation.json", _binding(data_root))
    _write_authority(program_data, "operations/active.json", active)
    with pytest.raises(RuntimeError):
        launch._assert_vnext_runtime_authority(data_dir)


def _configure_frozen(
    monkeypatch: pytest.MonkeyPatch,
    launch,
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    program_data = tmp_path / "ProgramData"
    data_root = program_data / "Ticketbox" / "data"
    data_dir = data_root / "app"
    executable = tmp_path / "Ticketbox" / "releases" / RELEASE_ID / "backend" / "ticketbox-backend.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("frozen", encoding="utf-8")
    monkeypatch.setenv("PROGRAMDATA", str(program_data))
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", INSTALL_ID)
    monkeypatch.setenv("TICKETBOX_DATASET_ID", DATASET_ID)
    monkeypatch.setenv("TICKETBOX_RELEASE_ID", RELEASE_ID)
    monkeypatch.setenv("TICKETBOX_OWNER_RECOVERY_CHANNEL", "managed_host")
    monkeypatch.setenv("TICKETBOX_PORT", "8000")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "executable", str(executable), raising=False)
    return program_data, data_root, data_dir


def _write_authority(program_data: Path, relative: str, payload: dict[str, object]) -> Path:
    path = program_data / "Ticketbox" / "machine" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_source_runtime_uses_explicit_data_dir_without_installed_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    preset = tmp_path / "source-data"
    monkeypatch.setenv("TICKETBOX_HEALTH_ATTESTATION_KEY", "ambient")
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)

    assert launch.configure_environment() == preset.resolve()
    assert (preset / "uploads").is_dir()
    assert "TICKETBOX_HEALTH_ATTESTATION_KEY" not in os.environ


def test_frozen_service_initializes_runtime_settings_before_app_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    events: list[str] = []

    class AppMain(ModuleType):
        def __getattribute__(self, name: str):
            if name == "app":
                events.append("app-import")
                return object()
            return super().__getattribute__(name)

    uvicorn = ModuleType("uvicorn")
    uvicorn.run = lambda *_args, **_kwargs: events.append("serve")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
    monkeypatch.setitem(sys.modules, "app.main", AppMain("app.main"))
    monkeypatch.setattr("logging.config.dictConfig", lambda _config: None)
    monkeypatch.setattr(launch, "configure_environment", lambda: tmp_path)
    monkeypatch.setattr(
        launch,
        "_initialize_installed_runtime_settings",
        lambda _data_dir: events.append("initialize"),
        raising=False,
    )
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "executable", str(tmp_path / "ticketbox-backend.exe"), raising=False)

    assert launch.main() is None
    assert events == ["initialize", "app-import", "serve"]


def test_installed_runtime_settings_initializer_uses_existing_create_only_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import runtime_settings_store as store

    launch = _load_launch_module()
    observed: list[tuple[Path, object, bool]] = []

    def initialize(path: Path, projection: object, *, service_owned: bool) -> object:
        observed.append((path, projection, service_owned))
        return projection

    monkeypatch.setattr(store, "initialize_runtime_settings", initialize)
    launch._initialize_installed_runtime_settings(tmp_path)

    assert observed == [
        (
            tmp_path / "runtime-settings" / "runtime-settings.json",
            store.RuntimeSettingsProjection("", False),
            True,
        )
    ]
    assert (tmp_path / "runtime-settings").is_dir()


def test_frozen_runtime_requires_complete_explicit_service_authority_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    _program_data, _data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    monkeypatch.delenv("TICKETBOX_INSTALLATION_ID")

    with pytest.raises(RuntimeError, match="TICKETBOX_INSTALLATION_ID"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_requires_binding_or_active_operation_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    _program_data, _data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)

    with pytest.raises(RuntimeError, match="runtime authority"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_admits_exact_installation_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))

    assert launch.configure_environment() == data_dir.resolve()
    assert (data_dir / "uploads").is_dir()
    assert os.environ["TICKETBOX_HEALTH_ATTESTATION_KEY"] == HEALTH_ATTESTATION_KEY


@pytest.mark.parametrize("phase,step,verify_only", [
    ("data_ready", "owner_claim", "1"), ("committed", "health", "0"),
])
def test_restore_authority_controls_verification_even_with_forged_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, phase: str, step: str, verify_only: str,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    binding = {**_binding(data_root), "expected_restore_epoch": 3}
    active = {**_active(data_root), "kind": "restore", "phase": phase, "completed_step": step, "expected_restore_epoch": 3}
    if phase == "committed":
        _write_authority(program_data, "installation.json", binding)
    _write_authority(program_data, "operations/active.json", active)
    data_dir.mkdir(parents=True)
    (data_dir / ".env").write_text("TICKETBOX_RESTORE_VERIFY_ONLY=0\nTICKETBOX_EXPECTED_RESTORE_EPOCH=0\n")

    assert launch.configure_environment() == data_dir.resolve()
    assert os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] == "3"
    assert os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] == verify_only


@pytest.mark.parametrize("phase,step", [("prepared", None), ("failed_recoverable", "owner_claim")])
def test_interrupted_restore_cannot_start_business_with_published_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, phase: str, step: str | None,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", {**_binding(data_root), "expected_restore_epoch": 1})
    _write_authority(program_data, "operations/active.json", {
        **_active(data_root), "kind": "restore", "phase": phase, "completed_step": step, "expected_restore_epoch": 1,
    })
    with pytest.raises(RuntimeError):
        launch.configure_environment()
    assert not (data_dir / "uploads").exists()


def test_completed_restore_reboot_reads_positive_epoch_from_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", {**_binding(data_root), "expected_restore_epoch": 1})
    monkeypatch.setenv("TICKETBOX_RESTORE_VERIFY_ONLY", "1")
    launch.configure_environment()
    assert os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] == "0"
    assert os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] == "1"


def test_restore_verification_requires_expected_generation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "operations/active.json", {**_active(data_root), "kind": "restore"})
    with pytest.raises(RuntimeError):
        launch.configure_environment()
    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_admits_active_fresh_install_before_binding_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "operations/active.json", _active(data_root))

    assert launch.configure_environment() == data_dir.resolve()
    assert os.environ["TICKETBOX_HEALTH_ATTESTATION_KEY"] == HEALTH_ATTESTATION_KEY


def test_active_fresh_install_never_probes_unpublished_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    active = _active(data_root)
    active["phase"] = "release_activated"
    active["completed_step"] = "health"
    _write_authority(program_data, "operations/active.json", active)
    original_lstat = Path.lstat
    binding_probes = 0

    def lstat(path: Path):
        nonlocal binding_probes
        if path.name == "installation.json":
            binding_probes += 1
            raise PermissionError("Windows hides the unpublished binding behind its protected parent")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat)

    assert launch.configure_environment() == data_dir.resolve()
    assert binding_probes == 0


def test_frozen_runtime_rejects_failed_recoverable_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    active = _active(data_root)
    active["phase"] = "failed_recoverable"
    _write_authority(program_data, "operations/active.json", active)

    with pytest.raises(RuntimeError, match="runtime-capable install phase"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_rejects_active_before_owner_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    active = _active(data_root)
    active["completed_step"] = "alembic"
    _write_authority(program_data, "operations/active.json", active)

    with pytest.raises(RuntimeError, match="runtime progress is not closed"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_admits_committed_active_only_with_exact_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))
    active = _active(data_root)
    active["phase"] = "committed"
    active["completed_step"] = "health"
    _write_authority(program_data, "operations/active.json", active)

    assert launch.configure_environment() == data_dir.resolve()


def test_frozen_runtime_rejects_committed_active_without_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    active = _active(data_root)
    active["phase"] = "committed"
    active["completed_step"] = "health"
    _write_authority(program_data, "operations/active.json", active)

    with pytest.raises(RuntimeError, match="committed active operation requires installation binding"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_rejects_disagreeing_temporal_authorities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))
    active = _active(data_root)
    active["phase"] = "committed"
    active["completed_step"] = "health"
    active["health_attestation_key"] = "d" * 64
    _write_authority(program_data, "operations/active.json", active)

    with pytest.raises(RuntimeError, match="authorities disagree"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_frozen_runtime_rejects_reparse_ancestor_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))
    original_lstat = Path.lstat

    def marked_lstat(path: Path):
        if path.name == "machine":
            return SimpleNamespace(
                st_mode=stat.S_IFLNK,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", marked_lstat)
    with pytest.raises(RuntimeError, match="reparse point"):
        launch.configure_environment()

    assert not (data_dir / "uploads").exists()


def test_dotenv_cannot_replace_frozen_service_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))
    data_dir.mkdir(parents=True)
    (data_dir / ".env").write_text(
        "TICKETBOX_DATA_DIR=C:\\attacker\n"
        "TICKETBOX_INSTALLATION_ID=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n"
        "TICKETBOX_DATASET_ID=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb\n"
        "TICKETBOX_RELEASE_ID=attacker\n"
        "TICKETBOX_OWNER_RECOVERY_CHANNEL=operator\n"
        "TICKETBOX_PORT=9999\n"
        + "TICKETBOX_HEALTH_ATTESTATION_KEY="
        + "d" * 64
        + "\n",
        encoding="utf-8",
    )

    launch.configure_environment()

    assert os.environ["TICKETBOX_DATA_DIR"] == str(data_dir.resolve())
    assert os.environ["TICKETBOX_INSTALLATION_ID"] == INSTALL_ID
    assert os.environ["TICKETBOX_DATASET_ID"] == DATASET_ID
    assert os.environ["TICKETBOX_RELEASE_ID"] == RELEASE_ID
    assert os.environ["TICKETBOX_OWNER_RECOVERY_CHANNEL"] == "managed_host"
    assert os.environ["TICKETBOX_PORT"] == "8000"
    assert os.environ["TICKETBOX_HEALTH_ATTESTATION_KEY"] == HEALTH_ATTESTATION_KEY


def test_runtime_entrypoint_contains_no_retired_marker_or_recovery_fallback() -> None:
    launch = _load_launch_module()
    source = Path(launch.__file__).read_text(encoding="utf-8")
    for token in (
        "TICKETBOX_DATA_ROOT_MARKER_PATH",
        "TICKETBOX_DATA_VOLUME_IDENTITY",
        "TICKETBOX_BOOTSTRAP_RECOVERY_GUARD_PATH",
        "TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH",
        "_InstallerRuntimeRecoveryGuard",
    ):
        assert token not in source


def test_fresh_owner_helper_consumes_secret_on_stdin_and_returns_pairing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    passfile = tmp_path / "pgpass"
    passfile.write_text("sealed", encoding="utf-8")
    for key in tuple(os.environ):
        if key.upper().startswith("PG"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PGPASSFILE", str(passfile))
    observed: dict[str, object] = {}

    class FakeEngine:
        def dispose(self):
            observed["disposed"] = True

    class FakeSession:
        def __init__(self, engine, *, expire_on_commit):
            observed["engine"] = engine
            observed["expire_on_commit"] = expire_on_commit

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            observed["statement"] = str(statement)

        def commit(self):
            observed["committed"] = True

    @dataclass(frozen=True)
    class Result:
        contract: str = "ticketbox-installation-owner-pairing-v1"
        operation_id: str = "op-1"
        installation_id: str = "install-1"
        account_name: str = "我"
        ledger_id: str = "default"
        ledger_name: str = "我的小票夹"
        device_name: str = "Windows 安装来源"
        pairing_code: str = "12345678"
        pairing_expires_at: str = "2026-08-25T12:00:00Z"
        pairing_derivation_index: int = 0
        claim_generation: int = 1

    import sqlalchemy
    import sqlalchemy.orm

    from app.services import identity_service, secure_file

    engine = FakeEngine()

    @contextmanager
    def hold_machine_secret(path: Path):
        assert path == passfile
        observed["machine_secret_held"] = True
        try:
            yield path
        finally:
            observed["machine_secret_held"] = False
            observed["machine_secret_released"] = True

    def create_engine(*_args, **_kwargs):
        assert observed.get("machine_secret_held") is True
        return engine

    monkeypatch.setattr(secure_file, "hold_installer_machine_secret_for_read", hold_machine_secret)
    monkeypatch.setattr(sqlalchemy, "create_engine", create_engine)
    monkeypatch.setattr(sqlalchemy.orm, "Session", FakeSession)
    monkeypatch.setattr(identity_service, "bootstrap_installation_owner", lambda _db, **_kwargs: Result())
    output = StringIO()

    assert launch._run_fresh_owner_claim(
        [
            "--fresh-owner-claim",
            "--database-url",
            "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256",
            "--pgpassfile",
            str(passfile),
            "--operation-id",
            "op-1",
            "--installation-id",
            "install-1",
        ],
        input_stream=BytesIO(b"a" * 64 + b"\n"),
        output_stream=output,
    ) == 0
    assert observed["committed"] is True
    assert observed["disposed"] is True
    assert observed["machine_secret_released"] is True
    assert json.loads(output.getvalue())["pairing_code"] == "12345678"


def test_frozen_runtime_admits_valid_previous_release_id_and_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", {**_binding(data_root), "previous_release_id": "1.1.0"})

    assert launch.configure_environment() == data_dir.resolve()
    assert os.environ["TICKETBOX_UPGRADE_VERIFY_ONLY"] == "0"
    assert os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] == "0"

    for invalid in (RELEASE_ID, "", "bad release!", 123):
        _write_authority(program_data, "installation.json", {**_binding(data_root), "previous_release_id": invalid})
        with pytest.raises(RuntimeError, match="unsupported release transition"):
            launch.configure_environment()


@pytest.mark.parametrize("phase,step,verify_only", [
    ("data_ready", "scm", "1"),
    ("committed", "health", "0"),
])
def test_upgrade_authority_controls_readonly_verification_even_with_forged_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    step: str,
    verify_only: str,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    old_binding = {
        **_binding(data_root),
        "expected_restore_epoch": 2,
        "active_release_id": "1.1.0",
        "previous_release_id": None,
        "release_manifest_sha256": "d" * 64,
        "health_attestation_key": "f" * 64,
    }
    committed_binding = {**_binding(data_root), "expected_restore_epoch": 2, "previous_release_id": "1.1.0"}
    active = {
        **_active(data_root),
        "kind": "upgrade",
        "phase": phase,
        "completed_step": step,
        "expected_restore_epoch": 2,
        "previous_release_id": "1.1.0",
        "previous_release_manifest_sha256": "d" * 64,
        "source_schema_revision": "20261029_0002",
        "backup_path": r"C:\ProgramData\Ticketbox\backups\pre.tbxcold",
        "backup_sha256": "e" * 64,
        "business_writes_opened": phase == "committed",
    }
    _write_authority(
        program_data,
        "installation.json",
        committed_binding if phase == "committed" else old_binding,
    )
    _write_authority(program_data, "operations/active.json", active)
    data_dir.mkdir(parents=True)
    (data_dir / ".env").write_text("TICKETBOX_UPGRADE_VERIFY_ONLY=0\nTICKETBOX_EXPECTED_RESTORE_EPOCH=0\n")

    assert launch.configure_environment() == data_dir.resolve()
    assert os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] == "2"
    assert os.environ["TICKETBOX_UPGRADE_VERIFY_ONLY"] == verify_only
    assert os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] == "0"
    assert os.environ["TICKETBOX_HEALTH_ATTESTATION_KEY"] == HEALTH_ATTESTATION_KEY


@pytest.mark.parametrize("tamper", ["missing", "dataset_id", "epoch", "release_lineage"])
def test_upgrade_candidate_requires_exact_existing_installation_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    old_binding = {
        **_binding(data_root),
        "expected_restore_epoch": 2,
        "active_release_id": "1.1.0",
        "previous_release_id": None,
        "release_manifest_sha256": "d" * 64,
        "health_attestation_key": "f" * 64,
    }
    active = {
        **_active(data_root),
        "kind": "upgrade",
        "phase": "data_ready",
        "completed_step": "scm",
        "expected_restore_epoch": 2,
        "previous_release_id": "1.1.0",
        "previous_release_manifest_sha256": "d" * 64,
        "source_schema_revision": "20261029_0002",
        "backup_path": r"C:\ProgramData\Ticketbox\backups\pre.tbxcold",
        "backup_sha256": "e" * 64,
        "business_writes_opened": False,
    }
    _write_authority(program_data, "operations/active.json", active)
    if tamper != "missing":
        if tamper == "dataset_id":
            old_binding["dataset_id"] = OPERATION_ID
        elif tamper == "epoch":
            old_binding["expected_restore_epoch"] = 0
        elif tamper == "release_lineage":
            old_binding["active_release_id"] = "1.0.0"
        _write_authority(program_data, "installation.json", old_binding)
    with pytest.raises(RuntimeError):
        launch.configure_environment()
    assert not (data_dir / "uploads").exists()


@pytest.mark.parametrize("phase,step", [("prepared", "alembic"), ("failed_recoverable", "scm")])
def test_interrupted_upgrade_cannot_start_business_with_existing_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    step: str,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", {**_binding(data_root), "previous_release_id": "1.1.0"})
    _write_authority(program_data, "operations/active.json", {
        **_active(data_root),
        "kind": "upgrade",
        "phase": phase,
        "completed_step": step,
        "expected_restore_epoch": 0,
        "previous_release_id": "1.1.0",
        "source_schema_revision": "20261029_0002",
        "backup_path": r"C:\ProgramData\Ticketbox\backups\pre.tbxcold",
        "backup_sha256": "e" * 64,
        "business_writes_opened": False,
    })
    with pytest.raises(RuntimeError):
        launch.configure_environment()
    assert not (data_dir / "uploads").exists()


def test_upgrade_candidate_rejects_business_writes_opened_before_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    old_binding = {
        **_binding(data_root),
        "active_release_id": "1.1.0",
        "release_manifest_sha256": "d" * 64,
        "health_attestation_key": "f" * 64,
    }
    active = {
        **_active(data_root),
        "kind": "upgrade",
        "phase": "data_ready",
        "completed_step": "scm",
        "expected_restore_epoch": 0,
        "previous_release_id": "1.1.0",
        "previous_release_manifest_sha256": "d" * 64,
        "source_schema_revision": "20261029_0002",
        "backup_path": r"C:\ProgramData\Ticketbox\backups\pre.tbxcold",
        "backup_sha256": "e" * 64,
        "business_writes_opened": True,
    }
    _write_authority(program_data, "installation.json", old_binding)
    _write_authority(program_data, "operations/active.json", active)
    with pytest.raises(RuntimeError, match="business writes opened"):
        launch.configure_environment()
    assert not (data_dir / "uploads").exists()


@pytest.mark.parametrize("phase,step,verify_only", [
    ("data_ready", "scm", "1"),
    ("committed", "health", "0"),
])
def test_reinstall_authority_admits_verify_only_then_normal_preserving_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    step: str,
    verify_only: str,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    binding = {**_binding(data_root), "expected_restore_epoch": 2}
    active = {
        **_active(data_root),
        "kind": "reinstall",
        "phase": phase,
        "completed_step": step,
        "expected_restore_epoch": 2,
    }
    _write_authority(program_data, "installation.json", binding)
    _write_authority(program_data, "operations/active.json", active)
    assert launch.configure_environment() == data_dir.resolve()
    assert os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] == "2"
    assert os.environ["TICKETBOX_UPGRADE_VERIFY_ONLY"] == verify_only
    assert os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] == "0"


def test_existing_dataset_upgrade_backup_archive_validates_recovery_point_and_local_postgres_tree(
    tmp_path: Path,
) -> None:
    import hashlib
    import zipfile

    from app.database._existing_dataset_upgrade import (
        ExistingDatasetUpgradeError,
        _VerifiedBackupArchive,
    )

    install_id = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    source_rev = "20261029_0002"
    release_id = "1.2.1"

    app_dir = tmp_path / "app"
    pg_files = {
        "postgresql/bin/postgres.exe": b"pg17-postgres-bytes",
        "postgresql/bin/pg_controldata.exe": b"pg17-controldata-bytes",
    }
    for rel, content in pg_files.items():
        path = app_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def write_archive(
        dest: Path,
        *,
        recovery_point: dict | None = None,
        archive_pg_files: dict[str, bytes] | None = None,
    ) -> str:
        prog = {
            **(pg_files if archive_pg_files is None else archive_pg_files),
            f"releases/{release_id}/backend/ticketbox-backend.exe": b"backend-bytes",
        }
        manifest_payload = {
            "schema": "ticketbox-release-manifest-v1",
            "release_id": release_id,
            "product_version": release_id,
            "max_schema_revision": source_rev,
            "min_semantic_revision": "ticketbox-dataset-semantics-v1",
            "immutable_payload": {
                "algorithm": "SHA-256",
                "files": [
                    {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    for rel, data in sorted(prog.items())
                ],
            },
        }
        manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        members: dict[str, bytes] = {
            "data/pgdata/PG_VERSION": b"17\n",
            "data/pgdata/global/pg_control": b"pg-ctrl",
            "data/app/.env": b"TICKETBOX_ENV=1\n",
            "machine/installation.json": json.dumps({
                "schema": "ticketbox-installed-instance-v1",
                "install_id": install_id,
                "dataset_id": dataset_id,
                "expected_restore_epoch": 0,
                "active_release_id": release_id,
                "release_manifest_sha256": manifest_sha,
            }).encode("utf-8"),
            "machine/secrets/postgres.password": b"pw1",
            "machine/secrets/ticketbox_migrator.password": b"pw2",
            "machine/secrets/ticketbox_runtime.password": b"pw3",
            "machine/secrets/pgpass": b"pgpass",
            f"machine/operations/history/fresh-{manifest_sha}.json": json.dumps({
                "schema": "ticketbox-lifecycle-operation-v2",
                "operation_id": f"fresh-{manifest_sha}",
                "kind": "install",
                "phase": "committed",
                "install_id": install_id,
                "dataset_id": dataset_id,
                "target_release_id": release_id,
                "release_manifest_sha256": manifest_sha,
            }).encode("utf-8"),
            f"program/releases/{release_id}/release-manifest.json": manifest_bytes,
            **{f"program/{rel}": data for rel, data in prog.items()},
        }
        entries: dict[str, dict[str, object] | None] = {
            "program/": None,
            "machine/": None,
            "data/pgdata/": None,
            "data/attachments/": None,
            "data/app/": None,
        }
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
            for d in entries:
                zf.writestr(d, b"")
            for name, data in sorted(members.items()):
                zf.writestr(name, data)
                entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            cold_copy: dict[str, object] = {
                "schema": "ticketbox-beta-cold-copy-v2",
                "complete": True,
                "public_connectivity": {
                    "excluded_directory": "machine/connectors/cloudflare/secrets",
                    "credentials": "not_backed_up",
                    "after_restore": "configure_again",
                },
                "identity": {
                    "install_id": install_id,
                    "dataset_id": dataset_id,
                    "restore_epoch": 0,
                    "release_id": release_id,
                    "release_manifest_sha256": manifest_sha,
                    "schema_revision": source_rev,
                    "postgres_major": 17,
                },
                "entries": entries,
            }
            if recovery_point is not None:
                cold_copy["recovery_point"] = recovery_point
            zf.writestr("COLD_COPY.json", json.dumps(cold_copy).encode("utf-8"))
        return hashlib.sha256(dest.read_bytes()).hexdigest()

    # Valid archive with exact PG tree and valid recovery_point succeeds.
    good_rp = {
        "cutoff_utc": "2026-11-26T12:00:00Z",
        "api_version": "2026-10-11",
        "semantic_revision": "ticketbox-dataset-semantics-v1",
        "schema_revision": source_rev,
        "secret_disposition": {
            "db_bootstrap_material": "included_in_private_copy_for_rebind",
            "service_db_credentials": "rotated_on_restore",
            "connector_secrets": "excluded_reconfigure_on_target",
            "user_wincred_dpapi": "not_included_non_portable",
        },
        "matching_installer_requirement": {
            "release_id": release_id,
            "release_manifest_sha256": "a" * 64,
            "postgres_major": 17,
            "verify_command": "TicketboxLifecycle.exe verify-cold-copy --source backup.tbxcold",
        },
    }
    good = tmp_path / "good.tbxcold"
    good_sha = write_archive(good, recovery_point=good_rp)
    with _VerifiedBackupArchive(
        good,
        good_sha,
        dataset_id=dataset_id,
        installation_id=install_id,
        expected_restore_epoch=0,
        source_revision=source_rev,
        app_dir=app_dir,
    ):
        pass

    bad_rp = tmp_path / "bad-rp.tbxcold"
    bad_rp_sha = write_archive(bad_rp, recovery_point={"cutoff_utc": "bad"})
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="recovery_point"),
        _VerifiedBackupArchive(
            bad_rp,
            bad_rp_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass

    partial_pg = tmp_path / "partial-pg.tbxcold"
    partial_pg_sha = write_archive(
        partial_pg,
        recovery_point=good_rp,
        archive_pg_files={"postgresql/bin/postgres.exe": b"pg17-postgres-bytes"},
    )
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="PostgreSQL program tree"),
        _VerifiedBackupArchive(
            partial_pg,
            partial_pg_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass

    # Omitting app_dir must fail closed rather than skipping PG tree verification.
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="app_dir is required"),
        _VerifiedBackupArchive(
            good,
            good_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=None,
        ),
    ):
        pass

    # JSON boolean false for restore_epoch must not match expected integer 0.
    bool_epoch_archive = tmp_path / "bool-epoch.tbxcold"
    with zipfile.ZipFile(good, "r") as src, zipfile.ZipFile(bool_epoch_archive, "w", compression=zipfile.ZIP_STORED) as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "COLD_COPY.json":
                manifest = json.loads(data.decode("utf-8"))
                manifest["identity"]["restore_epoch"] = False
                data = json.dumps(manifest).encode("utf-8")
            dst.writestr(name, data)
    bool_epoch_sha = hashlib.sha256(bool_epoch_archive.read_bytes()).hexdigest()
    with (
        pytest.raises(ExistingDatasetUpgradeError, match="identity does not match"),
        _VerifiedBackupArchive(
            bool_epoch_archive,
            bool_epoch_sha,
            dataset_id=dataset_id,
            installation_id=install_id,
            expected_restore_epoch=0,
            source_revision=source_rev,
            app_dir=app_dir,
        ),
    ):
        pass
