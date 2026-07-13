"""Construct source and installed Desktop Manager runtimes."""

from __future__ import annotations

from functools import partial

from backend_manager.config import ConfigError, InstalledRuntimeConfig, ManagerConfig, SourceRuntimeConfig, load_config
from backend_manager.elevation import ElevatedServiceActionRunner
from backend_manager.process import (
    TicketboxHealthExpectation,
    health_ok,
    probe_ticketbox_health,
    spawn_backend,
    tree_kill,
)
from backend_manager.projection import (
    RefreshingInstalledRuntimeConfigProvider,
    RuntimeConfigProvider,
    StaticRuntimeConfigProvider,
)
from backend_manager.runtime import BackendRuntime, SourceBackendRuntime
from backend_manager.supervisor import BackendSupervisor
from backend_manager.windows_service import BrokeredWindowsServiceRuntime, WindowsServiceGateway, WindowsServiceRuntime


def build_source_supervisor(config: ManagerConfig, runtime: SourceRuntimeConfig) -> BackendSupervisor:
    expectation = TicketboxHealthExpectation(
        backend_version=config.expected_backend_version,
        installation_id=config.expected_installation_id,
    )
    return BackendSupervisor(
        spawn=partial(
            spawn_backend,
            backend_root=runtime.backend_root,
            venv_python=runtime.venv_python,
            data_root=runtime.data_root,
            host=config.backend_host,
            port=config.backend_port,
        ),
        tree_kill=tree_kill,
        health=partial(
            health_ok,
            config.health_url,
            expectation=expectation,
            timeout=config.health_request_timeout_seconds,
        ),
    )


def build_direct_service_runtime(
    config: ManagerConfig,
    runtime: InstalledRuntimeConfig,
    *,
    backend_stopped_validator=None,
) -> WindowsServiceRuntime:
    expectation = TicketboxHealthExpectation(
        backend_version=config.expected_backend_version,
        installation_id=config.expected_installation_id,
    )
    release = runtime.release
    return WindowsServiceRuntime(
        gateway=WindowsServiceGateway(),
        backend_service_name=runtime.backend_service_name,
        pg_service_name=runtime.pg_service_name,
        health_probe=partial(
            probe_ticketbox_health,
            config.health_url,
            expectation=expectation,
            timeout=config.health_request_timeout_seconds,
        ),
        wait_timeout_seconds=release.service_state_timeout_seconds,
        pg_wait_timeout_seconds=max(
            release.service_state_timeout_seconds,
            release.postgres_ready_timeout_seconds,
        ),
        poll_seconds=release.service_poll_seconds,
        backend_ready_timeout_seconds=release.backend_ready_timeout_seconds,
        backend_ready_poll_seconds=release.backend_ready_poll_seconds,
        backend_stopped_validator=backend_stopped_validator,
    )


def build_runtime(config: ManagerConfig) -> BackendRuntime:
    runtime = config.runtime
    if isinstance(runtime, SourceRuntimeConfig):
        expectation = TicketboxHealthExpectation(
            backend_version=config.expected_backend_version,
            installation_id=config.expected_installation_id,
        )
        return SourceBackendRuntime(
            build_source_supervisor(config, runtime),
            health_probe=partial(
                probe_ticketbox_health,
                config.health_url,
                expectation=expectation,
                timeout=config.health_request_timeout_seconds,
            ),
        )
    if isinstance(runtime, InstalledRuntimeConfig):
        return BrokeredWindowsServiceRuntime(
            status_runtime=build_direct_service_runtime(config, runtime),
            action_runner=ElevatedServiceActionRunner(
                runtime.release,
                runtime.layout.manager_executable_path,
            ),
        )
    raise ConfigError(f"unsupported runtime: {type(runtime).__name__}")


def build_provider(config: ManagerConfig) -> RuntimeConfigProvider:
    if config.runtime_mode == "source":
        return StaticRuntimeConfigProvider(build_runtime(config), config)
    return RefreshingInstalledRuntimeConfigProvider(
        config_loader=partial(load_config, mode_override="installed"),
        runtime_builder=build_runtime,
    )
