from __future__ import annotations

import json
import time

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import DATABASE_NAME, RUNTIME_ROLE
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok, sealed_pg_env
from ticketbox_lifecycle.runtime.postgres_connection import maintenance_database_url
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
        require_ok(completed, code="owner_claim_failed")
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
        deadline = time.time() + 60
        last: LifecycleError | None = None
        while time.time() < deadline:
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
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{request.backend_port}/api/health/installation"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    raise LifecycleError("health_failed", f"installation health returned {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LifecycleError("health_unreachable", f"installation health is unreachable: {exc}") from exc
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise LifecycleError("health_identity_mismatch", "installation health is not JSON") from exc
        if payload.get("contract") != "ticketbox-installation-health-v2" or payload.get("status") != "ok":
            raise LifecycleError("health_identity_mismatch", "installation health contract is not v2")
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
        psql = layout.tool(request, "psql.exe")
        completed = self._runner.run(
            [
                str(psql),
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                "127.0.0.1",
                "-p",
                str(request.pg_port),
                "-U",
                RUNTIME_ROLE,
                "-d",
                DATABASE_NAME,
                "-tA",
                "-c",
                "SELECT dataset_id FROM dataset_authority WHERE singleton_id = 1",
            ],
            env=sealed_pg_env(str(layout.pg_passfile(request))),
        )
        if completed.returncode != 0:
            raise LifecycleError("health_identity_mismatch", "dataset_authority is unreadable")
        return completed.stdout.strip().splitlines()[0].strip() if completed.stdout.strip() else ""
