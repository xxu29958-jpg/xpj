from __future__ import annotations

import os
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime import windows_credentials as credentials
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.windows_file_security import FileSecurity
from ticketbox_lifecycle.schemas import InstallRequest


class WindowsSecurityAdapter:
    name = "security"

    def __init__(self, runner: CommandRunner, file_security: FileSecurity) -> None:
        self._runner = runner
        self._file_security = file_security

    def prepare_operation_store(self, request: InstallRequest) -> None:
        native.require_windows()
        require_closed_data_root(request)
        backend_reader_sid, interactive_reader_sid = self._operation_store_reader_sids(request)
        paths = (
            Path(request.program_data_root),
            layout.machine_root(request),
            layout.active_operation(request).parent,
        )
        for path in paths:
            native.reject_reparse_components(path)
            if os.path.lexists(path):
                native.require_protected_directory(
                    path,
                    backend_reader_sid=backend_reader_sid,
                    interactive_reader_sid=interactive_reader_sid,
                    code="operation_store_untrusted",
                )
            else:
                native.create_protected_directory(
                    path,
                    backend_reader_sid=backend_reader_sid,
                    interactive_reader_sid=interactive_reader_sid,
                    code="operation_store_create_failed",
                )
        pending = paths[-1] / layout.ACTIVE_OPERATION_TEMP_NAME
        if os.path.lexists(pending):
            _require_active_temp(pending, code="operation_store_orphan_untrusted")
            try:
                pending.unlink()
            except OSError as exc:
                raise LifecycleError(
                    "operation_store_orphan_cleanup_failed",
                    "cannot discard the incomplete active publication",
                ) from exc

    def require_fresh_inputs(self, request: InstallRequest) -> None:
        native.require_windows()
        require_closed_data_root(request)
        backend_reader_sid, interactive_reader_sid = self._operation_store_reader_sids(request)
        root = Path(request.program_data_root)
        machine = layout.machine_root(request)
        operations = layout.active_operation(request).parent
        data_root = Path(request.data_root)
        native.reject_reparse_components(data_root)
        if os.path.lexists(data_root):
            _raise_preexisting_mutable_state()
        expected_children = ((root, machine), (machine, operations))
        for parent, expected_child in expected_children:
            if not os.path.lexists(parent):
                return
            native.require_protected_directory(
                parent,
                backend_reader_sid=backend_reader_sid,
                interactive_reader_sid=interactive_reader_sid,
                code="operation_store_untrusted",
            )
            entries = list(parent.iterdir())
            if any(entry != expected_child for entry in entries):
                _raise_preexisting_mutable_state()
            if not os.path.lexists(expected_child):
                return
        native.require_protected_directory(
            operations,
            backend_reader_sid=backend_reader_sid,
            interactive_reader_sid=interactive_reader_sid,
            code="operation_store_untrusted",
        )
        entries = list(operations.iterdir())
        pending = operations / layout.ACTIVE_OPERATION_TEMP_NAME
        if not entries:
            return
        if entries != [pending]:
            _raise_preexisting_mutable_state()
        _require_active_temp(pending, code="preexisting_mutable_state")

    def protect_machine_json(self, path: Path, reader_service: str) -> None:
        native.require_windows()
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation("machine_state_invalid", "machine JSON is not a regular file")
        self._file_security.protect_file(
            self._runner,
            path,
            reader_sids=(native.service_sid(self._runner, reader_service),),
            code="machine_state_acl_failed",
        )

    def verify_machine_json(self, path: Path, reader_service: str) -> None:
        native.require_windows()
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation("machine_state_invalid", "machine JSON is not a regular file")
        native.require_trusted_owner(
            path,
            code="machine_state_untrusted",
            message="machine JSON must have a trusted owner",
        )
        native.require_protected_file_acl(
            self._runner,
            path,
            code="machine_state_untrusted",
            required_reader_markers=(
                native.service_sid(self._runner, reader_service),
                f"NT SERVICE\\{reader_service}",
            ),
        )

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "acl":
            raise LifecycleViolation("wrong_adapter", "security adapter only owns acl")
        self.prepare_operation_store(request)
        data_root = Path(request.data_root)
        secrets_root = layout.secrets_dir(request)
        for path in (data_root, secrets_root):
            native.reject_reparse_components(path)
            path.mkdir(parents=True, exist_ok=True)
            native.protect_directory(self._runner, path, code="acl_apply_failed")
        credentials.verify_existing_credentials(self._runner, request, allow_missing=True)
        credentials.ensure_credentials(request)
        for secret in sorted(path for path in secrets_root.iterdir() if path.is_file()):
            self._file_security.protect_file(
                self._runner,
                secret,
                reader_sids=(),
                code="secret_acl_failed",
            )
        self.protect_runtime_env(request)
        return "acl-applied"

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "acl":
            raise LifecycleViolation("wrong_adapter", "security adapter only owns acl")
        native.require_windows()
        completed = self._runner.run(["icacls", request.data_root])
        root_acl = f"{completed.stdout}\n{completed.stderr}".upper()
        if completed.returncode != 0:
            raise LifecycleError("acl_verify_failed", "icacls could not read DataRoot")
        if native.has_broad_reader(root_acl):
            raise LifecycleError("data_root_acl_too_broad", "DataRoot is readable by ordinary users")
        credentials.verify_existing_credentials(self._runner, request, allow_missing=False)

    def grant_backend_binding_read(self, binding_path: Path, service_name: str) -> None:
        native.require_windows()
        interactive_sid = native.shell_user_sid()
        if not interactive_sid:
            raise LifecycleError(
                "binding_reader_unavailable",
                "cannot identify the interactive Windows user for installation.json",
            )
        self._file_security.protect_file(
            self._runner,
            binding_path,
            reader_sids=(
                native.service_sid(self._runner, service_name),
                interactive_sid,
            ),
            code="binding_acl_failed",
        )

    def materialize_initdb_password_file(self, request: InstallRequest) -> Path:
        reader_sid = native.current_process_user_sid()
        if not reader_sid:
            raise LifecycleError(
                "initdb_reader_unavailable",
                "cannot identify the Windows user that will run initdb",
            )
        return credentials.materialize_initdb_password_file(
            self._runner,
            self._file_security,
            request,
            reader_sid=reader_sid,
        )

    def discard_initdb_password_file(self, request: InstallRequest) -> None:
        credentials.discard_initdb_password_file(request)

    def protect_runtime_env(self, request: InstallRequest) -> None:
        self._file_security.protect_file(
            self._runner,
            Path(request.data_root) / "app" / ".env",
            reader_sids=(native.service_sid(self._runner, request.backend_service_name),),
            code="runtime_env_acl_failed",
        )

    def configure_backend_runtime_acl(self, request: InstallRequest) -> None:
        native.require_windows()
        app_data = Path(request.data_root) / "app"
        log_dir = layout.backend_logs(request)
        for path in (app_data, log_dir):
            native.reject_reparse_components(path)
            if not path.is_dir():
                raise LifecycleError("backend_directory_missing", f"missing backend directory: {path}")
            native.protect_directory(self._runner, path, code="backend_directory_acl_failed")
        service_sid = native.service_sid(self._runner, request.backend_service_name)
        for path, access in (
            (Path(request.data_root), "(RX)"),
            (app_data, "(OI)(CI)M"),
            (log_dir, "(OI)(CI)M"),
        ):
            require_ok(
                self._runner.run(
                    ["icacls", str(path), "/grant:r", f"*{service_sid}:{access}"]
                ),
                code="backend_directory_acl_failed",
            )

    def verify_backend_runtime_authority(self, request: InstallRequest) -> None:
        service_sid = native.service_sid(self._runner, request.backend_service_name)
        for path, writable in (
            (Path(request.data_root), False),
            (Path(request.data_root) / "app", True),
            (layout.backend_logs(request), True),
        ):
            completed = self._runner.run(["icacls", str(path)])
            text = f"{completed.stdout}\n{completed.stderr}".upper()
            service_lines = [line for line in text.splitlines() if service_sid in line]
            if completed.returncode != 0 or not service_lines or native.has_broad_reader(text):
                raise LifecycleError(
                    "backend_directory_acl_verify_failed",
                    f"backend directory ACL is incomplete: {path}",
                )
            grants_modify = any("(M)" in line or ")M" in line for line in service_lines)
            grants_too_much = any("(F)" in line or ")F" in line for line in service_lines)
            if grants_too_much or grants_modify != writable:
                raise LifecycleError(
                    "backend_directory_acl_verify_failed",
                    f"backend directory ACL has wrong rights: {path}",
                )
        active = layout.active_operation(request)
        completed = self._runner.run(["icacls", str(active)])
        text = f"{completed.stdout}\n{completed.stderr}".upper()
        if completed.returncode != 0:
            raise LifecycleError("runtime_authority_acl_verify_failed", "icacls could not read active.json")
        if not any(
            marker in text
            for marker in (
                service_sid.upper(),
                f"NT SERVICE\\{request.backend_service_name}".upper(),
            )
        ):
            raise LifecycleError(
                "runtime_authority_acl_missing_backend",
                "active.json is not readable by TicketboxBackend",
            )
        for name in credentials.KNOWN_SECRET_NAMES:
            secret = layout.secrets_dir(request) / name
            if not secret.is_file():
                continue
            observed = self._runner.run(["icacls", str(secret)])
            observed_text = f"{observed.stdout}\n{observed.stderr}".upper()
            if f"NT SERVICE\\{request.backend_service_name}".upper() in observed_text:
                raise LifecycleError("secret_acl_leaked_backend", f"{name} grants TicketboxBackend")
        runtime_env = Path(request.data_root) / "app" / ".env"
        native.require_trusted_owner(
            runtime_env,
            code="runtime_env_owner_untrusted",
            message="runtime .env must have a trusted owner",
        )
        native.require_protected_file_acl(
            self._runner,
            runtime_env,
            code="runtime_env_acl_verify_failed",
            required_reader_markers=(
                native.service_sid(self._runner, request.backend_service_name),
                f"NT SERVICE\\{request.backend_service_name}",
            ),
        )

    def seal_pgdata_acl(self, request: InstallRequest) -> None:
        pgdata = str(layout.pgdata(request))
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    pgdata,
                    "/T",
                    "/C",
                    "/remove:g",
                    f"NT SERVICE\\{request.backend_service_name}",
                ]
            ),
            code="pgdata_acl_remove_backend_failed",
        )
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    pgdata,
                    "/inheritance:r",
                    "/grant:r",
                    "SYSTEM:(OI)(CI)F",
                    "Administrators:(OI)(CI)F",
                    f"NT SERVICE\\{request.pg_service_name}:(OI)(CI)F",
                ]
            ),
            code="pgdata_acl_failed",
        )

    def verify_pgdata_service_acl(self, request: InstallRequest) -> None:
        completed = self._runner.run(["icacls", str(layout.pgdata(request))])
        text = f"{completed.stdout}\n{completed.stderr}".upper()
        if completed.returncode != 0:
            raise LifecycleError("pgdata_acl_verify_failed", "icacls could not read pgdata")
        backend = f"NT SERVICE\\{request.backend_service_name}".upper()
        pg_service = f"NT SERVICE\\{request.pg_service_name}".upper()
        if backend in text:
            raise LifecycleError("pgdata_acl_leaked_backend", "pgdata grants TicketboxBackend")
        if pg_service not in text:
            raise LifecycleError("pgdata_acl_missing_pg", "pgdata missing TicketboxPg")

    def owner_bootstrap_secret(self, request: InstallRequest) -> str:
        return credentials.owner_bootstrap_secret(request)

    def _operation_store_reader_sids(self, request: InstallRequest) -> tuple[str, str]:
        backend_reader_sid = native.service_sid(self._runner, request.backend_service_name)
        interactive_reader_sid = native.shell_user_sid()
        if not interactive_reader_sid:
            raise LifecycleError(
                "operation_store_reader_unavailable",
                "cannot identify the interactive Windows user for the operation store",
            )
        return backend_reader_sid, interactive_reader_sid


def _require_active_temp(path: Path, *, code: str) -> None:
    native.reject_reparse_components(path)
    if not path.is_file():
        raise LifecycleViolation(code, "active publication orphan must be a regular file")


def _raise_preexisting_mutable_state() -> None:
    raise LifecycleViolation(
        "preexisting_mutable_state",
        "fresh install refuses unbound mutable state",
    )


def require_closed_data_root(request: InstallRequest) -> None:
    root = os.path.normcase(os.path.abspath(request.program_data_root))
    expected = os.path.normcase(os.path.abspath(os.path.join(root, "data")))
    actual = os.path.normcase(os.path.abspath(request.data_root))
    if actual != expected:
        raise LifecycleViolation(
            "data_root_outside_programdata",
            "fresh install data_root must be the protected ProgramData/Ticketbox/data path",
        )
