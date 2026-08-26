from __future__ import annotations

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
        "last_adapter_result": "owner_claim:claimed",
        "install_id": INSTALL_ID,
        "dataset_id": DATASET_ID,
        "schema_revision": "20260821_0001",
    }


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
    monkeypatch.setenv("TICKETBOX_DATA_DIR", str(preset))
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)

    assert launch.configure_environment() == preset.resolve()
    assert (preset / "uploads").is_dir()


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


def test_frozen_runtime_admits_active_fresh_install_before_binding_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "operations/active.json", _active(data_root))

    assert launch.configure_environment() == data_dir.resolve()


def test_frozen_runtime_admits_committed_active_only_with_exact_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    launch = _load_launch_module()
    program_data, data_root, data_dir = _configure_frozen(monkeypatch, launch, tmp_path)
    _write_authority(program_data, "installation.json", _binding(data_root))
    active = _active(data_root)
    active["phase"] = "committed"
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
    active["release_manifest_sha256"] = "c" * 64
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
        "TICKETBOX_PORT=9999\n",
        encoding="utf-8",
    )

    launch.configure_environment()

    assert os.environ["TICKETBOX_DATA_DIR"] == str(data_dir.resolve())
    assert os.environ["TICKETBOX_INSTALLATION_ID"] == INSTALL_ID
    assert os.environ["TICKETBOX_DATASET_ID"] == DATASET_ID
    assert os.environ["TICKETBOX_RELEASE_ID"] == RELEASE_ID
    assert os.environ["TICKETBOX_OWNER_RECOVERY_CHANNEL"] == "managed_host"
    assert os.environ["TICKETBOX_PORT"] == "8000"


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
