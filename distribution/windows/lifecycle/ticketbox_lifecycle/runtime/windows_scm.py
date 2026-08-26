from __future__ import annotations

import os
import time
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    SERVICE_DEMAND_START,
    expected_backend_service,
    expected_pg_service,
    require_service_configuration,
    require_service_identity,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.windows_scm_observation import (
    ScmObserver,
    ServiceConfiguration,
)
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_services import (
    require_running_service,
    require_service,
    scm_query_state,
    service_exists,
    service_running,
    start_service,
    stop_service,
)
from ticketbox_lifecycle.schemas import InstallRequest


class WindowsScmAdapter:
    name = "scm"

    def __init__(
        self,
        runner: CommandRunner,
        security: WindowsSecurityAdapter,
        observer: ScmObserver,
    ) -> None:
        self._runner = runner
        self._security = security
        self._observer = observer

    def apply(self, request: InstallRequest, step: str) -> str:
        if step == "scm":
            return self._register(request)
        if step == "start_services":
            return self._start_backend(request)
        raise LifecycleViolation("wrong_adapter", f"scm adapter does not own {step}")

    def verify(self, request: InstallRequest, step: str) -> None:
        if step == "scm":
            require_service(self._runner, request.pg_service_name)
            require_service(self._runner, request.backend_service_name)
            self._verify_service_configurations(
                request,
                backend_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
            )
            self._security.verify_pgdata_service_acl(
                request,
                verify_tree=not service_running(self._runner, request.pg_service_name),
            )
            self._security.verify_backend_runtime_authority(request)
            return
        if step == "start_services":
            require_running_service(self._runner, request.backend_service_name)
            return
        raise LifecycleViolation("wrong_adapter", f"scm adapter does not own {step}")

    def enable_autostart(self, request: InstallRequest) -> None:
        self._verify_service_configurations(
            request,
            backend_start_types=frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START}),
        )
        current = self._observer.observe(request.backend_service_name)
        if current.start_type != SERVICE_AUTO_START:
            self._set_start_type(request.backend_service_name, "auto")
        self._verify_service_configurations(
            request,
            backend_start_types=frozenset({SERVICE_AUTO_START}),
        )

    def fence_backend(self, request: InstallRequest) -> None:
        if not service_exists(self._runner, request.backend_service_name):
            return
        self._verify_backend_fence_target(request)
        if self._observer.observe(request.backend_service_name).start_type != SERVICE_DEMAND_START:
            self._set_start_type(request.backend_service_name, "demand")
        if scm_query_state(self._runner, request.backend_service_name) != "STOPPED":
            stop_service(
                self._runner,
                request.backend_service_name,
                code="backend_fence_stop_failed",
            )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if scm_query_state(self._runner, request.backend_service_name) == "STOPPED":
                self._verify_backend_fence_target(request, demand_only=True)
                return
            time.sleep(1)
        raise LifecycleError("backend_fence_timeout", "TicketboxBackend did not reach STOPPED")

    def _register(self, request: InstallRequest) -> str:
        pg_ctl = layout.tool(request, "pg_ctl.exe")
        if not pg_ctl.is_file():
            raise LifecycleError("missing_platform_binary", "postgresql/bin/pg_ctl.exe is not installed")
        shawl = layout.shawl_exe(request)
        backend = layout.backend_exe(request)
        if not shawl.is_file() or not backend.is_file():
            raise LifecycleError("missing_platform_binary", "shawl.exe or immutable backend is missing")
        if service_running(self._runner, request.pg_service_name) or service_running(
            self._runner,
            request.backend_service_name,
        ):
            raise LifecycleError(
                "live_scm_mutation_forbidden",
                "fresh-install reconcile refuses to mutate a running service",
            )
        self._refuse_foreign_service(
            request.pg_service_name,
            expected_pg_service(request),
        )
        self._refuse_foreign_service(
            request.backend_service_name,
            expected_backend_service(request, start_type=SERVICE_DEMAND_START),
        )
        if not service_exists(self._runner, request.pg_service_name):
            require_ok(
                self._runner.run(
                    [
                        str(pg_ctl),
                        "register",
                        "-N",
                        request.pg_service_name,
                        "-U",
                        "NT AUTHORITY\\LocalService",
                        "-D",
                        str(layout.pgdata(request)),
                        "-S",
                        "demand",
                    ]
                ),
                code="pg_register_failed",
            )
        self._set_identity(request.pg_service_name, start="demand")
        if not service_exists(self._runner, request.backend_service_name):
            require_ok(
                self._runner.run(
                    [
                        str(shawl),
                        "add",
                        "--name",
                        request.backend_service_name,
                        "--cwd",
                        _win32_service_path(backend.parent),
                        "--log-dir",
                        _win32_service_path(layout.backend_logs(request)),
                        "--env",
                        f"TICKETBOX_DATA_DIR={Path(request.data_root) / 'app'}",
                        "--env",
                        f"TICKETBOX_INSTALLATION_ID={request.install_id}",
                        "--env",
                        f"TICKETBOX_DATASET_ID={request.dataset_id}",
                        "--env",
                        f"TICKETBOX_RELEASE_ID={request.target_release_id}",
                        "--env",
                        "TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host",
                        "--env",
                        f"TICKETBOX_PORT={request.backend_port}",
                        "--",
                        _win32_service_path(backend),
                    ]
                ),
                code="backend_register_failed",
            )
        self._set_identity(request.backend_service_name, start="demand")
        self._security.configure_backend_runtime_acl(request)
        require_ok(
            self._runner.run(
                [
                    "sc.exe",
                    "config",
                    request.backend_service_name,
                    "depend=",
                    request.pg_service_name,
                ]
            ),
            code="backend_depend_failed",
        )
        self._security.seal_pgdata_acl(request)
        self._set_start_type(request.pg_service_name, "auto")
        return "registered"

    def _start_backend(self, request: InstallRequest) -> str:
        start_service(self._runner, request.backend_service_name, code="backend_start_failed")
        deadline = time.time() + 60
        while time.time() < deadline:
            if service_running(self._runner, request.backend_service_name):
                return "started"
            time.sleep(1)
        raise LifecycleError("backend_not_running", "TicketboxBackend did not reach RUNNING")

    def _refuse_foreign_service(
        self,
        name: str,
        expected: ServiceConfiguration,
    ) -> None:
        if not service_exists(self._runner, name):
            return
        require_service_identity(name, self._observer.observe(name), expected)

    def _set_identity(self, name: str, *, start: str) -> None:
        require_ok(
            self._runner.run(
                ["sc.exe", "config", name, "obj=", "NT AUTHORITY\\LocalService", "password=", ""]
            ),
            code="service_logon_failed",
        )
        require_ok(
            self._runner.run(["sc.exe", "sidtype", name, "unrestricted"]),
            code="service_sid_failed",
        )
        self._set_start_type(name, start)
        require_ok(
            self._runner.run(
                [
                    "sc.exe",
                    "failure",
                    name,
                    "reset=",
                    "3600",
                    "actions=",
                    "restart/5000/restart/10000/restart/60000",
                ]
            ),
            code="service_recovery_failed",
        )

    def _set_start_type(self, name: str, start: str) -> None:
        require_ok(
            self._runner.run(["sc.exe", "config", name, "start=", start]),
            code="service_start_type_failed",
        )

    def _verify_service_configurations(
        self,
        request: InstallRequest,
        *,
        backend_start_types: frozenset[int],
    ) -> None:
        require_service_configuration(
            request.pg_service_name,
            self._observer.observe(request.pg_service_name),
            expected_pg_service(request),
            allowed_start_types=frozenset({SERVICE_AUTO_START}),
        )
        require_service_configuration(
            request.backend_service_name,
            self._observer.observe(request.backend_service_name),
            expected_backend_service(request, start_type=SERVICE_DEMAND_START),
            allowed_start_types=backend_start_types,
        )

    def _verify_backend_fence_target(
        self,
        request: InstallRequest,
        *,
        demand_only: bool = False,
    ) -> None:
        allowed = (
            frozenset({SERVICE_DEMAND_START})
            if demand_only
            else frozenset({SERVICE_DEMAND_START, SERVICE_AUTO_START})
        )
        require_service_configuration(
            request.backend_service_name,
            self._observer.observe(request.backend_service_name),
            expected_backend_service(request, start_type=SERVICE_DEMAND_START),
            allowed_start_types=allowed,
        )


def _win32_service_path(path: Path) -> str:
    text = os.path.abspath(os.fspath(path))
    prefix = "\\\\?\\"
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text
