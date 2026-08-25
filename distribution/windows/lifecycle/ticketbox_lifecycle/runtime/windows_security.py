from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.schemas import InstallRequest

_CLUSTER_SECRET_NAMES = frozenset(
    {
        "postgres.password",
        "postgres.pwfile",
        "pgpass",
        "ticketbox_migrator.password",
        "ticketbox_runtime.password",
    }
)


class WindowsSecurityAdapter:
    name = "security"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def prepare_operation_store(self, request: InstallRequest) -> None:
        native.require_windows()
        require_closed_data_root(request)
        root = Path(request.program_data_root)
        native.reject_reparse_components(root)
        root.mkdir(parents=True, exist_ok=True)
        native.protect_directory(self._runner, root, code="operation_store_acl_failed")
        for path in (layout.machine_root(request), layout.active_operation(request).parent):
            native.reject_reparse_components(path)
            path.mkdir(parents=True, exist_ok=True)
            native.protect_directory(self._runner, path, code="operation_store_acl_failed")

    def require_fresh_inputs(self, request: InstallRequest) -> None:
        machine = layout.machine_root(request)
        operations = layout.active_operation(request).parent
        data_root = Path(request.data_root)
        native.reject_reparse_components(machine)
        native.reject_reparse_components(operations)
        native.reject_reparse_components(data_root)
        unexpected_machine = [path for path in machine.iterdir() if path != operations]
        unexpected_operations = list(operations.iterdir())
        unexpected_data = list(data_root.iterdir()) if data_root.is_dir() else []
        if unexpected_machine or unexpected_operations or unexpected_data or data_root.is_file():
            raise LifecycleViolation(
                "preexisting_mutable_state",
                "fresh install refuses unbound mutable state",
            )

    def protect_machine_json(self, path: Path, reader_service: str) -> None:
        native.require_windows()
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation("machine_state_invalid", "machine JSON is not a regular file")
        native.protect_file(
            self._runner,
            path,
            extra_grants=(f"*{native.service_sid(self._runner, reader_service)}:(R)",),
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
        self._verify_existing_credentials(request, allow_missing=True)
        self._ensure_credentials(request)
        for secret in sorted(path for path in secrets_root.iterdir() if path.is_file()):
            native.protect_file(self._runner, secret, extra_grants=(), code="secret_acl_failed")
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
        self._verify_existing_credentials(request, allow_missing=False)

    def grant_backend_binding_read(self, binding_path: Path, service_name: str) -> None:
        native.require_windows()
        machine = binding_path.parent
        for path, grant, code in (
            (machine, f"NT SERVICE\\{service_name}:(RX)", "binding_dir_acl_failed"),
            (binding_path, f"NT SERVICE\\{service_name}:(R)", "binding_acl_failed"),
        ):
            require_ok(
                self._runner.run(["icacls", str(path), "/grant", grant]),
                code=code,
            )
        interactive_sid = native.shell_user_sid()
        if not interactive_sid:
            raise LifecycleError(
                "binding_reader_unavailable",
                "cannot identify the interactive Windows user for installation.json",
            )
        for path, grant, code in (
            (machine, f"*{interactive_sid}:(RX)", "binding_dir_acl_failed"),
            (binding_path, f"*{interactive_sid}:(R)", "binding_acl_failed"),
        ):
            require_ok(
                self._runner.run(["icacls", str(path), "/grant", grant]),
                code=code,
            )

    def protect_runtime_env(self, request: InstallRequest) -> None:
        native.protect_file(
            self._runner,
            Path(request.data_root) / "app" / ".env",
            extra_grants=(f"*{native.service_sid(self._runner, request.backend_service_name)}:(R)",),
            code="runtime_env_acl_failed",
        )

    def grant_backend_runtime_authority_read(self, request: InstallRequest) -> None:
        active = layout.active_operation(request)
        for path, access in (
            (layout.machine_root(request), "(RX)"),
            (active.parent, "(OI)(CI)RX"),
        ):
            require_ok(
                self._runner.run(
                    ["icacls", str(path), "/grant", f"NT SERVICE\\{request.backend_service_name}:{access}"]
                ),
                code="runtime_authority_dir_acl_failed",
            )
        require_ok(
            self._runner.run(
                ["icacls", str(active), "/grant", f"NT SERVICE\\{request.backend_service_name}:(R)"]
            ),
            code="runtime_authority_acl_failed",
        )

    def verify_backend_runtime_authority(self, request: InstallRequest) -> None:
        active = layout.active_operation(request)
        completed = self._runner.run(["icacls", str(active)])
        text = f"{completed.stdout}\n{completed.stderr}".upper()
        if completed.returncode != 0:
            raise LifecycleError("runtime_authority_acl_verify_failed", "icacls could not read active.json")
        if f"NT SERVICE\\{request.backend_service_name}".upper() not in text:
            raise LifecycleError(
                "runtime_authority_acl_missing_backend",
                "active.json is not readable by TicketboxBackend",
            )
        for name in _CLUSTER_SECRET_NAMES:
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
        postgres_secret = self._read_or_create_secret(layout.postgres_password_file(request))
        message = (
            "ticketbox/fresh-owner/v1\0"
            + request.operation_id
            + "\0"
            + request.install_id
        ).encode("utf-8")
        return hmac.new(postgres_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def _verify_existing_credentials(self, request: InstallRequest, *, allow_missing: bool) -> None:
        secrets_root = layout.secrets_dir(request)
        existing_names = {path.name for path in secrets_root.iterdir()} if secrets_root.is_dir() else set()
        if existing_names - _CLUSTER_SECRET_NAMES:
            raise LifecycleViolation("credential_invalid", "secrets directory contains an unknown object")
        if not allow_missing and existing_names != _CLUSTER_SECRET_NAMES:
            raise LifecycleError("postcondition_missing", "lifecycle secrets are incomplete")
        for name in existing_names:
            path = secrets_root / name
            native.reject_reparse_components(path)
            if not path.is_file():
                raise LifecycleViolation("credential_invalid", f"credential is not a regular file: {name}")
            native.require_trusted_owner(
                path,
                code="credential_owner_untrusted",
                message="credential must have a trusted owner",
            )
            native.require_protected_file_acl(
                self._runner,
                path,
                code="credential_acl_untrusted",
                forbidden_markers=("NT SERVICE\\", "S-1-5-80-"),
            )
        runtime_env = Path(request.data_root) / "app" / ".env"
        if not runtime_env.exists() and not runtime_env.is_symlink():
            if allow_missing:
                return
            raise LifecycleError("postcondition_missing", "runtime .env is absent")
        native.reject_reparse_components(runtime_env)
        if not runtime_env.is_file():
            raise LifecycleViolation("credential_invalid", "runtime .env is not a regular file")
        native.require_trusted_owner(
            runtime_env,
            code="credential_owner_untrusted",
            message="runtime .env must have a trusted owner",
        )
        native.require_protected_file_acl(
            self._runner,
            runtime_env,
            code="credential_acl_untrusted",
            required_reader_markers=(
                native.service_sid(self._runner, request.backend_service_name),
                f"NT SERVICE\\{request.backend_service_name}",
            ),
        )

    def _ensure_credentials(self, request: InstallRequest) -> None:
        secrets_root = layout.secrets_dir(request)
        secrets_root.mkdir(parents=True, exist_ok=True)
        postgres_password = self._read_or_create_secret(layout.postgres_password_file(request))
        migrator_password = self._read_or_create_secret(layout.migrator_password_file(request))
        runtime_password = self._read_or_create_secret(layout.runtime_password_file(request))
        durable_write_text(layout.postgres_pwfile(request), postgres_password + "\n")
        pass_lines = [
            f"127.0.0.1:{request.pg_port}:*:postgres:{postgres_password}",
            f"127.0.0.1:{request.pg_port}:{DATABASE_NAME}:{MIGRATOR_ROLE}:{migrator_password}",
            f"127.0.0.1:{request.pg_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{runtime_password}",
            f"localhost:{request.pg_port}:*:postgres:{postgres_password}",
            f"localhost:{request.pg_port}:{DATABASE_NAME}:{MIGRATOR_ROLE}:{migrator_password}",
            f"localhost:{request.pg_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{runtime_password}",
        ]
        durable_write_text(layout.pg_passfile(request), "\n".join(pass_lines) + "\n")
        app_dir = Path(request.data_root) / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        env_text = f"DATABASE_URL={_app_database_url(request, runtime_password)}\n"
        env_path = app_dir / ".env"
        if env_path.is_file():
            try:
                current_env = env_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise LifecycleViolation("credential_invalid", "runtime .env is unreadable") from exc
            if current_env != env_text:
                raise LifecycleViolation("credential_invalid", "runtime .env does not match this operation")
        else:
            durable_write_text(env_path, env_text)

    @staticmethod
    def _read_or_create_secret(path: Path) -> str:
        if path.is_file():
            try:
                value = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                raise LifecycleViolation("credential_invalid", f"credential is unreadable: {path.name}") from exc
            if not 32 <= len(value) <= 200 or any(character.isspace() for character in value):
                raise LifecycleViolation("credential_invalid", f"credential is malformed: {path.name}")
            return value
        if path.exists() or path.is_symlink():
            raise LifecycleViolation("credential_invalid", f"credential is not a regular file: {path.name}")
        value = secrets.token_urlsafe(32)
        durable_write_text(path, value + "\n")
        return value


def require_closed_data_root(request: InstallRequest) -> None:
    root = os.path.normcase(os.path.abspath(request.program_data_root))
    expected = os.path.normcase(os.path.abspath(os.path.join(root, "data")))
    actual = os.path.normcase(os.path.abspath(request.data_root))
    if actual != expected:
        raise LifecycleViolation(
            "data_root_outside_programdata",
            "fresh install data_root must be the protected ProgramData/Ticketbox/data path",
        )


def _app_database_url(request: InstallRequest, runtime_password: str) -> str:
    return (
        f"postgresql+psycopg://{RUNTIME_ROLE}:{runtime_password}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )
