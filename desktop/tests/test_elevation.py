"""UAC broker contracts: fixed actions, short-lived helper, no elevated HTTP UI."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend_manager import elevation
from backend_manager.__main__ import _build_runtime, main
from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig
from backend_manager.elevation import (
    HELPER_EXIT_CONFIG,
    HELPER_EXIT_MISSING_SERVICE,
    HELPER_EXIT_NOT_ELEVATED,
    HELPER_EXIT_TIMEOUT,
    ElevatedServiceActionRunner,
    HelperCommand,
    build_helper_command,
    start_helper_watchdog,
)
from backend_manager.installation import InstalledLayout
from backend_manager.runtime import RuntimeControlError, ServiceMissingError
from backend_manager.windows_service import BrokeredWindowsServiceRuntime, ServiceSnapshot


def test_source_helper_command_reenters_module_with_one_fixed_action(monkeypatch, tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    monkeypatch.setattr(elevation.sys, "executable", str(python))
    monkeypatch.delattr(elevation.sys, "frozen", raising=False)

    command = build_helper_command("restart")

    assert command.executable == python.resolve()
    assert command.arguments == ("-m", "backend_manager", "--elevated-service-action", "restart")
    assert command.working_dir.name == "desktop"


def test_frozen_helper_command_reuses_manager_executable(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "TicketboxManager.exe"
    monkeypatch.setattr(elevation.sys, "executable", str(executable))
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)

    command = build_helper_command("stop")

    assert command == HelperCommand(
        executable=executable.resolve(),
        arguments=("--elevated-service-action", "stop"),
        working_dir=tmp_path.resolve(),
    )


@pytest.mark.parametrize(
    ("exit_code", "message"),
    [
        (HELPER_EXIT_CONFIG, "安装信息不可用"),
        (HELPER_EXIT_MISSING_SERVICE, "未找到小票夹 Windows 服务"),
        (HELPER_EXIT_TIMEOUT, "可能仍在完成操作"),
        (99, "exit=99"),
    ],
)
def test_action_runner_maps_helper_exit_to_actionable_message(exit_code: int, message: str) -> None:
    runner = ElevatedServiceActionRunner(launcher=lambda _command: exit_code)

    with pytest.raises(RuntimeControlError, match=message):
        runner.run("start")


def test_helper_watchdog_forces_distinct_timeout_exit() -> None:
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
    layout = InstalledLayout(tmp_path / "program", tmp_path / "data", 8000, 5432)
    config = ManagerConfig(
        runtime=InstalledRuntimeConfig(layout),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
    )

    class BrokenRuntime:
        def stop(self) -> None:
            raise ServiceMissingError("missing")

    monkeypatch.setattr("backend_manager.__main__.is_process_elevated", lambda: True)
    monkeypatch.setattr("backend_manager.__main__.start_helper_watchdog", threading.Event)
    monkeypatch.setattr("backend_manager.__main__.load_config", lambda **_kwargs: config)
    monkeypatch.setattr("backend_manager.__main__._build_direct_service_runtime", lambda *_args: BrokenRuntime())

    assert main(["--elevated-service-action", "stop"]) == HELPER_EXIT_MISSING_SERVICE


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
        def run(self, action: str) -> None:
            actions.append(action)

    monkeypatch.setattr("backend_manager.__main__.WindowsServiceGateway", QueryOnlyGateway)
    monkeypatch.setattr("backend_manager.__main__.ElevatedServiceActionRunner", Runner)
    layout = InstalledLayout(tmp_path / "program", tmp_path / "data", 8000, 5432)
    config = ManagerConfig(
        runtime=InstalledRuntimeConfig(layout),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
    )

    runtime = _build_runtime(config)
    runtime.stop()

    assert isinstance(runtime, BrokeredWindowsServiceRuntime)
    assert actions == ["stop"]
