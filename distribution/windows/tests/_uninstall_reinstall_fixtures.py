"""Shared fakes and fixtures for Windows uninstall, reinstall, and purge-data lifecycle tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    InstallationBinding,
    InstallRequest,
    UninstallOperation,
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


class _ProbeRetryJob:
    def __init__(self, events: list[str], on_start: Callable[[Callable[[], None] | None], Any]) -> None:
        self._events = events
        self._on_start = on_start

    def __enter__(self) -> _ProbeRetryJob:
        self._events.append("job_enter")
        return self

    def run_background_starter(
        self,
        argv: list[str],
        *,
        on_timeout: Callable[[], None] | None = None,
        **_kw: Any,
    ) -> Any:
        del argv
        return self._on_start(on_timeout)

    def __exit__(self, *_exc: Any) -> None:
        self._events.append("job_exit")


class _ProbeRetryRunner:
    def __init__(self, pgdata: Path, on_start: Callable[[Callable[[], None] | None], Any]) -> None:
        self.pgdata = pgdata
        self.on_start = on_start
        self.events: list[str] = []
        self.stop_calls = 0
        self.stop_succeeds_on = 2
        self.cluster_running = False

    def reset(self, *, stop_succeeds_on: int, on_start: Callable[[Callable[[], None] | None], Any] | None = None) -> None:
        self.events.clear()
        self.stop_calls = 0
        self.stop_succeeds_on = stop_succeeds_on
        self.cluster_running = False
        pid_file = self.pgdata / "postmaster.pid"
        if pid_file.exists():
            pid_file.unlink()
        if on_start is not None:
            self.on_start = on_start

    def open_managed_job(self) -> _ProbeRetryJob:
        return _ProbeRetryJob(self.events, self.on_start)

    def run(self, argv: list[str], **_kw: Any) -> CompletedCommand:
        exe = Path(argv[0]).name.lower()
        if exe == "pg_controldata.exe":
            state = "in production" if self.cluster_running else "shut down"
            return CompletedCommand(
                tuple(argv),
                0,
                f"Database cluster state:               {state}\n"
                "Database system identifier:           7123456789012345678\n",
                "",
            )
        if exe == "pg_ctl.exe" and "stop" in argv:
            self.stop_calls += 1
            self.events.append(f"pg_ctl_stop_{self.stop_calls}")
            if self.stop_calls >= self.stop_succeeds_on:
                self.cluster_running = False
                pid_file = self.pgdata / "postmaster.pid"
                if pid_file.exists():
                    pid_file.unlink()
                return CompletedCommand(tuple(argv), 0, "", "")
            return CompletedCommand(tuple(argv), 1, "", "stop timed out")
        raise AssertionError(f"unexpected command: {argv}")


def _prepare_probe_retry_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[InstallationBinding, Path, Path, Path]:
    from ticketbox_lifecycle.runtime import windows_security_native as native

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
    return binding, app_dir, program_data, pgdata


class _NoopMachineSecurity:
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


class _RecordingUninstallPlatform:
    def __init__(self, active_release_id: str) -> None:
        self._active_release_id = active_release_id
        self.requests: list[InstallRequest] = []
        self.verify_called = False
        self.unregister_called = False
        self.cleanup_called = False

    def verify_owned_services(self, request: InstallRequest, _binding: InstallationBinding) -> None:
        self.verify_called = True
        self.requests.append(request)

    def verify_registered_release_manifests(self, _request: Any, _binding: Any, **_kw: Any) -> None:
        self.verify_called = True

    def stop_and_unregister_services(self, _request: Any, _binding: Any) -> list[str]:
        self.unregister_called = True
        return ["TicketboxBackend", "TicketboxPg"]

    def remove_start_menu_shortcut(self, _request: Any) -> bool:
        return True

    def cleanup_registered_release_payloads(self, _request: Any, _binding: Any, **_kw: Any) -> list[str]:
        self.cleanup_called = True
        return [self._active_release_id]


def _make_hookable_mutex(mutex_on_acquire: list[Callable[[], object]]) -> Any:
    from ticketbox_lifecycle.runtime.mutex import ThreadMutex

    class HookableMutex(ThreadMutex):
        def acquire(self) -> None:
            super().acquire()
            if mutex_on_acquire:
                hook = mutex_on_acquire.pop(0)
                hook()

    return HookableMutex()


def _setup_from_installed_cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from dataclasses import asdict

    from ticketbox_lifecycle import uninstall_cli
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores

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
    mutex_on_acquire: list[Callable[[], object]] = []
    root_calls = {"install": 0, "program_data": 0}
    platform_box = [_RecordingUninstallPlatform(binding.active_release_id)]

    def _from_installed(*, install_root: Path | None = None, program_data_root: Path | None = None) -> FilesystemStores:
        resolved_pd = program_data_root if program_data_root is not None else program_data
        return FilesystemStores(
            resolved_pd / "machine",
            binding.backend_service_name,
            SimpleNamespace(security=_NoopMachineSecurity()),
            _make_hookable_mutex(mutex_on_acquire),
            install_root=install_root,
            program_data_root=resolved_pd,
        )

    def _counted_install_root() -> Path:
        root_calls["install"] += 1
        return app_dir

    def _counted_program_data_root() -> Path:
        root_calls["program_data"] += 1
        return program_data

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
    monkeypatch.setattr(uninstall_cli, "WindowsUninstallPlatform", lambda *_args, **_kw: platform_box[0])
    binding_path = machine_root / "installation.json"
    active_path = machine_root / "operations" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        uninstall_cli=uninstall_cli,
        app_dir=app_dir,
        program_data=program_data,
        machine_root=machine_root,
        chinese_data_root=chinese_data_root,
        binding=binding,
        binding_raw=json.dumps(asdict(binding), indent=2, sort_keys=True) + "\n",
        manifest_sha=manifest_sha,
        expected_op_id=expected_op_id,
        mutex_on_acquire=mutex_on_acquire,
        root_calls=root_calls,
        platform_box=platform_box,
        binding_path=binding_path,
        active_path=active_path,
    )


def _write_release_manifest(app_dir: Path, release_id: str) -> str:
    backend = app_dir / "releases" / release_id / "backend" / "ticketbox-backend.exe"
    backend.parent.mkdir(parents=True, exist_ok=True)
    backend.write_bytes(f"backend-{release_id}".encode())
    manifest = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "lifecycle_compatibility": ["ticketbox-lifecycle-request-v1"],
        "min_schema_revision": "20260722_0001",
        "max_schema_revision": "20261101_0001",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "signing_state": "release-bound",
        "immutable_payload": {
            "algorithm": "SHA-256",
            "files": [
                {
                    "path": f"releases/{release_id}/backend/ticketbox-backend.exe",
                    "size": backend.stat().st_size,
                    "sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
                },
            ],
        },
    }
    raw = json.dumps(manifest).encode("utf-8")
    (app_dir / "releases" / release_id / "release-manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _make_uninstall_operation(
    *,
    operation_id: str,
    data_root: str,
    release_manifest_sha256: str,
    target_release_id: str = "1.3.0",
    backend_port: int = 8000,
    phase: Literal["prepared", "failed_recoverable", "committed"] = "failed_recoverable",
    no_return_point: bool = True,
    completed_step: str | None = "unregister_services",
    install_id: str = INSTALL_ID,
    dataset_id: str = DATASET_ID,
    expected_restore_epoch: int = 1,
) -> UninstallOperation:
    return UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=operation_id,
        kind="uninstall",
        request_hash="a" * 64,
        target_release_id=target_release_id,
        data_root=data_root,
        release_manifest_sha256=release_manifest_sha256,
        backend_port=backend_port,
        phase=phase,
        no_return_point=no_return_point,
        completed_step=completed_step,
        install_id=install_id,
        dataset_id=dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key="d" * 64,
        expected_restore_epoch=expected_restore_epoch,
    )
