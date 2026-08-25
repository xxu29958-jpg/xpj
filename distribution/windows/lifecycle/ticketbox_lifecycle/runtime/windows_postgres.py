from __future__ import annotations

import shutil
import time
from pathlib import Path

from ticketbox_lifecycle.adapters.ports import SecurityAdapter
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
    create_database_sql,
    database_connect_statements,
    database_exists_sql,
    expected_membership_probe,
    expected_roles_probe,
    provision_statements,
    schema_privilege_statements,
    verify_database_privileges_sql,
    verify_membership_sql,
    verify_roles_sql,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    require_ok,
    sealed_postgres_env,
)
from ticketbox_lifecycle.runtime.durable_files import durable_write_text
from ticketbox_lifecycle.runtime.postgres_connection import run_psql
from ticketbox_lifecycle.runtime.windows_postgres_identity import (
    read_system_identifier,
    require_running_ticketbox_cluster,
)
from ticketbox_lifecycle.runtime.windows_security_native import (
    reject_reparse_components,
)
from ticketbox_lifecycle.runtime.windows_services import (
    scm_query_state,
    service_running,
    start_service,
)
from ticketbox_lifecycle.schemas import InstallRequest

_PG_HBA = """\
# Ticketbox fresh-install localhost SCRAM only.
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
"""


class WindowsPostgresAdapter:
    name = "postgres"

    def __init__(self, runner: CommandRunner, security: SecurityAdapter) -> None:
        self._runner = runner
        self._security = security

    def apply(self, request: InstallRequest, step: str) -> str:
        if step == "postgres_initdb":
            return self._initdb(request)
        if step == "start_postgres":
            return self._start(request)
        if step == "roles_database":
            return self._roles(request)
        raise LifecycleViolation("wrong_adapter", f"postgres adapter does not own {step}")

    def verify(self, request: InstallRequest, step: str) -> None:
        if step == "postgres_initdb":
            data = layout.pgdata(request)
            _require_complete_pgdata(data, request.postgres_major)
            _require_ticketbox_cluster_config(request)
            if service_running(self._runner, request.pg_service_name):
                require_running_ticketbox_cluster(self._runner, request)
            else:
                read_system_identifier(self._runner, request)
            return
        if step == "start_postgres":
            self._require_ready(request)
            return
        if step == "roles_database":
            self._require_ready(request)
            completed = run_psql(self._runner, request, verify_roles_sql(), database="postgres")
            if completed.returncode != 0 or expected_roles_probe() not in completed.stdout.replace("\r\n", "\n"):
                raise LifecycleError("postcondition_missing", "PostgreSQL three-role probe failed")
            membership = run_psql(self._runner, request, verify_membership_sql(), database="postgres")
            if (
                membership.returncode != 0
                or expected_membership_probe() not in membership.stdout.replace("\r\n", "\n")
            ):
                raise LifecycleError("postcondition_missing", "ticketbox_migrator cannot SET ROLE owner")
            privileges = run_psql(
                self._runner,
                request,
                verify_database_privileges_sql(),
                database=DATABASE_NAME,
            )
            if privileges.returncode != 0 or privileges.stdout.strip() != "true":
                raise LifecycleError(
                    "postcondition_missing",
                    "Ticketbox database and default privileges are incomplete",
                )
            return
        raise LifecycleViolation("wrong_adapter", f"postgres adapter does not own {step}")

    def _initdb(self, request: InstallRequest) -> str:
        data = layout.pgdata(request)
        reject_reparse_components(data)
        if _postgresql_cluster_complete(data, request.postgres_major):
            if service_running(self._runner, request.pg_service_name):
                _require_complete_pgdata(data, request.postgres_major)
                _require_ticketbox_cluster_config(request)
                require_running_ticketbox_cluster(self._runner, request)
                return "already-present"
            self._security.prepare_initdb_directory(request)
            _require_complete_pgdata(data, request.postgres_major)
            self._security.discard_initdb_password_file(request)
            _write_cluster_config(request)
            return "already-present"
        _discard_incomplete_pgdata(data, request.postgres_major)
        self._security.prepare_initdb_directory(request)
        initdb = layout.tool(request, "initdb.exe")
        if not initdb.is_file():
            raise LifecycleError("missing_platform_binary", "postgresql/bin/initdb.exe is not installed")
        primary_failure: LifecycleError | None = None
        try:
            pwfile = self._security.materialize_initdb_password_file(request)
            argv = [
                str(initdb),
                "-D",
                str(data),
                "-U",
                "postgres",
                "--pwfile",
                str(pwfile),
                "--auth=scram-sha-256",
                "--data-checksums",
                "-E",
                "UTF8",
                "--locale=C",
            ]
            if "--no-sync" in argv:
                raise LifecycleViolation("unsafe_initdb", "initdb --no-sync is forbidden")
            require_ok(
                self._runner.run(argv, env=sealed_postgres_env(), timeout_s=180),
                code="initdb_failed",
            )
        except Exception as exc:
            if isinstance(exc, LifecycleError):
                primary_failure = exc
                raise
            primary_failure = LifecycleError(
                "initdb_platform_failure",
                f"initdb platform boundary failed: {exc}",
            )
            raise primary_failure from exc
        finally:
            try:
                self._security.discard_initdb_password_file(request)
            except LifecycleError as cleanup_failure:
                if primary_failure is None:
                    raise
                raise LifecycleError(
                    primary_failure.code,
                    f"{primary_failure.message}; cleanup failed "
                    f"({cleanup_failure.code}): {cleanup_failure.message}",
                ) from cleanup_failure
        _require_complete_pgdata(data, request.postgres_major)
        _write_cluster_config(request)
        return "initialized"

    def _start(self, request: InstallRequest) -> str:
        start_service(self._runner, request.pg_service_name, code="pg_start_failed")
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                self._require_ready(request)
                return "started"
            except LifecycleError as exc:
                if exc.code in {
                    "postgres_cluster_mismatch",
                    "postgres_checksums_disabled",
                    "pg_controldata_failed",
                    "missing_platform_binary",
                }:
                    raise
                if scm_query_state(self._runner, request.pg_service_name) == "STOPPED":
                    raise LifecycleError(
                        "postgres_not_ready",
                        _postgres_not_ready_message(request, stopped=True),
                    ) from None
                time.sleep(1)
        raise LifecycleError("postgres_not_ready", _postgres_not_ready_message(request, stopped=False))

    def _roles(self, request: InstallRequest) -> str:
        self._require_ready(request)
        migrator_password = layout.migrator_password_file(request).read_text(encoding="utf-8").strip()
        runtime_password = layout.runtime_password_file(request).read_text(encoding="utf-8").strip()
        for sql in provision_statements(
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        ):
            completed = run_psql(self._runner, request, sql, database="postgres")
            if completed.returncode != 0:
                raise LifecycleError(
                    "create_role_failed",
                    "PostgreSQL role provisioning failed",
                )
        probe = run_psql(self._runner, request, database_exists_sql(), database="postgres")
        if probe.returncode != 0 or "1" not in probe.stdout:
            require_ok(
                run_psql(self._runner, request, create_database_sql(), database="postgres"),
                code="create_database_failed",
            )
        for sql in database_connect_statements():
            require_ok(
                run_psql(self._runner, request, sql, database="postgres"),
                code="database_privilege_failed",
            )
        for sql in schema_privilege_statements():
            require_ok(
                run_psql(self._runner, request, sql, database=DATABASE_NAME),
                code="schema_privilege_failed",
            )
        require_ok(
            run_psql(
                self._runner,
                request,
                "SELECT current_user",
                database=DATABASE_NAME,
                user=MIGRATOR_ROLE,
            ),
            code="migrator_role_connect_failed",
        )
        require_ok(
            run_psql(
                self._runner,
                request,
                "SELECT current_user",
                database=DATABASE_NAME,
                user=RUNTIME_ROLE,
            ),
            code="runtime_role_connect_failed",
        )
        return "roles-ready"

    def _require_ready(self, request: InstallRequest) -> None:
        require_running_ticketbox_cluster(self._runner, request)




def _postgres_log_excerpt(request: InstallRequest) -> str:
    log_dir = layout.pgdata(request) / "log"
    if not log_dir.is_dir():
        return ""
    files = sorted(log_dir.glob("postgresql*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return ""
    lines = [line for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    return "\n".join(lines[-20:])


def _postgres_not_ready_message(request: InstallRequest, *, stopped: bool) -> str:
    prefix = (
        "PostgreSQL service reached STOPPED before ready"
        if stopped
        else "PostgreSQL did not become ready"
    )
    excerpt = _postgres_log_excerpt(request)
    if excerpt:
        return f"{prefix}: {excerpt}"
    return prefix


def _postgresql_cluster_complete(data: Path, postgres_major: int) -> bool:
    # A successful initdb owns this whole shape. PG_VERSION alone is written
    # before the control file and WAL directories are durable.
    try:
        version = (data / "PG_VERSION").read_text(encoding="ascii").strip()
        control_size = (data / "global" / "pg_control").stat().st_size
    except (OSError, UnicodeError):
        return False
    return (
        version == str(postgres_major)
        and control_size > 0
        and (data / "postgresql.conf").is_file()
        and (data / "pg_hba.conf").is_file()
        and (data / "base").is_dir()
        and (data / "global").is_dir()
        and (data / "pg_wal").is_dir()
    )


def _require_complete_pgdata(data: Path, postgres_major: int) -> None:
    for path in (
        data,
        data / "PG_VERSION",
        data / "postgresql.conf",
        data / "pg_hba.conf",
        data / "base",
        data / "global",
        data / "global" / "pg_control",
        data / "pg_wal",
    ):
        reject_reparse_components(path)
    if not _postgresql_cluster_complete(data, postgres_major):
        raise LifecycleError("postcondition_missing", "pgdata is not a complete PostgreSQL cluster")


def _discard_incomplete_pgdata(data: Path, postgres_major: int) -> None:
    if not data.exists() or _postgresql_cluster_complete(data, postgres_major):
        return
    try:
        if data.is_dir():
            if any(data.iterdir()):
                shutil.rmtree(data)
            return
        data.unlink()
    except OSError as exc:
        raise LifecycleError(
            "incomplete_pgdata",
            "incomplete PostgreSQL cluster could not be discarded for initdb retry",
        ) from exc


def _write_cluster_config(request: InstallRequest) -> None:
    conf = layout.pgdata(request) / "postgresql.conf"
    current = conf.read_text(encoding="utf-8") if conf.is_file() else ""
    owned = {"listen_addresses", "port", "password_encryption", "logging_collector"}
    retained: list[str] = []
    for line in current.splitlines():
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if stripped and not stripped.startswith("#") and key in owned:
            continue
        retained.append(line)
    retained.extend(
        [
            "",
            "# Ticketbox fresh-install settings.",
            "listen_addresses = '127.0.0.1'",
            f"port = {request.pg_port}",
            "password_encryption = scram-sha-256",
            "logging_collector = on",
        ]
    )
    durable_write_text(conf, "\n".join(retained).rstrip() + "\n")
    durable_write_text(layout.pgdata(request) / "pg_hba.conf", _PG_HBA)


def _require_ticketbox_cluster_config(request: InstallRequest) -> None:
    data = layout.pgdata(request)
    expected = {
        "listen_addresses": "'127.0.0.1'",
        "port": str(request.pg_port),
        "password_encryption": "scram-sha-256",
        "logging_collector": "on",
    }
    try:
        active: dict[str, list[str]] = {key: [] for key in expected}
        for line in (data / "postgresql.conf").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = (part.strip() for part in stripped.split("=", 1))
            if key in active:
                active[key].append(value)
        hba = (data / "pg_hba.conf").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LifecycleError(
            "postcondition_missing",
            "Ticketbox PostgreSQL configuration is unreadable",
        ) from exc
    if any(active[key] != [value] for key, value in expected.items()) or hba != _PG_HBA:
        raise LifecycleError(
            "postcondition_missing",
            "Ticketbox PostgreSQL configuration is incomplete",
        )
