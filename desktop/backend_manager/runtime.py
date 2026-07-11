"""Common runtime contract for source processes and installed Windows services."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Protocol

from backend_manager.supervisor import BackendSupervisor, SupervisorControlError


class RuntimeControlError(RuntimeError):
    """A service/process control failure safe to show in the local manager UI."""


class ServiceMissingError(RuntimeControlError):
    """An installer-owned Windows service is absent."""


class ServiceTransitionError(RuntimeControlError):
    """A Windows service did not converge to the requested state."""


class ServiceAccessError(RuntimeControlError):
    """Windows rejected an SCM query or mutation."""


@dataclass(frozen=True)
class RuntimeStatus:
    mode: str
    running: bool
    healthy: bool
    pid: int | None
    uptime_seconds: int
    auto_restart: bool
    auto_restart_configurable: bool
    restarts: int
    backend_service_state: str | None
    database_service_state: str | None
    log: list[str]
    control_error: str | None = None
    health_state: str = "pending"
    health_detail: str | None = None


class BackendRuntime(Protocol):
    """Lifecycle and status operations consumed by ``AppController``."""

    def status(self) -> RuntimeStatus: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def restart(self) -> None: ...
    def toggle_auto_restart(self) -> bool: ...
    def run_monitor(self, stop_event: threading.Event) -> None: ...
    def shutdown(self) -> None: ...


class SourceBackendRuntime:
    """Adapter preserving the existing source-tree supervisor behavior."""

    def __init__(self, supervisor: BackendSupervisor) -> None:
        self._supervisor = supervisor

    def status(self) -> RuntimeStatus:
        snapshot = self._supervisor.status()
        return RuntimeStatus(
            mode="source",
            running=snapshot.running,
            healthy=snapshot.healthy,
            pid=snapshot.pid,
            uptime_seconds=snapshot.uptime_seconds,
            auto_restart=snapshot.auto_restart,
            auto_restart_configurable=True,
            restarts=snapshot.restarts,
            backend_service_state=None,
            database_service_state=None,
            log=snapshot.log,
            control_error=snapshot.control_error,
            health_state="healthy" if snapshot.healthy else ("pending" if snapshot.running else "stopped"),
            health_detail=None,
        )

    def start(self) -> None:
        self._control(self._supervisor.start)

    def stop(self) -> None:
        self._control(self._supervisor.stop)

    def restart(self) -> None:
        self._control(self._supervisor.restart)

    def toggle_auto_restart(self) -> bool:
        return self._supervisor.toggle_auto_restart()

    def run_monitor(self, stop_event: threading.Event) -> None:
        self._supervisor.run_monitor(stop_event)

    def shutdown(self) -> None:
        self._control(self._supervisor.shutdown_owned)

    @staticmethod
    def _control(action) -> None:
        try:
            action()
        except (OSError, subprocess.SubprocessError, SupervisorControlError) as exc:
            raise RuntimeControlError(str(exc)) from exc
