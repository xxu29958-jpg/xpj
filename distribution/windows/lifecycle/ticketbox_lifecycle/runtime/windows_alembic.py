from __future__ import annotations

import json

from ticketbox_lifecycle.adapters.upgrade import UpgradeMigrationResult
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    expected_alembic_probe,
    verify_alembic_version_sql,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok, sealed_pg_env
from ticketbox_lifecycle.runtime.postgres_connection import maintenance_database_url, run_psql
from ticketbox_lifecycle.schemas import InstallRequest

_MIGRATION_RESULT_SCHEMA = "ticketbox-existing-dataset-upgrade-result-v1"
_MIGRATION_RESULT_FIELDS = frozenset({
    "schema",
    "operation_id",
    "dataset_id",
    "installation_id",
    "restore_epoch",
    "source_revision",
    "target_revision",
    "alembic_revision",
    "backup_archive_sha256",
    "result",
})


class WindowsAlembicAdapter:
    name = "alembic"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "alembic":
            raise LifecycleViolation("wrong_adapter", "alembic adapter only owns alembic")
        helper = layout.maintenance_helper(request)
        if not helper.is_file():
            raise LifecycleError("missing_platform_binary", "ticketbox-database-maintenance.exe is not installed")
        if not request.schema_revision or request.schema_revision == "99991231_9999":
            raise LifecycleError(
                "missing_schema_revision",
                "release-manifest max_schema_revision is not a real Alembic revision",
            )
        url = maintenance_database_url(request)
        argv = [
            str(helper),
            "--fresh-schema-upgrade",
            "--database-url",
            url,
            "--pgpassfile",
            str(layout.pg_passfile(request)),
            "--target-revision",
            request.schema_revision,
            "--dataset-id",
            request.dataset_id,
            "--client-generation",
            request.install_id,
            "--schema-min-compatible",
            request.schema_min_compatible,
            "--semantic-revision",
            request.semantic_revision,
            "--operation-id",
            request.operation_id,
        ]
        require_ok(
            self._runner.run(
                argv,
                env=sealed_pg_env(str(layout.pg_passfile(request))),
                timeout_s=600,
                input_text="",
            ),
            code="alembic_failed",
        )
        return "upgraded"

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "alembic":
            raise LifecycleViolation("wrong_adapter", "alembic adapter only owns alembic")
        if not request.schema_revision:
            raise LifecycleError("postcondition_missing", "schema revision is unbound")
        completed = run_psql(
            self._runner,
            request,
            verify_alembic_version_sql(request.schema_revision),
            database=DATABASE_NAME,
            user=MIGRATOR_ROLE,
        )
        observed = completed.stdout.replace("\r\n", "\n").strip()
        expected = expected_alembic_probe()
        if completed.returncode != 0 or observed not in {expected, f"SET\n{expected}"}:
            raise LifecycleError("postcondition_missing", "alembic_version is not the exact release target")

    def upgrade_existing_dataset(
        self,
        request: InstallRequest,
        *,
        source_revision: str,
        target_revision: str,
        expected_restore_epoch: int,
        backup_path: str,
        backup_sha256: str,
    ) -> UpgradeMigrationResult:
        helper = layout.maintenance_helper(request)
        if not helper.is_file():
            raise LifecycleError(
                "missing_platform_binary",
                "ticketbox-database-maintenance.exe is not installed",
            )
        if not backup_path or not backup_sha256:
            raise LifecycleViolation(
                "upgrade_backup_missing",
                "offline migration requires both backup archive path and sha256",
            )
        argv = [
            str(helper),
            "--upgrade-existing-dataset",
            "--database-url",
            maintenance_database_url(request),
            "--pgpassfile",
            str(layout.pg_passfile(request)),
            "--source-revision",
            source_revision,
            "--target-revision",
            target_revision,
            "--dataset-id",
            request.dataset_id,
            "--installation-id",
            request.install_id,
            "--expected-restore-epoch",
            str(expected_restore_epoch),
            "--operation-id",
            request.operation_id,
            "--data-root",
            request.data_root,
            "--backup-archive",
            backup_path,
            "--backup-archive-sha256",
            backup_sha256,
            "--app-dir",
            request.app_dir,
        ]
        completed = self._runner.run(
            argv,
            env=sealed_pg_env(str(layout.pg_passfile(request))),
            timeout_s=1200,
            input_text="",
        )
        require_ok(completed, code="upgrade_migration_failed")
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LifecycleError("upgrade_migration_failed", "upgrade helper did not return JSON") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != _MIGRATION_RESULT_FIELDS
            or payload.get("schema") != _MIGRATION_RESULT_SCHEMA
            or payload.get("operation_id") != request.operation_id
            or payload.get("dataset_id") != request.dataset_id
            or payload.get("installation_id") != request.install_id
            or payload.get("restore_epoch") != expected_restore_epoch
            or payload.get("source_revision") != source_revision
            or payload.get("target_revision") != target_revision
            or payload.get("alembic_revision") != target_revision
            or payload.get("backup_archive_sha256") != backup_sha256
            or payload.get("result") not in {"target_committed", "target_observed_after_interruption"}
        ):
            raise LifecycleViolation(
                "upgrade_migration_mismatch",
                "upgrade helper result does not match the exact upgrade contract",
            )
        return UpgradeMigrationResult(
            outcome=payload["result"],
            source_revision=source_revision,
            target_revision=target_revision,
            operation_id=request.operation_id,
        )
