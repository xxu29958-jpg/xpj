"""Runtime/config projections used by the long-lived Manager GUI."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.runtime import BackendRuntime, RuntimeControlError


@dataclass(frozen=True)
class RuntimeProjection:
    config: ManagerConfig
    runtime: BackendRuntime


class RuntimeConfigProvider(Protocol):
    mode_hint: Literal["source", "installed"]

    def current(self) -> RuntimeProjection: ...
    def run_monitor(self, stop_event: threading.Event) -> None: ...
    def shutdown(self) -> None: ...


class StaticRuntimeConfigProvider:
    """Keep the one source supervisor whose child ownership is process-local."""

    def __init__(self, runtime: BackendRuntime, config: ManagerConfig) -> None:
        self.mode_hint: Literal["source", "installed"] = config.runtime_mode
        self._projection = RuntimeProjection(config=config, runtime=runtime)

    def current(self) -> RuntimeProjection:
        return self._projection

    def run_monitor(self, stop_event: threading.Event) -> None:
        self._projection.runtime.run_monitor(stop_event)

    def shutdown(self) -> None:
        self._projection.runtime.shutdown()


class RefreshingInstalledRuntimeConfigProvider:
    """Rebuild the installed projection so an open GUI follows upgrades safely."""

    mode_hint: Literal["installed"] = "installed"

    def __init__(
        self,
        *,
        config_loader: Callable[[], ManagerConfig],
        runtime_builder: Callable[[ManagerConfig], BackendRuntime],
        monitor_seconds: float = 3.0,
    ) -> None:
        self._config_loader = config_loader
        self._runtime_builder = runtime_builder
        self._monitor_seconds = monitor_seconds

    def current(self) -> RuntimeProjection:
        config = self._config_loader()
        if config.runtime_mode != "installed":
            raise ConfigError("正式安装运行时刷新返回了非安装态配置。")
        return RuntimeProjection(config=config, runtime=self._runtime_builder(config))

    def run_monitor(self, stop_event: threading.Event) -> None:
        while not stop_event.wait(self._monitor_seconds):
            try:
                self.current().runtime.status()
            except (ConfigError, RuntimeControlError):
                continue

    def shutdown(self) -> None:
        return
