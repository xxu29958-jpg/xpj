from __future__ import annotations

import hashlib
import hmac
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
from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.runtime.windows_file_security import FileSecurity
from ticketbox_lifecycle.schemas import InstallRequest

DURABLE_SECRET_NAMES = frozenset(
    {
        "postgres.password",
        "pgpass",
        "ticketbox_migrator.password",
        "ticketbox_runtime.password",
    }
)
KNOWN_SECRET_NAMES = DURABLE_SECRET_NAMES | {"postgres.pwfile"}


def materialize_initdb_password_file(
    runner: CommandRunner,
    file_security: FileSecurity,
    request: InstallRequest,
) -> Path:
    path = layout.postgres_pwfile(request)
    discard_initdb_password_file(request)
    password = _read_secret(layout.postgres_password_file(request))
    durable_write_text(path, password + "\n")
    file_security.protect_file(runner, path, reader_sids=(), code="secret_acl_failed")
    native.require_trusted_owner(
        path,
        code="credential_owner_untrusted",
        message="initdb password input must have a trusted owner",
    )
    native.require_protected_file_acl(
        runner,
        path,
        code="credential_acl_untrusted",
        forbidden_markers=("NT SERVICE\\", "S-1-5-80-"),
    )
    return path


def discard_initdb_password_file(request: InstallRequest) -> None:
    path = layout.postgres_pwfile(request)
    native.reject_reparse_components(path)
    if path.exists() and not path.is_file():
        raise LifecycleViolation(
            "credential_invalid",
            "initdb password input is not a regular file",
        )
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise LifecycleError(
            "secret_cleanup_failed",
            "initdb password input could not be removed",
        ) from exc


def owner_bootstrap_secret(request: InstallRequest) -> str:
    postgres_secret = _read_secret(layout.postgres_password_file(request))
    message = (
        "ticketbox/fresh-owner/v1\0" + request.operation_id + "\0" + request.install_id
    ).encode("utf-8")
    return hmac.new(postgres_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_existing_credentials(
    runner: CommandRunner,
    request: InstallRequest,
    *,
    allow_missing: bool,
) -> None:
    secrets_root = layout.secrets_dir(request)
    existing_names = {path.name for path in secrets_root.iterdir()} if secrets_root.is_dir() else set()
    if existing_names - KNOWN_SECRET_NAMES:
        raise LifecycleViolation("credential_invalid", "secrets directory contains an unknown object")
    if not allow_missing and not DURABLE_SECRET_NAMES.issubset(existing_names):
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
            runner,
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
        runner,
        runtime_env,
        code="credential_acl_untrusted",
        required_reader_markers=(
            native.service_sid(runner, request.backend_service_name),
            f"NT SERVICE\\{request.backend_service_name}",
        ),
    )


def ensure_credentials(request: InstallRequest) -> None:
    secrets_root = layout.secrets_dir(request)
    secrets_root.mkdir(parents=True, exist_ok=True)
    postgres_password = _read_or_create_secret(layout.postgres_password_file(request))
    migrator_password = _read_or_create_secret(layout.migrator_password_file(request))
    runtime_password = _read_or_create_secret(layout.runtime_password_file(request))
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


def _read_or_create_secret(path: Path) -> str:
    if path.is_file():
        return _read_secret(path)
    if path.exists() or path.is_symlink():
        raise LifecycleViolation("credential_invalid", f"credential is not a regular file: {path.name}")
    value = secrets.token_urlsafe(32)
    durable_write_text(path, value + "\n")
    return value


def _read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise LifecycleViolation("credential_invalid", f"credential is unreadable: {path.name}") from exc
    if not 32 <= len(value) <= 200 or any(character.isspace() for character in value):
        raise LifecycleViolation("credential_invalid", f"credential is malformed: {path.name}")
    return value


def _app_database_url(request: InstallRequest, runtime_password: str) -> str:
    return (
        f"postgresql+psycopg://{RUNTIME_ROLE}:{runtime_password}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )
