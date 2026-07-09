"""Backend process supervision — owns exactly one uvicorn process and keeps it alive.

The OS-touching operations (spawn / tree-kill / health probe / clock)
are injected so the lifecycle logic is unit-testable without real subprocesses.

Two correctness rules this module exists to enforce:

* **No orphaned workers.** uvicorn spawns a child worker; on Windows, killing only
  the parent leaves the worker bound to the port. Termination therefore tree-kills
  (parent + descendants), so a "stop" actually frees the port.
* **Health-aware restart.** A crash (parent exits) restarts immediately; a hung or
  worker-dead process (parent alive but ``/api/health`` failing) restarts after a
  startup grace window and a few consecutive unhealthy probes, so first-boot
  migrations are not mistaken for a hang.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol


class ManagedProcess(Protocol):
    """A spawned backend process the supervisor owns."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None:
        """Return the exit code, or ``None`` while still running."""
        ...

    def recent_log(self) -> list[str]:
        """Most recent captured stdout/stderr lines (newest last)."""
        ...

    def wait(self, timeout: float) -> int:
        """Wait for process exit, raising ``TimeoutError`` if it stays alive."""
        ...


class SupervisorControlError(RuntimeError):
    """Raised when an ownership-safe lifecycle operation cannot be completed."""


# Injected callable signatures (real implementations live in ``process.py``).
SpawnFn = "callable[[], ManagedProcess]"
TreeKillFn = "callable[[int], bool]"
HealthFn = "callable[[], bool]"
ClockFn = "callable[[], float]"


@dataclass(frozen=True)
class SupervisorConfig:
    """Timing knobs for the supervision loop."""

    tick_seconds: float = 3.0
    health_grace_seconds: float = 25.0  # first boot runs migrations; don't mistake for a hang
    unhealthy_restarts_after: int = 2  # consecutive failing probes (post-grace) before restart


@dataclass(frozen=True)
class SupervisorStatus:
    """Read-only snapshot for the UI / control surface."""

    running: bool
    healthy: bool
    pid: int | None
    uptime_seconds: int
    auto_restart: bool
    restarts: int
    log: list[str]
    control_error: str | None


class BackendSupervisor:
    """Owns one backend process; tree-kills it cleanly and restarts it when it dies."""

    def __init__(
        self,
        *,
        spawn,
        tree_kill,
        health,
        config: SupervisorConfig | None = None,
        clock=time.monotonic,
    ) -> None:
        self._spawn = spawn
        self._tree_kill = tree_kill
        self._health = health
        self._clock = clock
        self._config = config or SupervisorConfig()

        self._lock = threading.RLock()
        self._proc: ManagedProcess | None = None
        self._managed = False  # user intent: True means "should be running" (drives auto-restart)
        self._spawned_at: float | None = None
        self._unhealthy_streak = 0
        self._adopted = False  # tracking an externally-started healthy backend (we don't own its pid)
        self._last_control_error: str | None = None

        self.auto_restart = True
        self.restarts = 0

    # ---- intent-driven controls ------------------------------------------
    def start(self) -> None:
        """Bring the backend up — or adopt one that is already healthy.

        We never kill a process we did not spawn. If a backend is already
        answering ``/api/health`` on the port (the boot scheduled-task, or a
        prior manager whose uvicorn worker outlived it), we ADOPT it: monitor
        its health but leave its process alone. We also never blind-clear the
        port — if some unrelated process holds it, uvicorn fails to bind and
        surfaces that in the log rather than us terminating an unknown process.
        """
        with self._lock:
            self._managed = True
            if self._alive():
                return
            if self._health():
                self._adopt()
                return
            self._adopted = False
            self._launch()

    def _adopt(self) -> None:
        """Track an externally-started, already-healthy backend (no owned pid)."""
        self._adopted = True
        self._proc = None
        self._spawned_at = None
        self._unhealthy_streak = 0
        self._last_control_error = None

    def stop(self) -> None:
        """Tree-kill the backend and stop supervising it (no auto-restart)."""
        with self._lock:
            if self._adopted:
                raise SupervisorControlError(
                    "当前后端由管理器外部启动，不能安全停止；请使用它原来的启动方式停止。",
                )
            self._managed = False
            self._terminate()
            self._last_control_error = None

    def restart(self) -> None:
        """Tree-kill and respawn a fresh backend."""
        with self._lock:
            self._managed = True
            if self._adopted:
                raise SupervisorControlError(
                    "当前后端由管理器外部启动，不能安全重启；请使用它原来的启动方式重启。",
                )
            self._terminate()
            self._launch()

    # ---- supervision tick (called by the monitor thread or tests) --------
    def tick(self) -> None:
        """One supervision step: restart the backend if it has died or gone unhealthy."""
        with self._lock:
            try:
                if not (self._managed and self.auto_restart):
                    return
                if self._adopted:
                    # An externally-started backend we adopted. Sustained health
                    # failure (past grace) means it's effectively gone — _check_health
                    # takes over with our own process via _restart_internal.
                    self._check_health()
                    return
                if not self._alive():
                    if self._health():
                        self._adopt()
                        return
                    self._restart_internal()
                    return
                self._check_health()
            except (OSError, SupervisorControlError) as exc:
                self._last_control_error = str(exc)
                raise

    def _check_health(self) -> None:
        if self._within_grace():
            return
        if self._health():
            self._unhealthy_streak = 0
            self._last_control_error = None
            return
        self._unhealthy_streak += 1
        if self._unhealthy_streak >= self._config.unhealthy_restarts_after:
            self._restart_internal()

    def _within_grace(self) -> bool:
        return (
            self._spawned_at is not None
            and self._clock() - self._spawned_at < self._config.health_grace_seconds
        )

    # ---- process primitives ----------------------------------------------
    def _launch(self) -> None:
        self._proc = self._spawn()
        self._spawned_at = self._clock()
        self._unhealthy_streak = 0
        self._last_control_error = None

    def _terminate(self) -> None:
        proc = self._proc
        if proc is not None:
            kill_requested = self._tree_kill(proc.pid)
            try:
                proc.wait(timeout=5.0)
            except TimeoutError as exc:
                detail = "taskkill 未成功" if not kill_requested else "进程未在 taskkill 后退出"
                raise SupervisorControlError(f"停止后端失败：{detail}（PID {proc.pid}）。") from exc
            if not kill_requested and self._health():
                self._adopt()
                raise SupervisorControlError(
                    "后端父进程已退出，但服务端口仍有健康实例；管理器没有误杀该外部进程。",
                )
        self._proc = None
        self._spawned_at = None
        self._adopted = False

    def _restart_internal(self) -> None:
        self._adopted = False
        self._terminate()
        self._launch()
        self.restarts += 1

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---- status -----------------------------------------------------------
    def status(self) -> SupervisorStatus:
        with self._lock:
            alive = self._alive()
            running = alive or self._adopted
            uptime = int(self._clock() - self._spawned_at) if (alive and self._spawned_at) else 0
            return SupervisorStatus(
                running=running,
                healthy=running and self._health(),
                pid=self._proc.pid if (alive and self._proc) else None,
                uptime_seconds=uptime,
                auto_restart=self.auto_restart,
                restarts=self.restarts,
                log=(self._proc.recent_log() if self._proc else []),
                control_error=self._last_control_error,
            )

    def toggle_auto_restart(self) -> bool:
        with self._lock:
            self.auto_restart = not self.auto_restart
            return self.auto_restart

    def run_monitor(self, stop_event: threading.Event) -> None:
        """Block in the supervision loop until ``stop_event`` is set (run in a daemon thread)."""
        while not stop_event.wait(self._config.tick_seconds):
            try:
                self.tick()
            except (OSError, SupervisorControlError):
                continue
