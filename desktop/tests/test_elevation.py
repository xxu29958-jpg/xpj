"""UAC broker contracts: fixed actions, short-lived helper, no elevated HTTP UI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from backend_manager import elevation, runtime_factory, windows_user_security
from backend_manager.__main__ import main
from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig
from backend_manager.elevation import (
    HELPER_EXIT_CONFIG,
    HELPER_EXIT_LIFECYCLE_BUSY,
    HELPER_EXIT_MISSING_SERVICE,
    HELPER_EXIT_NOT_ELEVATED,
    HELPER_EXIT_TIMEOUT,
    ElevatedServiceActionRunner,
    HelperCommand,
    HelperResult,
    HelperResultChannel,
    build_helper_command,
    sanitize_helper_diagnostic,
    start_helper_watchdog,
    write_helper_result,
)
from backend_manager.helper_channel import channel_file_identity, open_exclusive_channel
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.lifecycle_lock import hold_installer_lifecycle_lock
from backend_manager.runtime import RuntimeControlError, ServiceMissingError
from backend_manager.runtime_factory import build_runtime
from backend_manager.windows_service import BrokeredWindowsServiceRuntime, ServiceSnapshot


def _release() -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        service_state_timeout_ms=17_000,
        service_poll_interval_ms=125,
        postgres_ready_timeout_ms=23_000,
        backend_ready_timeout_ms=31_000,
        backend_ready_poll_interval_ms=375,
        backend_health_request_timeout_ms=1_750,
    )


@contextmanager
def _fake_result_channel(action: str, exit_code: int, diagnostic: str):
    class Channel:
        path = Path("result.json")
        root = Path(".")
        nonce = "n" * 43
        owner_sid = "S-1-5-21-1000"
        file_identity = "1:2"

        @staticmethod
        def read(actual_exit_code: int) -> HelperResult | None:
            assert actual_exit_code == exit_code
            return HelperResult(exit_code=exit_code, diagnostic=diagnostic)

    yield Channel()


def test_source_helper_command_reenters_module_with_one_fixed_action(monkeypatch, tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    monkeypatch.setattr(elevation.sys, "executable", str(python))
    monkeypatch.delattr(elevation.sys, "frozen", raising=False)

    channel = HelperResultChannel(
        path=tmp_path / "result.json",
        root=tmp_path,
        nonce="n" * 43,
        action="restart",
        owner_sid="S-1-5-21-1000",
        file_identity="1:2",
    )
    command = build_helper_command("restart", channel, 123_456)

    assert command.executable == python.resolve()
    assert command.arguments == (
        "-m",
        "backend_manager",
        "--elevated-service-action",
        "restart",
        "--helper-result-path",
        str(channel.path),
        "--helper-result-root",
        str(channel.root),
        "--helper-result-nonce",
        channel.nonce,
        "--helper-channel-owner-sid",
        channel.owner_sid,
        "--helper-channel-file-id",
        channel.file_identity,
    )
    assert command.working_dir.name == "desktop"
    assert command.wait_timeout_ms == 123_456


def test_frozen_helper_command_reuses_manager_executable(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "TicketboxManager.exe"
    monkeypatch.setattr(elevation.sys, "executable", str(executable))
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)

    channel = HelperResultChannel(
        path=tmp_path / "result.json",
        root=tmp_path,
        nonce="n" * 43,
        action="stop",
        owner_sid="S-1-5-21-1000",
        file_identity="1:2",
    )
    command = build_helper_command("stop", channel, 87_000)

    assert command == HelperCommand(
        executable=executable.resolve(),
        arguments=(
            "--elevated-service-action",
            "stop",
            "--helper-result-path",
            str(channel.path),
            "--helper-result-root",
            str(channel.root),
            "--helper-result-nonce",
            channel.nonce,
            "--helper-channel-owner-sid",
            channel.owner_sid,
            "--helper-channel-file-id",
            channel.file_identity,
        ),
        working_dir=tmp_path.resolve(),
        wait_timeout_ms=87_000,
    )


@pytest.mark.parametrize(
    ("exit_code", "message"),
    [
        (HELPER_EXIT_CONFIG, "安装信息不可用"),
        (HELPER_EXIT_MISSING_SERVICE, "未找到小票夹 Windows 服务"),
        (HELPER_EXIT_TIMEOUT, "可能仍在完成操作"),
        (HELPER_EXIT_LIFECYCLE_BUSY, "正在安装、升级或卸载"),
        (99, "exit=99"),
    ],
)
def test_action_runner_maps_helper_exit_to_actionable_message(exit_code: int, message: str) -> None:
    diagnostic = f"helper detail: {message}"
    runner = ElevatedServiceActionRunner(
        _release(),
        launcher=lambda command: (
            exit_code
            if command.wait_timeout_ms == 91_500
            else (_ for _ in ()).throw(AssertionError("helper timeout ignored release config"))
        ),
        channel_factory=lambda action: _fake_result_channel(action, exit_code, diagnostic),
    )

    with pytest.raises(RuntimeControlError, match=message if exit_code != 99 else "helper detail"):
        runner.run("start")


def test_helper_watchdog_and_nonce_result_are_bounded_and_secret_redacted(tmp_path: Path, monkeypatch) -> None:
    nonce = "n" * 43
    path = tmp_path / f"{nonce}.json"
    path.touch()
    with open_exclusive_channel(path) as stream:
        file_identity = channel_file_identity(stream)
    path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-manager-helper-result-v1",
                "root": str(tmp_path),
                "nonce": nonce,
                "action": "start",
                "state": "pending",
                "owner_sid": "S-1-5-21-1000",
                "file_identity": file_identity,
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(windows_user_security, "assert_helper_channel_path", lambda *_args: None)
    monkeypatch.setattr(elevation, "validate_exact_file_security", lambda *_args, **_kwargs: None)
    write_helper_result(
        path,
        tmp_path,
        nonce,
        "start",
        "S-1-5-21-1000",
        file_identity,
        HELPER_EXIT_CONFIG,
        "DATABASE_URL=postgresql://owner:super-secret@127.0.0.1/db token=abc123 " + "x" * 1200,
    )
    result = HelperResultChannel(
        path,
        tmp_path,
        nonce,
        "start",
        "S-1-5-21-1000",
        file_identity,
    ).read(HELPER_EXIT_CONFIG)
    assert result is not None
    assert "super-secret" not in result.diagnostic
    assert "abc123" not in result.diagnostic
    assert result.diagnostic == "小票夹安装信息不可用，请修复或重新安装后重试。"
    assert len(result.diagnostic) <= 800
    assert HelperResultChannel(path, tmp_path, "z" * 43, "start", "S-1-5-21-1000", file_identity).read(
        HELPER_EXIT_CONFIG,
    ) is None
    assert sanitize_helper_diagnostic("secret=hunter2", "固定公开错误") == "固定公开错误"
    assert sanitize_helper_diagnostic(
        r"failed at C:\Program Files\Ticketbox\app\.env",
        "固定公开错误",
    ) == "固定公开错误"

    forced = threading.Event()
    exit_codes: list[int] = []

    def force_exit(code: int) -> None:
        exit_codes.append(code)
        forced.set()

    start_helper_watchdog(timeout_seconds=0.01, force_exit=force_exit)

    assert forced.wait(timeout=1)
    assert exit_codes == [HELPER_EXIT_TIMEOUT]


def test_elevated_ui_process_is_refused_before_control_server_starts(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: True)

    with pytest.raises(ConfigError, match="不能以管理员身份运行"):
        main([])


def test_helper_action_without_elevation_cannot_touch_services(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: False)

    assert main(["--elevated-service-action", "stop"]) == HELPER_EXIT_NOT_ELEVATED


def test_elevated_helper_preserves_missing_service_result(monkeypatch, tmp_path: Path) -> None:
    layout = InstalledLayout(
        tmp_path / "program",
        tmp_path / "data",
        8000,
        5432,
        "TicketboxBackend",
        "TicketboxPg",
        "9.8.7-test",
    )
    release = _release()
    config = ManagerConfig(
        runtime=InstalledRuntimeConfig(layout, release),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=layout.backend_version,
        expected_installation_id=layout.installation_id,
        health_request_timeout_seconds=release.backend_health_request_timeout_seconds,
    )

    class BrokenRuntime:
        def stop(self) -> None:
            raise ServiceMissingError("missing")

    events: list[str] = []

    def build_runtime(*_args, backend_stopped_validator=None):
        assert callable(backend_stopped_validator)
        events.append("build")
        return BrokenRuntime()

    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: True)
    monkeypatch.setattr("backend_manager.__main__.start_helper_watchdog", lambda **_kwargs: threading.Event())
    monkeypatch.setattr("backend_manager.__main__.validate_helper_result_channel", lambda *_args: None)
    monkeypatch.setattr("backend_manager.__main__.hold_installer_lifecycle_lock", _no_op_lock)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda **_kwargs: config)
    monkeypatch.setattr(
        "backend_manager.__main__.validate_installed_service_contract",
        lambda _layout, _release_config: events.append("validate"),
    )
    monkeypatch.setattr("backend_manager.__main__.build_direct_service_runtime", build_runtime)
    results: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "backend_manager.__main__.write_helper_result",
        lambda _path, _root, _nonce, _action, _owner_sid, _file_id, code, detail: results.append((code, detail)),
    )

    assert main(
        [
            "--elevated-service-action",
            "stop",
            "--helper-result-path",
            str(tmp_path / "result.json"),
            "--helper-result-root",
            str(tmp_path),
            "--helper-result-nonce",
            "n" * 43,
            "--helper-channel-owner-sid",
            "S-1-5-21-1000",
            "--helper-channel-file-id",
            "1:2",
        ],
    ) == HELPER_EXIT_MISSING_SERVICE
    assert events == ["validate", "build"]
    assert results == [(HELPER_EXIT_MISSING_SERVICE, "missing")]


def _no_op_lock():
    class Guard:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return False

    return Guard()


@pytest.mark.skipif(os.name != "nt", reason="Windows file-share semantics required")
def test_python_lifecycle_lock_interoperates_with_real_powershell_hosts(tmp_path: Path) -> None:
    lock_path = tmp_path / "installer-lifecycle.lock"
    lock_script = Path(__file__).parents[2] / "backend" / "packaging" / "windows_lifecycle_lock.ps1"
    harness = tmp_path / "lock-interoperability.ps1"
    escaped_script = str(lock_script).replace("'", "''")
    escaped_lock = str(lock_path).replace("'", "''")
    harness.write_text(
        "#Requires -Version 5.1\n"
        f". '{escaped_script}'\n"
        f"$lock = Enter-TicketboxExclusiveFileLock '{escaped_lock}'\n"
        "try { exit 0 } finally { $lock.Dispose() }\n",
        encoding="utf-8-sig",
    )
    hosts = [Path(found) for name in ("powershell", "pwsh") if (found := shutil.which(name))]
    assert hosts, "no PowerShell host available"

    with hold_installer_lifecycle_lock(path=lock_path):
        blocked = [subprocess.run([host, "-NoProfile", "-File", harness], check=False).returncode for host in hosts]
    acquired = [subprocess.run([host, "-NoProfile", "-File", harness], check=False).returncode for host in hosts]

    assert blocked == [1] * len(hosts)
    assert acquired == [0] * len(hosts)


def test_installed_ui_runtime_uses_uac_broker_not_direct_service_mutation(monkeypatch, tmp_path: Path) -> None:
    class QueryOnlyGateway:
        def query(self, name: str) -> ServiceSnapshot:
            return ServiceSnapshot(name=name, state="stopped")

        def start(self, _name: str) -> None:
            raise AssertionError("unelevated UI must not mutate SCM directly")

        def stop(self, _name: str) -> None:
            raise AssertionError("unelevated UI must not mutate SCM directly")

    actions: list[str] = []

    class Runner:
        def __init__(self, _release_config) -> None:
            pass

        def run(self, action: str) -> None:
            actions.append(action)

    monkeypatch.setattr(runtime_factory, "WindowsServiceGateway", QueryOnlyGateway)
    monkeypatch.setattr(runtime_factory, "ElevatedServiceActionRunner", Runner)
    layout = InstalledLayout(
        tmp_path / "program",
        tmp_path / "data",
        8000,
        5432,
        "TicketboxBackend",
        "TicketboxPg",
        "9.8.7-test",
    )
    release = _release()
    config = ManagerConfig(
        runtime=InstalledRuntimeConfig(layout, release),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=layout.backend_version,
        expected_installation_id=layout.installation_id,
        health_request_timeout_seconds=release.backend_health_request_timeout_seconds,
    )

    runtime = build_runtime(config)
    runtime.stop()

    assert isinstance(runtime, BrokeredWindowsServiceRuntime)
    assert runtime._status_runtime._wait_timeout_seconds == 17  # noqa: SLF001 - wiring contract
    assert runtime._status_runtime._pg_wait_timeout_seconds == 23  # noqa: SLF001 - wiring contract
    assert runtime._status_runtime._poll_seconds == 0.125  # noqa: SLF001 - wiring contract
    assert runtime._status_runtime._backend_ready_timeout_seconds == 31  # noqa: SLF001 - wiring contract
    assert runtime._status_runtime._backend_ready_poll_seconds == 0.375  # noqa: SLF001 - wiring contract
    assert actions == ["stop"]
