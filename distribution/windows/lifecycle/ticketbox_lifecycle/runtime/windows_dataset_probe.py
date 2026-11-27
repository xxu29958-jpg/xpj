"""Stopped-pgdata ephemeral probe helpers and installation health verification."""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import (
    verifies_challenge,
    verifies_runtime_mode,
)
from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, RUNTIME_ROLE
from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    CompletedCommand,
)
from ticketbox_lifecycle.runtime.windows_process import ProcessTerminationUnconfirmedError
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest

_HEALTH_FIELDS = frozenset({
    "contract",
    "status",
    "product",
    "backend_version",
    "installation_id",
    "runtime_access_state",
    "owner_state",
    "owner_recovery_channel",
    "mobile_connectivity",
})


def _run_probe_start(
    runner: object,
    argv: list[str],
    *,
    env: Mapping[str, str],
    timeout_s: int,
    on_timeout: Callable[[], None] | None = None,
) -> CompletedCommand:
    starter = getattr(runner, "run_background_starter", None)
    if callable(starter):
        return starter(
            argv,
            env=env,
            timeout_s=timeout_s,
            on_timeout=on_timeout,
        )
    return cast(CommandRunner, runner).run(argv, env=env, timeout_s=timeout_s)


def _parse_pgpass_fields(line: str) -> list[str]:
    fields: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":" and len(fields) < 4:
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf))
    return fields


def _read_runtime_probe_password(runtime_pw_file: Path, pgpass_file: Path) -> str:
    if os.path.lexists(runtime_pw_file):
        reject_reparse_components(runtime_pw_file)
        if not runtime_pw_file.is_file():
            raise LifecycleViolation(
                "purge_dataset_identity_unverifiable",
                "runtime credential file is not a regular file",
            )
        value = runtime_pw_file.read_text(encoding="ascii").strip()
        if value:
            return value
    for raw_line in pgpass_file.read_text(encoding="ascii").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = _parse_pgpass_fields(line)
        if (
            len(fields) == 5
            and fields[0] in {"127.0.0.1", "localhost", "*"}
            and fields[2] in {DATABASE_NAME, "*"}
            and fields[3] == RUNTIME_ROLE
            and fields[4]
        ):
            return fields[4]
    raise LifecycleViolation(
        "purge_dataset_identity_unverifiable",
        "cannot resolve runtime PostgreSQL credential for stopped pgdata verification",
    )


def prepare_stopped_pgdata_probe(
    runner: CommandRunner,
    binding: InstallationBinding,
    *,
    app_dir: Path,
    program_data_root: Path,
) -> tuple[Path, Path, Path, str]:
    from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster

    pgdata = Path(binding.data_root) / "pgdata"
    reject_reparse_components(pgdata)
    if not pgdata.is_dir() or not (pgdata / "PG_VERSION").is_file():
        raise LifecycleViolation(
            "purge_pgdata_missing",
            "stopped pgdata directory is missing; refusing blind permanent deletion",
        )
    pg_bin = app_dir / "postgresql" / "bin"
    pg_ctl = pg_bin / "pg_ctl.exe"
    psql = pg_bin / "psql.exe"
    pg_controldata = pg_bin / "pg_controldata.exe"
    secrets_dir = program_data_root / "machine" / "secrets"
    pgpass = secrets_dir / "pgpass"
    runtime_pw_file = secrets_dir / f"{RUNTIME_ROLE}.password"
    for required in (pg_bin, pg_ctl, psql, pg_controldata, secrets_dir, pgpass):
        reject_reparse_components(required)
    if not (pg_ctl.is_file() and psql.is_file() and pg_controldata.is_file() and pgpass.is_file()):
        raise LifecycleViolation(
            "purge_dataset_identity_unverifiable",
            "local PostgreSQL verification tools or pgpass are missing; cannot prove stopped pgdata dataset identity",
        )
    runtime_password = _read_runtime_probe_password(runtime_pw_file, pgpass)
    if (pgdata / "postmaster.pid").exists():
        raise LifecycleViolation(
            "purge_cluster_not_stopped",
            "pgdata still has postmaster.pid; stop PostgreSQL cleanly before purging data",
        )
    if (pgdata / "PG_VERSION").read_text(encoding="ascii").strip() != str(binding.postgres_major):
        raise LifecycleViolation(
            "purge_dataset_identity_mismatch",
            "stopped pgdata PostgreSQL major version disagrees with installation binding",
        )
    read_stopped_cluster(runner, pg_bin, pgdata)
    return pgdata, pg_bin, secrets_dir, runtime_password


def is_probe_cluster_stopped(runner: CommandRunner, pg_bin: Path, pgdata: Path) -> bool:
    from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster

    if os.path.lexists(pgdata / "postmaster.pid"):
        return False
    try:
        read_stopped_cluster(runner, pg_bin, pgdata)
    except (LifecycleError, OSError, ProcessTerminationUnconfirmedError):
        return False
    return not os.path.lexists(pgdata / "postmaster.pid")


def run_probe_fast_stop(runner: CommandRunner, pg_ctl: Path, pgdata: Path, pg_env: Mapping[str, str]) -> None:
    with contextlib.suppress(LifecycleError, OSError, ProcessTerminationUnconfirmedError):
        runner.run(
            [str(pg_ctl), "-D", str(pgdata), "-m", "fast", "-w", "-t", "60", "stop"],
            env=pg_env,
            timeout_s=75,
        )


def finalize_ephemeral_probe_stop(
    runner: CommandRunner,
    pg_bin: Path,
    pgdata: Path,
    pg_env: Mapping[str, str],
    *,
    starter_exit_confirmed: bool,
    on_timeout_ran: bool,
    body_error: BaseException | None,
) -> None:
    pg_ctl = pg_bin / "pg_ctl.exe"
    stop_verified = False
    if not starter_exit_confirmed:
        run_probe_fast_stop(runner, pg_ctl, pgdata, pg_env)
    elif on_timeout_ran:
        stop_verified = is_probe_cluster_stopped(runner, pg_bin, pgdata)
        if not stop_verified:
            run_probe_fast_stop(runner, pg_ctl, pgdata, pg_env)
            stop_verified = is_probe_cluster_stopped(runner, pg_bin, pgdata)
    else:
        for _ in range(2):
            run_probe_fast_stop(runner, pg_ctl, pgdata, pg_env)
            if is_probe_cluster_stopped(runner, pg_bin, pgdata):
                stop_verified = True
                break
    if stop_verified:
        return
    if body_error is not None:
        primary_code = (
            body_error.code if isinstance(body_error, LifecycleError) else type(body_error).__name__
        )
        raise LifecycleError(
            "purge_probe_stop_failed",
            f"ephemeral read-only PostgreSQL probe could not be cleanly stopped (after {primary_code})",
        ) from body_error
    raise LifecycleError(
        "purge_probe_stop_failed",
        "ephemeral read-only PostgreSQL probe could not be cleanly stopped",
    )


def execute_ephemeral_probe_query(
    runner: CommandRunner,
    pg_bin: Path,
    pgdata: Path,
    ephemeral_port: int,
    pg_env: Mapping[str, str],
    query_env: Mapping[str, str],
) -> CompletedCommand:
    pg_ctl = pg_bin / "pg_ctl.exe"
    psql = pg_bin / "psql.exe"
    job_ctx = (
        runner.open_managed_job()
        if hasattr(runner, "open_managed_job")
        else contextlib.nullcontext(runner)
    )
    with pgdata_security.temporary_probe_access(pgdata), job_ctx as probe_runner:
        start_attempted = False
        on_timeout_ran = False
        starter_exit_confirmed = True
        body_error: BaseException | None = None

        def _on_timeout_stop() -> None:
            nonlocal on_timeout_ran
            on_timeout_ran = True
            run_probe_fast_stop(runner, pg_ctl, pgdata, pg_env)

        try:
            start_attempted = True
            started = _run_probe_start(
                probe_runner,
                [
                    str(pg_ctl), "-D", str(pgdata), "-w", "-t", "30", "-l", "NUL", "-o",
                    f"-h 127.0.0.1 -p {ephemeral_port} -c listen_addresses=127.0.0.1 -c default_transaction_read_only=on",
                    "start",
                ],
                env=pg_env,
                timeout_s=45,
                on_timeout=_on_timeout_stop,
            )
            if started.returncode != 0:
                raise LifecycleViolation(
                    "purge_dataset_identity_unverifiable",
                    "could not start ephemeral read-only PostgreSQL probe to verify stopped pgdata identity",
                )
            return runner.run(
                [
                    str(psql), "-X", "-v", "ON_ERROR_STOP=1", "-At",
                    "-h", "127.0.0.1", "-p", str(ephemeral_port),
                    "-U", RUNTIME_ROLE, "-d", DATABASE_NAME, "-c",
                    "SELECT dataset_id || '|' || client_generation || '|' || restore_epoch "
                    "FROM dataset_authority WHERE singleton_id = 1",
                ],
                env=query_env,
                timeout_s=30,
            )
        except BaseException as exc:
            body_error = exc
            if isinstance(exc, LifecycleError) and exc.code == "starter_process_not_exited":
                starter_exit_confirmed = False
            raise
        finally:
            if start_attempted:
                finalize_ephemeral_probe_stop(
                    runner,
                    pg_bin,
                    pgdata,
                    pg_env,
                    starter_exit_confirmed=starter_exit_confirmed,
                    on_timeout_ran=on_timeout_ran,
                    body_error=body_error,
                )


def parse_stopped_pgdata_identity(
    completed: CompletedCommand,
    binding: InstallationBinding,
) -> dict[str, object]:
    if completed.returncode != 0 or not completed.stdout.strip():
        raise LifecycleViolation(
            "purge_dataset_identity_unverifiable",
            "stopped pgdata dataset_authority could not be read",
        )
    first = completed.stdout.strip().splitlines()[0].strip()
    parts = first.split("|")
    if len(parts) != 3:
        raise LifecycleViolation(
            "purge_dataset_identity_unverifiable",
            "stopped pgdata dataset_authority row is malformed",
        )
    observed_dataset_id, observed_generation, observed_epoch = parts
    if (
        observed_dataset_id != binding.dataset_id
        or observed_generation != binding.install_id
        or observed_epoch != str(binding.expected_restore_epoch)
    ):
        raise LifecycleViolation(
            "purge_dataset_identity_mismatch",
            "stopped pgdata belongs to a different dataset or generation than the confirmed installation",
        )
    return {
        "dataset_id": observed_dataset_id,
        "client_generation": observed_generation,
        "restore_epoch": int(observed_epoch),
    }


def _parse_health_payload(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError, TypeError) as exc:
        raise LifecycleError("health_identity_mismatch", "installation health is not JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _HEALTH_FIELDS:
        raise LifecycleError("health_identity_mismatch", "installation health fields are not closed")
    return payload


def _verify_health_attestation(
    key: str,
    challenge: str,
    attestation: str | None,
    *,
    expected_mode: str | None,
    runtime_mode: str | None,
    mode_attestation: str | None,
) -> None:
    try:
        attested = verifies_challenge(key, challenge, attestation)
    except ValueError as exc:
        raise LifecycleError(
            "health_identity_mismatch",
            "installation health attestation input is invalid",
        ) from exc
    if not attested:
        raise LifecycleError(
            "health_identity_mismatch",
            "installation health responder is not the bound backend",
        )
    if expected_mode is None:
        return
    if runtime_mode != expected_mode:
        raise LifecycleError(
            "health_mode_mismatch",
            f"installation health reported mode {runtime_mode!r}, expected {expected_mode!r}",
        )
    try:
        mode_ok = verifies_runtime_mode(key, challenge, expected_mode, mode_attestation)
    except ValueError as exc:
        raise LifecycleError(
            "health_mode_mismatch",
            "installation health runtime mode attestation input is invalid",
        ) from exc
    if not mode_ok:
        raise LifecycleError(
            "health_mode_mismatch",
            "installation health runtime mode attestation is invalid",
        )


def _verify_health_identity(payload: dict[str, object], request: InstallRequest) -> None:
    if payload.get("contract") != "ticketbox-installation-health-v3" or payload.get("status") != "ok":
        raise LifecycleError("health_identity_mismatch", "installation health contract is not v3")
    if payload.get("backend_version") != request.target_release_id:
        raise LifecycleError(
            "health_identity_mismatch",
            "installation health backend version does not match this release",
        )
    if payload.get("installation_id") != request.install_id:
        raise LifecycleError(
            "health_identity_mismatch",
            "installation health identity does not match this install",
        )
    if payload.get("runtime_access_state") != "available":
        raise LifecycleError("health_failed", "installation runtime is not available")
    if payload.get("owner_state") != "configured":
        raise LifecycleError("health_failed", "installation owner is not configured")
