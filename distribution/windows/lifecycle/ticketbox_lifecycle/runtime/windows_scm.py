from __future__ import annotations

import os
import time
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.runtime.windows_services import (
    require_running_service,
    require_service,
    service_exists,
    service_running,
    start_service,
)
from ticketbox_lifecycle.schemas import InstallRequest


class WindowsScmAdapter:
    name = "scm"

    def __init__(self, runner: CommandRunner, security: WindowsSecurityAdapter) -> None:
        self._runner = runner
        self._security = security

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
            self._security.verify_pgdata_service_acl(request)
            self._security.verify_backend_runtime_authority(request)
            return
        if step == "start_services":
            require_running_service(self._runner, request.backend_service_name)
            return
        raise LifecycleViolation("wrong_adapter", f"scm adapter does not own {step}")

    def _register(self, request: InstallRequest) -> str:
        pg_ctl = layout.tool(request, "pg_ctl.exe")
        if not pg_ctl.is_file():
            raise LifecycleError("missing_platform_binary", "postgresql/bin/pg_ctl.exe is not installed")
        self._refuse_foreign_service(
            request.pg_service_name,
            _path_fragment(pg_ctl),
            _path_fragment(layout.pgdata(request)),
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
                        "auto",
                    ]
                ),
                code="pg_register_failed",
            )
        self._set_identity(request.pg_service_name)
        shawl = layout.shawl_exe(request)
        backend = layout.backend_exe(request)
        if not shawl.is_file() or not backend.is_file():
            raise LifecycleError("missing_platform_binary", "shawl.exe or immutable backend is missing")
        self._refuse_foreign_service(
            request.backend_service_name,
            _path_fragment(backend),
            request.target_release_id.lower(),
        )
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
        self._set_identity(request.backend_service_name)
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
        require_windows()
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    request.data_root,
                    "/T",
                    "/grant",
                    f"NT SERVICE\\{request.backend_service_name}:(OI)(CI)M",
                ]
            ),
            code="data_root_backend_acl_failed",
        )
        self._security.seal_pgdata_acl(request)
        self._security.grant_backend_runtime_authority_read(request)
        self._security.protect_runtime_env(request)
        return "registered"

    def _start_backend(self, request: InstallRequest) -> str:
        start_service(self._runner, request.backend_service_name, code="backend_start_failed")
        deadline = time.time() + 60
        while time.time() < deadline:
            if service_running(self._runner, request.backend_service_name):
                return "started"
            time.sleep(1)
        raise LifecycleError("backend_not_running", "TicketboxBackend did not reach RUNNING")

    def _refuse_foreign_service(self, name: str, *expected_fragments: str) -> None:
        if not service_exists(self._runner, name):
            return
        completed = self._runner.run(["sc.exe", "qc", name])
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        missing = [
            fragment
            for fragment in expected_fragments
            if fragment and fragment.lower() not in text
        ]
        if completed.returncode != 0 or missing:
            raise LifecycleViolation(
                "scm_collision",
                f"service {name} exists with a foreign ImagePath",
            )

    def _set_identity(self, name: str) -> None:
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
        require_ok(
            self._runner.run(["sc.exe", "config", name, "start=", "auto"]),
            code="service_start_type_failed",
        )
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


def _win32_service_path(path: Path) -> str:
    text = os.path.abspath(os.fspath(path))
    prefix = "\\\\?\\"
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def _path_fragment(path: Path) -> str:
    return _win32_service_path(path).replace("/", "\\").lower()
