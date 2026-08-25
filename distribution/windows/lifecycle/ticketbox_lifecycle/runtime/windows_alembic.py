from __future__ import annotations

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    verify_alembic_version_sql,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok, sealed_pg_env
from ticketbox_lifecycle.runtime.postgres_connection import maintenance_database_url, run_psql
from ticketbox_lifecycle.schemas import InstallRequest


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
            request.schema_min_compatible or request.target_release_id,
            "--semantic-revision",
            request.semantic_revision or "ticketbox-dataset-semantics-v1",
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
            verify_alembic_version_sql(),
            database=DATABASE_NAME,
            user=MIGRATOR_ROLE,
        )
        if completed.returncode != 0 or request.schema_revision not in completed.stdout:
            raise LifecycleError("postcondition_missing", "alembic_version is not the exact release target")
