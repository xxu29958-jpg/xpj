from __future__ import annotations

import json
import time

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.health_attestation import new_challenge, verifies_challenge
from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, RUNTIME_ROLE
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, sealed_pg_env
from ticketbox_lifecycle.runtime.postgres_connection import (
    maintenance_database_url,
    run_psql,
)
from ticketbox_lifecycle.runtime.windows_installation_health import (
    fetch_installation_health,
)
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import InstallRequest, OwnerPairing


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
        deadline = time.monotonic() + 60
        last: LifecycleError | None = None
        while time.monotonic() < deadline:
            try:
                return self._probe(request)
            except LifecycleError as exc:
                last = exc
                time.sleep(1)
        if last is None:
            raise LifecycleError("health_unreachable", "installation health is unreachable")
        raise last

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "health":
            raise LifecycleViolation("wrong_adapter", "dataset adapter only owns health")
        self._probe(request)

    def _probe(self, request: InstallRequest) -> str:
        challenge = new_challenge()
        status, body, attestation = fetch_installation_health(
            request.backend_port,
            challenge=challenge,
        )
        if status != 200:
            raise LifecycleError("health_failed", f"installation health returned {status}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError, TypeError) as exc:
            raise LifecycleError("health_identity_mismatch", "installation health is not JSON") from exc
        expected_fields = {
            "contract",
            "status",
            "product",
            "backend_version",
            "installation_id",
            "runtime_access_state",
            "owner_state",
            "owner_recovery_channel",
            "mobile_connectivity",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise LifecycleError(
                "health_identity_mismatch",
                "installation health fields are not closed",
            )
        try:
            attested = verifies_challenge(
                request.health_attestation_key,
                challenge,
                attestation,
            )
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
        if (
            payload.get("contract") != "ticketbox-installation-health-v3"
            or payload.get("status") != "ok"
        ):
            raise LifecycleError(
                "health_identity_mismatch",
                "installation health contract is not v3",
            )
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
