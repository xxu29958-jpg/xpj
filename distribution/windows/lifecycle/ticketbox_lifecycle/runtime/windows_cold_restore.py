"""SCM/credential mechanics for the bounded same-environment restore action."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.postgres_roles import _escape_literal, provision_statements
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.runtime.command import CommandRunner, sealed_pg_env
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.runtime.postgres_connection import maintenance_database_url
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_postgres import _write_cluster_config
from ticketbox_lifecycle.runtime.windows_services import start_service
from ticketbox_lifecycle.schemas import InstallRequest, OwnerPairing


class WindowsColdRestore:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def prepare_data(self, request: InstallRequest, source: ColdRestoreSource) -> None:
        system_id = read_stopped_cluster(self.runner, layout.pg_bin(request), layout.pgdata(request))
        if system_id != source.identity["postgres_system_identifier"]:
            raise LifecycleError("restore_cluster_mismatch", "copied cluster does not match the selected backup")
        _write_cluster_config(request)
        # These copied projections carry old credentials/remote exposure. The
        # immutable source keeps them; the candidate gets new managed values.
        (Path(request.data_root) / "app" / ".env").unlink()
        settings = Path(request.data_root) / "app" / "runtime-settings" / "runtime-settings.json"
        if settings.exists():
            settings.unlink()

    def rotate_credentials(self, request: InstallRequest, source: ColdRestoreSource) -> None:
        private = layout.active_operation(request).parent / "restore-source.pgpass"
        with zipfile.ZipFile(source.stream) as archive:
            old = archive.read("machine/secrets/postgres.password").decode("ascii").strip()
        if not 32 <= len(old) <= 200 or any(char.isspace() or char in ":\\" for char in old):
            raise LifecycleError("restore_credential_invalid", "backup maintenance credential is invalid")
        durable_write_text(private, f"127.0.0.1:{request.pg_port}:postgres:postgres:{old}\n")
        WindowsFileSecurity().protect_file(self.runner, private, reader_sids=(), code="restore_credential_acl_failed")
        try:
            start_service(self.runner, request.pg_service_name, code="restore_pg_start_failed")
            expected = source.identity["postgres_system_identifier"]
            deadline = time.monotonic() + 90
            while True:
                observed = self._psql(request, private, "SELECT system_identifier FROM pg_control_system();")
                if observed.returncode == 0:
                    if observed.stdout.strip() != expected:
                        raise LifecycleError("restore_cluster_mismatch", "running cluster does not match the selected backup")
                    break
                if time.monotonic() >= deadline:
                    raise LifecycleError("restore_pg_unavailable", "copied cluster or backup maintenance credential is unavailable")
                time.sleep(1)
            postgres = layout.postgres_password_file(request).read_text().strip()
            migrator = layout.migrator_password_file(request).read_text().strip()
            runtime = layout.runtime_password_file(request).read_text().strip()
            statements = provision_statements(migrator_password=migrator, runtime_password=runtime)
            guard = (
                "DO $$ BEGIN IF (SELECT system_identifier::text FROM pg_control_system()) <> "
                f"'{_escape_literal(str(expected))}' THEN RAISE EXCEPTION 'restore cluster changed'; END IF; END $$;"
            )
            sql = "\n".join(("BEGIN;", guard, f"ALTER ROLE postgres PASSWORD '{_escape_literal(postgres)}';", *statements, "COMMIT;"))
            if self._psql(request, private, sql).returncode != 0:
                raise LifecycleError("restore_credential_rotation_failed", "candidate credential rotation failed; keep candidate fenced")
        finally:
            private.unlink(missing_ok=True)

    def _psql(self, request: InstallRequest, passfile: Path, sql: str):
        return self.runner.run([str(layout.tool(request, "psql.exe")), "-X", "-w", "-v", "ON_ERROR_STOP=1",
            "-h", "127.0.0.1", "-p", str(request.pg_port), "-U", "postgres", "-d", "postgres", "-tA", "-f", "-"],
            env=sealed_pg_env(str(passfile)), input_text=sql, timeout_s=30)

    def rebind_identity(self, request: InstallRequest, source: ColdRestoreSource, *, secret: str) -> OwnerPairing:
        payload = {"source": source.identity, "installation_id": request.install_id,
            "backup_id": source.backup_id, "operation_id": request.operation_id, "bootstrap_secret": secret,
            "recovery_secret": source.recovery_secret()}
        completed = self.runner.run([str(layout.maintenance_helper(request)), "--restore-cold-dataset",
            "--database-url", maintenance_database_url(request), "--pgpassfile", str(layout.pg_passfile(request)),
            "--data-root", request.data_root], env=sealed_pg_env(str(layout.pg_passfile(request))),
            input_text=json.dumps(payload), timeout_s=180)
        if completed.returncode != 0:
            raise LifecycleError("restore_dataset_failed", "dataset, originals or owner rebind failed; keep source and candidate")
        result = json.loads(completed.stdout)
        if (result.get("schema") != "ticketbox-cold-restore-dataset-v1"
                or result.get("installation_id") != request.install_id or result.get("dataset_id") != request.dataset_id
                or result.get("restore_epoch") != source.identity["restore_epoch"] + 1
                or result.get("backup_id") != source.backup_id):
            raise LifecycleError("restore_result_mismatch", "dataset maintenance result does not match the restore operation")
        pairing = result["pairing"]
        if pairing["installation_id"] != request.install_id or pairing["operation_id"] != request.operation_id:
            raise LifecycleError("restore_result_mismatch", "owner pairing does not match the restore operation")
        return OwnerPairing(pairing_code=pairing["pairing_code"], pairing_expires_at=pairing["pairing_expires_at"])
