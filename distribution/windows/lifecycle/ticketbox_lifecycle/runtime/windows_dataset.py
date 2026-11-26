from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import (
    new_challenge,
    verifies_challenge,
    verifies_runtime_mode,
)
from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, RUNTIME_ROLE
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    CompletedCommand,
    sealed_pg_env,
    sealed_postgres_env,
)
from ticketbox_lifecycle.runtime.postgres_connection import (
    maintenance_database_url,
    run_psql,
)
from ticketbox_lifecycle.runtime.windows_installation_health import (
    fetch_installation_health,
    fetch_installation_health_with_mode,
)
from ticketbox_lifecycle.runtime.windows_process import ProcessTerminationUnconfirmedError
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest, OwnerPairing


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


class WindowsDatasetAdapter:
    name = "dataset"

    def __init__(self, runner: CommandRunner, security: WindowsSecurityAdapter) -> None:
        self._runner = runner
        self._security = security

    def claim_owner(self, request: InstallRequest) -> OwnerPairing:
        helper = layout.maintenance_helper(request)
        if not helper.is_file():
            raise LifecycleError(
                "missing_platform_binary",
                "ticketbox-database-maintenance.exe is not installed",
            )
        if not request.install_id:
            raise LifecycleError("missing_identity", "owner claim requires install_id")
        secret = self._security.owner_bootstrap_secret(request)
        completed = self._runner.run(
            [
                str(helper),
                "--fresh-owner-claim",
                "--database-url",
                maintenance_database_url(request),
                "--pgpassfile",
                str(layout.pg_passfile(request)),
                "--operation-id",
                request.operation_id,
                "--installation-id",
                request.install_id,
            ],
            env=sealed_pg_env(str(layout.pg_passfile(request))),
            timeout_s=120,
            input_text=secret + "\n",
        )
        if completed.returncode != 0:
            raise LifecycleError("owner_claim_failed", "owner claim helper failed")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LifecycleError("owner_claim_failed", "owner claim result is not JSON") from exc
        expected_fields = {
            "contract",
            "operation_id",
            "installation_id",
            "account_name",
            "ledger_id",
            "ledger_name",
            "device_name",
            "pairing_code",
            "pairing_expires_at",
            "pairing_derivation_index",
            "claim_generation",
        }
        code = payload.get("pairing_code") if isinstance(payload, dict) else None
        expiration = payload.get("pairing_expires_at") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or set(payload) != expected_fields
            or payload.get("contract") != "ticketbox-installation-owner-pairing-v1"
            or payload.get("operation_id") != request.operation_id
            or payload.get("installation_id") != request.install_id
            or not isinstance(code, str)
            or len(code) != 8
            or not code.isdigit()
            or not isinstance(expiration, str)
            or not expiration
        ):
            raise LifecycleError("owner_claim_failed", "owner claim result does not match this install")
        return OwnerPairing(pairing_code=code, pairing_expires_at=expiration)

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "health":
            raise LifecycleViolation("wrong_adapter", "dataset adapter only owns health")
        return self._wait_for_probe(request, expected_mode=None)

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "health":
            raise LifecycleViolation("wrong_adapter", "dataset adapter only owns health")
        self._probe(request, expected_mode=None)

    def wait_for_runtime_mode(self, request: InstallRequest, *, expected_mode: str) -> str:
        return self._wait_for_probe(request, expected_mode=expected_mode)

    def verify_runtime_mode(self, request: InstallRequest, *, expected_mode: str) -> None:
        self._probe(request, expected_mode=expected_mode)

    def verify_preserved_dataset(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> dict[str, object]:
        helper = layout.maintenance_helper(request)
        if not helper.is_file():
            raise LifecycleError("missing_platform_binary", "database maintenance helper is missing")
        completed = self._runner.run(
            [
                str(helper),
                "--verify-preserved-dataset",
                "--database-url",
                maintenance_database_url(request),
                "--pgpassfile",
                str(layout.pg_passfile(request)),
                "--data-root",
                request.data_root,
                "--dataset-id",
                binding.dataset_id,
                "--installation-id",
                binding.install_id,
                "--expected-restore-epoch",
                str(binding.expected_restore_epoch),
                "--schema-revision",
                request.schema_revision,
                "--semantic-revision",
                request.semantic_revision or "ticketbox-dataset-semantics-v1",
            ],
            env=sealed_pg_env(str(layout.pg_passfile(request))),
            input_text="",
            timeout_s=180,
        )
        if completed.returncode != 0:
            raise LifecycleError(
                "reinstall_dataset_verify_failed",
                "preserved dataset authority or retained original verification failed",
            )
        payload = json.loads(completed.stdout)
        if (
            payload.get("schema") != "ticketbox-preserved-dataset-verify-v1"
            or payload.get("dataset_id") != binding.dataset_id
            or payload.get("installation_id") != binding.install_id
            or payload.get("restore_epoch") != binding.expected_restore_epoch
            or payload.get("schema_revision") != request.schema_revision
        ):
            raise LifecycleError(
                "reinstall_dataset_mismatch",
                "preserved dataset verification result does not match installation binding",
            )
        return payload

    def verify_live_authority(
        self,
        request: InstallRequest,
        *,
        expected_restore_epoch: int,
    ) -> None:
        completed = run_psql(
            self._runner,
            request,
            "SELECT dataset_id || '|' || client_generation || '|' || restore_epoch "
            "FROM dataset_authority WHERE singleton_id = 1",
            database=DATABASE_NAME,
            user=RUNTIME_ROLE,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise LifecycleError("health_identity_mismatch", "dataset_authority is unreadable")
        first = completed.stdout.strip().splitlines()[0].strip()
        parts = first.split("|")
        if len(parts) != 3:
            raise LifecycleError("health_identity_mismatch", "dataset_authority row format is invalid")
        observed_dataset_id, observed_generation, observed_epoch = parts
        if (
            (request.dataset_id and observed_dataset_id != request.dataset_id)
            or (request.install_id and observed_generation != request.install_id)
            or observed_epoch != str(expected_restore_epoch)
        ):
            raise LifecycleError(
                "health_identity_mismatch",
                "live dataset_authority does not match expected dataset_id, install_id or restore_epoch",
            )

    def _prepare_stopped_pgdata_probe(
        self,
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
        read_stopped_cluster(self._runner, pg_bin, pgdata)
        return pgdata, pg_bin, secrets_dir, runtime_password

    def _is_probe_cluster_stopped(self, pg_bin: Path, pgdata: Path) -> bool:
        from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster

        if os.path.lexists(pgdata / "postmaster.pid"):
            return False
        try:
            read_stopped_cluster(self._runner, pg_bin, pgdata)
        except (LifecycleError, OSError, ProcessTerminationUnconfirmedError):
            return False
        return not os.path.lexists(pgdata / "postmaster.pid")

    def _run_probe_fast_stop(self, pg_ctl: Path, pgdata: Path, pg_env: Mapping[str, str]) -> None:
        with contextlib.suppress(LifecycleError, OSError, ProcessTerminationUnconfirmedError):
            self._runner.run(
                [str(pg_ctl), "-D", str(pgdata), "-m", "fast", "-w", "-t", "60", "stop"],
                env=pg_env,
                timeout_s=75,
            )

    def _finalize_ephemeral_probe_stop(
        self,
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
            self._run_probe_fast_stop(pg_ctl, pgdata, pg_env)
        elif on_timeout_ran:
            stop_verified = self._is_probe_cluster_stopped(pg_bin, pgdata)
            if not stop_verified:
                self._run_probe_fast_stop(pg_ctl, pgdata, pg_env)
                stop_verified = self._is_probe_cluster_stopped(pg_bin, pgdata)
        else:
            for _ in range(2):
                self._run_probe_fast_stop(pg_ctl, pgdata, pg_env)
                if self._is_probe_cluster_stopped(pg_bin, pgdata):
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

    def _execute_ephemeral_probe_query(
        self,
        pg_bin: Path,
        pgdata: Path,
        probe_pgpass: Path,
        ephemeral_port: int,
        pg_env: Mapping[str, str],
    ) -> CompletedCommand:
        pg_ctl = pg_bin / "pg_ctl.exe"
        psql = pg_bin / "psql.exe"
        job_ctx = (
            self._runner.open_managed_job()
            if hasattr(self._runner, "open_managed_job")
            else contextlib.nullcontext(self._runner)
        )
        with pgdata_security.temporary_probe_access(pgdata), job_ctx as probe_runner:
            start_attempted = False
            on_timeout_ran = False
            starter_exit_confirmed = True
            body_error: BaseException | None = None

            def _on_timeout_stop() -> None:
                nonlocal on_timeout_ran
                on_timeout_ran = True
                self._run_probe_fast_stop(pg_ctl, pgdata, pg_env)

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
                return self._runner.run(
                    [
                        str(psql), "-X", "-v", "ON_ERROR_STOP=1", "-At",
                        "-h", "127.0.0.1", "-p", str(ephemeral_port),
                        "-U", RUNTIME_ROLE, "-d", DATABASE_NAME, "-c",
                        "SELECT dataset_id || '|' || client_generation || '|' || restore_epoch "
                        "FROM dataset_authority WHERE singleton_id = 1",
                    ],
                    env=sealed_pg_env(str(probe_pgpass)),
                    timeout_s=30,
                )
            except BaseException as exc:
                body_error = exc
                if isinstance(exc, LifecycleError) and exc.code == "starter_process_not_exited":
                    starter_exit_confirmed = False
                raise
            finally:
                if start_attempted:
                    self._finalize_ephemeral_probe_stop(
                        pg_bin,
                        pgdata,
                        pg_env,
                        starter_exit_confirmed=starter_exit_confirmed,
                        on_timeout_ran=on_timeout_ran,
                        body_error=body_error,
                    )

    @staticmethod
    def _parse_stopped_pgdata_identity(
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

    def verify_stopped_pgdata_dataset_id(
        self,
        binding: InstallationBinding,
        *,
        app_dir: Path,
        program_data_root: Path,
    ) -> dict[str, object]:
        from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster

        pgdata, pg_bin, secrets_dir, runtime_password = self._prepare_stopped_pgdata_probe(
            binding,
            app_dir=app_dir,
            program_data_root=program_data_root,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_sock:
            probe_sock.bind(("127.0.0.1", 0))
            ephemeral_port = int(probe_sock.getsockname()[1])

        pg_env = sealed_postgres_env()
        probe_dir = Path(tempfile.mkdtemp(prefix="purge-probe-", dir=str(secrets_dir)))
        probe_pgpass = probe_dir / "pgpass"
        try:
            escaped_pw = runtime_password.replace("\\", "\\\\").replace(":", "\\:")
            probe_pgpass.write_text(
                f"127.0.0.1:{ephemeral_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{escaped_pw}\n"
                f"localhost:{ephemeral_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{escaped_pw}\n",
                encoding="ascii",
                newline="\n",
            )
            completed = self._execute_ephemeral_probe_query(
                pg_bin,
                pgdata,
                probe_pgpass,
                ephemeral_port,
                pg_env,
            )
        finally:
            try:
                if os.path.lexists(probe_pgpass):
                    probe_pgpass.unlink()
            finally:
                with contextlib.suppress(OSError):
                    if probe_dir.is_dir():
                        probe_dir.rmdir()
        read_stopped_cluster(self._runner, pg_bin, pgdata)
        return self._parse_stopped_pgdata_identity(completed, binding)

    def _wait_for_probe(self, request: InstallRequest, *, expected_mode: str | None) -> str:
        deadline = time.monotonic() + 60
        last: LifecycleError | None = None
        while time.monotonic() < deadline:
            try:
                return self._probe(request, expected_mode=expected_mode)
            except LifecycleError as exc:
                last = exc
                time.sleep(1)
        if last is None:
            raise LifecycleError("health_unreachable", "installation health is unreachable")
        raise last

    def _probe(self, request: InstallRequest, *, expected_mode: str | None = None) -> str:
        challenge = new_challenge()
        runtime_mode: str | None = None
        mode_attestation: str | None = None
        if expected_mode is None:
            status, body, attestation = fetch_installation_health(
                request.backend_port,
                challenge=challenge,
            )
        else:
            status, body, attestation, runtime_mode, mode_attestation = fetch_installation_health_with_mode(
                request.backend_port,
                challenge=challenge,
            )
        if status != 200:
            raise LifecycleError("health_failed", f"installation health returned {status}")
        payload = _parse_health_payload(body)
        _verify_health_attestation(
            request.health_attestation_key,
            challenge,
            attestation,
            expected_mode=expected_mode,
            runtime_mode=runtime_mode,
            mode_attestation=mode_attestation,
        )
        _verify_health_identity(payload, request)
        dataset = self._live_dataset_id(request)
        if request.dataset_id and dataset != request.dataset_id:
            raise LifecycleError(
                "health_identity_mismatch",
                "live dataset_id does not match this operation",
            )
        return "healthy"

    def _live_dataset_id(self, request: InstallRequest) -> str:
        completed = run_psql(
            self._runner,
            request,
            "SELECT dataset_id FROM dataset_authority WHERE singleton_id = 1",
            database=DATABASE_NAME,
            user=RUNTIME_ROLE,
        )
        if completed.returncode != 0:
            raise LifecycleError("health_identity_mismatch", "dataset_authority is unreadable")
        return completed.stdout.strip().splitlines()[0].strip() if completed.stdout.strip() else ""


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
