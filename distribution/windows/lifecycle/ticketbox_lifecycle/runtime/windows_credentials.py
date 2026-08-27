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
from ticketbox_lifecycle.runtime.durable_files import (
    discard_durable_pending,
    durable_pending_path,
    durable_write_text,
)
from ticketbox_lifecycle.runtime.windows_file_security import FileSecurity, file_dacl_sddl
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


def _require_installer_owner(path: Path, *, message: str) -> None:
    try:
        owner_sid = native.file_owner_sid(path)
    except OSError as exc:
        raise LifecycleViolation("credential_owner_untrusted", message) from exc
    if owner_sid != native.ADMINISTRATORS_SID:
        raise LifecycleViolation("credential_owner_untrusted", message)


def materialize_initdb_password_file(
    runner: CommandRunner,
    file_security: FileSecurity,
    request: InstallRequest,
    *,
    reader_sid: str,
) -> Path:
    path = layout.postgres_pwfile(request)
    discard_initdb_password_file(request)
    password = _read_secret(layout.postgres_password_file(request))
    durable_write_text(path, password + "\n")
    file_security.protect_file(
        runner,
        path,
        reader_sids=(reader_sid,),
        code="secret_acl_failed",
    )
    _require_installer_owner(
        path,
        message="initdb password input must have the installer Administrators owner",
    )
    native.require_protected_file_acl(
        runner,
        path,
        code="credential_acl_untrusted",
        required_reader_markers=(reader_sid,),
        forbidden_markers=("NT SERVICE\\", "S-1-5-80-"),
        expected_dacl_sddl=file_dacl_sddl((reader_sid,)),
    )
    return path


def discard_initdb_password_file(request: InstallRequest) -> None:
    path = layout.postgres_pwfile(request)
    native.reject_reparse_components(durable_pending_path(path))
    discard_durable_pending(path)
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


def _existing_credential_paths(
    request: InstallRequest,
    *,
    allow_missing: bool,
) -> tuple[tuple[Path, ...], Path | None]:
    secrets_root = layout.secrets_dir(request)
    existing_names = {path.name for path in secrets_root.iterdir()} if secrets_root.is_dir() else set()
    if existing_names - KNOWN_SECRET_NAMES:
        raise LifecycleViolation("credential_invalid", "secrets directory contains an unknown object")
    if "postgres.pwfile" in existing_names:
        raise LifecycleViolation(
            "credential_invalid",
            "transient initdb password input must not persist",
        )
    if not allow_missing and not DURABLE_SECRET_NAMES.issubset(existing_names):
        raise LifecycleError("postcondition_missing", "lifecycle secrets are incomplete")
    secret_paths = tuple(secrets_root / name for name in sorted(existing_names))
    for path in secret_paths:
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation(
                "credential_invalid",
                f"credential is not a regular file: {path.name}",
            )
    runtime_env = Path(request.data_root) / "app" / ".env"
    if not runtime_env.exists() and not runtime_env.is_symlink():
        if allow_missing:
            return secret_paths, None
        raise LifecycleError("postcondition_missing", "runtime .env is absent")
    native.reject_reparse_components(runtime_env)
    if not runtime_env.is_file():
        raise LifecycleViolation("credential_invalid", "runtime .env is not a regular file")
    return secret_paths, runtime_env


def verify_existing_credentials(
    runner: CommandRunner,
    request: InstallRequest,
    *,
    allow_missing: bool,
) -> None:
    secret_paths, runtime_env = _existing_credential_paths(
        request,
        allow_missing=allow_missing,
    )
    for path in secret_paths:
        _require_installer_owner(
            path,
            message="credential must have the installer Administrators owner",
        )
        native.require_protected_file_acl(
            runner,
            path,
            code="credential_acl_untrusted",
            forbidden_markers=("NT SERVICE\\", "S-1-5-80-"),
            expected_dacl_sddl=file_dacl_sddl(()),
        )
    if runtime_env is None:
        return
    _require_installer_owner(
        runtime_env,
        message="runtime .env must have the installer Administrators owner",
    )
    backend_sid = native.service_sid(runner, request.backend_service_name)
    native.require_protected_file_acl(
        runner,
        runtime_env,
        code="credential_acl_untrusted",
        required_reader_markers=(
            backend_sid,
            f"NT SERVICE\\{request.backend_service_name}",
        ),
        expected_dacl_sddl=file_dacl_sddl((backend_sid,)),
    )


def _protect_credential_files(
    runner: CommandRunner,
    file_security: FileSecurity,
    secret_paths: tuple[Path, ...],
    runtime_env: Path | None,
    *,
    backend_sid: str,
) -> None:
    for path in secret_paths:
        file_security.protect_file(
            runner,
            path,
            reader_sids=(),
            code="secret_acl_failed",
        )
    if runtime_env is not None:
        file_security.protect_file(
            runner,
            runtime_env,
            reader_sids=(backend_sid,),
            code="runtime_env_acl_failed",
        )


def reconcile_credentials(
    runner: CommandRunner,
    file_security: FileSecurity,
    request: InstallRequest,
) -> None:
    discard_initdb_password_file(request)
    complete_secrets = tuple(
        layout.secrets_dir(request) / name for name in sorted(DURABLE_SECRET_NAMES)
    )
    runtime_env = Path(request.data_root) / "app" / ".env"
    for destination in (*complete_secrets, runtime_env):
        native.reject_reparse_components(durable_pending_path(destination))
        discard_durable_pending(destination)
    existing_secrets, existing_env = _existing_credential_paths(
        request,
        allow_missing=True,
    )
    backend_sid = native.service_sid(runner, request.backend_service_name)
    _protect_credential_files(
        runner,
        file_security,
        existing_secrets,
        existing_env,
        backend_sid=backend_sid,
    )
    _ensure_credentials(request)
    _protect_credential_files(
        runner,
        file_security,
        complete_secrets,
        runtime_env,
        backend_sid=backend_sid,
    )
    verify_existing_credentials(runner, request, allow_missing=False)


def _ensure_credentials(request: InstallRequest) -> None:
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
