"""Stable UI status contract and user-visible control failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager.__main__ import AppController
from backend_manager.config import ManagerConfig, SourceRuntimeConfig
from backend_manager.runtime import RuntimeControlError, RuntimeStatus, SourceBackendRuntime


class FakeRuntime:
    def __init__(self) -> None:
        self.fail_start = False

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=True,
            pid=123,
            uptime_seconds=45,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=2,
            backend_service_state=None,
            database_service_state=None,
            log=["ready"],
        )

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeControlError("需要管理员权限")

    def stop(self) -> None:
        pass

    def restart(self) -> None:
        pass

    def toggle_auto_restart(self) -> bool:
        return True

    def run_monitor(self, _stop_event) -> None:
        pass


def _config() -> ManagerConfig:
    return ManagerConfig(
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe")),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
    )


def test_status_exposes_runtime_capabilities(monkeypatch) -> None:
    monkeypatch.setattr("backend_manager.__main__.lan_ip", lambda: "192.168.1.8")
    controller = AppController(FakeRuntime(), _config())

    status = controller.status()

    assert status["runtime_mode"] == "source"
    assert status["auto_restart_configurable"] is True
    assert status["lan"] == "192.168.1.8:8000"
    assert status["control_error"] is None


def test_control_failure_is_returned_then_cleared_after_success() -> None:
    runtime = FakeRuntime()
    controller = AppController(runtime, _config())
    runtime.fail_start = True

    controller.start()
    assert controller.status()["control_error"] == "需要管理员权限"

    runtime.fail_start = False
    controller.start()
    assert controller.status()["control_error"] is None


def test_source_runtime_normalizes_os_start_failure() -> None:
    class BrokenSupervisor:
        def start(self) -> None:
            raise OSError("access denied")

    runtime = SourceBackendRuntime(BrokenSupervisor())  # type: ignore[arg-type]

    with pytest.raises(RuntimeControlError, match="access denied"):
        runtime.start()
