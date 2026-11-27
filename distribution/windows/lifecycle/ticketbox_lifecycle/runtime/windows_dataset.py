from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import time
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import new_challenge
from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, RUNTIME_ROLE
from ticketbox_lifecycle.runtime import layout, windows_dataset_probe
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    sealed_pg_env,
    sealed_postgres_env,
)
from ticketbox_lifecycle.runtime.postgres_connection import (
    maintenance_database_url,
    run_psql,
)
from ticketbox_lifecycle.runtime.windows_dataset_probe import (
    _parse_health_payload,
    _verify_health_attestation,
    _verify_health_identity,
)
from ticketbox_lifecycle.runtime.windows_installation_health import (
    fetch_installation_health,
    fetch_installation_health_with_mode,
)
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest, OwnerPairing

__all__ = ["WindowsDatasetAdapter"]


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

    def verify_stopped_pgdata_dataset_id(
        self,
        binding: InstallationBinding,
        *,
        app_dir: Path,
        program_data_root: Path,
    ) -> dict[str, object]:
        from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster

        pgdata, pg_bin, secrets_dir, runtime_password = windows_dataset_probe.prepare_stopped_pgdata_probe(
            self._runner,
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
            completed = windows_dataset_probe.execute_ephemeral_probe_query(
                self._runner,
                pg_bin,
                pgdata,
                ephemeral_port,
                pg_env,
                sealed_pg_env(str(probe_pgpass)),
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
        return windows_dataset_probe.parse_stopped_pgdata_identity(completed, binding)

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
