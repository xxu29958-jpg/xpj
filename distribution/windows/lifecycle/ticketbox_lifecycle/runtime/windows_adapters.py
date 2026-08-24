from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

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
    verify_alembic_version_sql,
    schema_privilege_statements,
    verify_membership_sql,
    verify_roles_sql,
)
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    CompletedCommand,
    SubprocessCommandRunner,
    require_ok,
    sealed_pg_env,
)
from ticketbox_lifecycle.schemas import InstallRequest

_INSTALLATION_ID_NAMESPACE = b"ticketbox-installation-v1\0"
_CLUSTER_SECRET_NAMES = frozenset(
    {
        "postgres.password",
        "postgres.pwfile",
        "pgpass",
        "ticketbox_migrator.password",
        "ticketbox_runtime.password",
    }
)
_BACKEND_SECRET_NAMES = frozenset({"backend.env"})
_PG_HBA = """\
# Ticketbox fresh-install localhost SCRAM only.
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
"""


class _FilesAdapter:
    name = "files"

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "programdata_root":
            raise LifecycleViolation("wrong_adapter", "files adapter only owns programdata_root")
        for path in (
            Path(request.program_data_root),
            Path(request.data_root),
            layout.machine_root(request),
            Path(request.program_data_root) / "logs",
            layout.secrets_dir(request),
            layout.originals(request),
        ):
            path.mkdir(parents=True, exist_ok=True)
        _ensure_credentials(request)
        return "created"

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "programdata_root":
            raise LifecycleViolation("wrong_adapter", "files adapter only owns programdata_root")
        required = (
            Path(request.program_data_root),
            Path(request.data_root),
            layout.machine_root(request),
            layout.secrets_dir(request),
            layout.postgres_pwfile(request),
            layout.pg_passfile(request),
            layout.backend_env_file(request),
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise LifecycleError("postcondition_missing", "ProgramData layout is incomplete")


class _SecurityAdapter:
    name = "security"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "acl":
            raise LifecycleViolation("wrong_adapter", "security adapter only owns acl")
        _require_windows()
        elevated_sid = _current_user_sid(self._runner)
        grants = [
            f"*{elevated_sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ]
        interactive_sid = _shell_user_sid()
        if interactive_sid and interactive_sid != elevated_sid:
            grants.append(f"*{interactive_sid}:(OI)(CI)RX")
        for path in (request.program_data_root, request.data_root):
            require_ok(
                self._runner.run(
                    [
                        "icacls",
                        path,
                        "/inheritance:r",
                        "/grant:r",
                        *grants,
                    ]
                ),
                code="acl_apply_failed",
            )
        secrets_root = layout.secrets_dir(request)
        if secrets_root.is_dir():
            for secret in sorted(path for path in secrets_root.iterdir() if path.is_file()):
                _protect_lifecycle_secret(self._runner, secret)
        return "acl-applied"

    def grant_backend_binding_read(self, binding_path: Path, service_name: str) -> None:
        _require_windows()
        machine = binding_path.parent
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    str(machine),
                    "/grant",
                    f"NT SERVICE\\{service_name}:(RX)",
                ]
            ),
            code="binding_dir_acl_failed",
        )
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    str(binding_path),
                    "/grant",
                    f"NT SERVICE\\{service_name}:(R)",
                ]
            ),
            code="binding_acl_failed",
        )
        interactive_sid = _shell_user_sid()
        if interactive_sid:
            require_ok(
                self._runner.run(
                    [
                        "icacls",
                        str(machine),
                        "/grant",
                        f"*{interactive_sid}:(RX)",
                    ]
                ),
                code="binding_dir_acl_failed",
            )
            require_ok(
                self._runner.run(
                    [
                        "icacls",
                        str(binding_path),
                        "/grant",
                        f"*{interactive_sid}:(R)",
                    ]
                ),
                code="binding_acl_failed",
            )

    def grant_backend_env_read(self, request: InstallRequest) -> None:
        _grant_backend_env_read(self._runner, request)

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "acl":
            raise LifecycleViolation("wrong_adapter", "security adapter only owns acl")
        _require_windows()
        completed = self._runner.run(["icacls", request.data_root])
        if completed.returncode != 0:
            raise LifecycleError("acl_verify_failed", "icacls could not read DataRoot")
        secrets_root = layout.secrets_dir(request)
        secret_files = sorted(path for path in secrets_root.iterdir() if path.is_file()) if secrets_root.is_dir() else []
        if not secret_files:
            raise LifecycleError("postcondition_missing", "lifecycle secrets are absent")
        for secret in secret_files:
            observed = self._runner.run(["icacls", str(secret)])
            text = f"{observed.stdout}\n{observed.stderr}"
            upper = text.upper()
            if observed.returncode != 0 or "(I)" in upper:
                raise LifecycleError(
                    "postcondition_missing",
                    "secret ACL is still inherited",
                )
            if "BUILTIN\\USERS" in upper or "NT AUTHORITY\\AUTHENTICATED USERS" in upper:
                raise LifecycleError("secret_acl_too_broad", "secret is readable by ordinary users")
            backend = f"NT SERVICE\\{request.backend_service_name}".upper()
            if secret.name in _CLUSTER_SECRET_NAMES and backend in upper:
                raise LifecycleError("secret_acl_leaked_backend", f"{secret.name} grants TicketboxBackend")
            if secret.name in _BACKEND_SECRET_NAMES and backend not in upper:
                # Bearer grant happens after SCM creates the service SID.
                continue


class _PostgresAdapter:
    name = "postgres"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

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
            if not (layout.pgdata(request) / "PG_VERSION").is_file():
                raise LifecycleError("postcondition_missing", "pgdata has no PG_VERSION")
            return
        if step == "start_postgres":
            self._require_ready(request)
            return
        if step == "roles_database":
            completed = self._psql(request, verify_roles_sql(), database="postgres")
            if completed.returncode != 0 or expected_roles_probe() not in completed.stdout.replace("\r\n", "\n"):
                raise LifecycleError("postcondition_missing", "PostgreSQL three-role probe failed")
            membership = self._psql(request, verify_membership_sql(), database="postgres")
            if (
                membership.returncode != 0
                or expected_membership_probe() not in membership.stdout.replace("\r\n", "\n")
            ):
                raise LifecycleError("postcondition_missing", "ticketbox_migrator cannot SET ROLE owner")
            return
        raise LifecycleViolation("wrong_adapter", f"postgres adapter does not own {step}")

    def _initdb(self, request: InstallRequest) -> str:
        data = layout.pgdata(request)
        if (data / "PG_VERSION").is_file():
            return "already-present"
        initdb = layout.tool(request, "initdb.exe")
        if not initdb.is_file():
            raise LifecycleError("missing_platform_binary", "postgresql/bin/initdb.exe is not installed")
        argv = [
            str(initdb),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--pwfile",
            str(layout.postgres_pwfile(request)),
            "--auth=scram-sha-256",
            "--data-checksums",
            "-E",
            "UTF8",
            "--locale=C",
        ]
        if "--no-sync" in argv:
            raise LifecycleViolation("unsafe_initdb", "initdb --no-sync is forbidden")
        require_ok(self._runner.run(argv, timeout_s=180), code="initdb_failed")
        _write_cluster_config(request)
        return "initialized"

    def _start(self, request: InstallRequest) -> str:
        _start_service(self._runner, request.pg_service_name, code="pg_start_failed")
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                self._require_ready(request)
                return "started"
            except LifecycleError:
                if _scm_query_state(self._runner, request.pg_service_name) == "STOPPED":
                    raise LifecycleError(
                        "postgres_not_ready",
                        _postgres_not_ready_message(request, stopped=True),
                    ) from None
                time.sleep(1)
        raise LifecycleError("postgres_not_ready", _postgres_not_ready_message(request, stopped=False))

    def _roles(self, request: InstallRequest) -> str:
        migrator_password = layout.migrator_password_file(request).read_text(encoding="utf-8").strip()
        runtime_password = layout.runtime_password_file(request).read_text(encoding="utf-8").strip()
        for sql in provision_statements(
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        ):
            require_ok(
                self._psql(request, sql, database="postgres"),
                code="create_role_failed",
            )
        probe = self._psql(request, database_exists_sql(), database="postgres")
        if probe.returncode != 0 or "1" not in probe.stdout:
            require_ok(
                self._psql(request, create_database_sql(), database="postgres"),
                code="create_database_failed",
            )
        for sql in database_connect_statements():
            require_ok(
                self._psql(request, sql, database="postgres"),
                code="database_privilege_failed",
            )
        for sql in schema_privilege_statements():
            require_ok(
                self._psql(request, sql, database=DATABASE_NAME),
                code="schema_privilege_failed",
            )
        require_ok(
            self._psql(
                request,
                "SELECT current_user",
                database=DATABASE_NAME,
                user=MIGRATOR_ROLE,
            ),
            code="migrator_role_connect_failed",
        )
        require_ok(
            self._psql(
                request,
                "SELECT current_user",
                database=DATABASE_NAME,
                user=RUNTIME_ROLE,
            ),
            code="runtime_role_connect_failed",
        )
        return "roles-ready"

    def _require_ready(self, request: InstallRequest) -> None:
        ready = layout.tool(request, "pg_isready.exe")
        require_ok(
            self._runner.run(
                [str(ready), "-h", "127.0.0.1", "-p", str(request.pg_port), "-d", "postgres"],
                env=sealed_pg_env(str(layout.pg_passfile(request))),
            ),
            code="postgres_not_ready",
        )

    def _psql(
        self,
        request: InstallRequest,
        sql: str,
        *,
        database: str,
        user: str = "postgres",
    ) -> CompletedCommand:
        psql = layout.tool(request, "psql.exe")
        return self._runner.run(
            [
                str(psql),
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                "127.0.0.1",
                "-p",
                str(request.pg_port),
                "-U",
                user,
                "-d",
                database,
                "-tA",
                "-f",
                "-",
            ],
            env=sealed_pg_env(str(layout.pg_passfile(request))),
            input_text=sql,
        )


class _AlembicAdapter:
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
        url = _maintenance_database_url(request)
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
                MIGRATOR_ROLE,
                "-d",
                DATABASE_NAME,
                "-tA",
                "-c",
                verify_alembic_version_sql(),
            ],
            env=sealed_pg_env(str(layout.pg_passfile(request))),
        )
        if completed.returncode != 0 or request.schema_revision not in completed.stdout:
            raise LifecycleError("postcondition_missing", "alembic_version is not the exact release target")


class _ScmAdapter:
    name = "scm"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def apply(self, request: InstallRequest, step: str) -> str:
        if step == "scm":
            return self._register(request)
        if step == "start_services":
            return self._start_backend(request)
        raise LifecycleViolation("wrong_adapter", f"scm adapter does not own {step}")

    def verify(self, request: InstallRequest, step: str) -> None:
        if step == "scm":
            self._require_service(request.pg_service_name)
            self._require_service(request.backend_service_name)
            _require_pgdata_exclusive_acl(self._runner, request)
            _require_backend_env_bearer(self._runner, request)
            return
        if step == "start_services":
            self._require_running(request.backend_service_name)
            return
        raise LifecycleViolation("wrong_adapter", f"scm adapter does not own {step}")

    def _register(self, request: InstallRequest) -> str:
        pg_ctl = layout.tool(request, "pg_ctl.exe")
        if not pg_ctl.is_file():
            raise LifecycleError("missing_platform_binary", "postgresql/bin/pg_ctl.exe is not installed")
        self._refuse_foreign_service(
            request.pg_service_name,
            _path_fragment(pg_ctl),
            _path_fragment(layout.pgdata(request)),
        )
        if not self._service_exists(request.pg_service_name):
            require_ok(
                self._runner.run(
                    [
                        str(pg_ctl),
                        "register",
                        "-N",
                        request.pg_service_name,
                        "-U",
                        "NT AUTHORITY\\LocalService",
                        "-D",
                        str(layout.pgdata(request)),
                        "-S",
                        "auto",
                    ]
                ),
                code="pg_register_failed",
            )
        self._set_identity(request.pg_service_name)
        shawl = layout.shawl_exe(request)
        launcher = layout.launcher_exe(request)
        if not shawl.is_file() or not launcher.is_file():
            raise LifecycleError("missing_platform_binary", "shawl.exe or TicketboxBackendLauncher.exe is missing")
        self._refuse_foreign_service(
            request.backend_service_name,
            _path_fragment(launcher),
            request.backend_service_name.lower(),
        )
        if not self._service_exists(request.backend_service_name):
            require_ok(
                self._runner.run(
                    [
                        str(shawl),
                        "add",
                        "--name",
                        request.backend_service_name,
                        "--cwd",
                        _win32_service_path(launcher.parent),
                        "--",
                        _win32_service_path(launcher),
                    ]
                ),
                code="backend_register_failed",
            )
        self._set_identity(request.backend_service_name)
        require_ok(
            self._runner.run(
                [
                    "sc.exe",
                    "config",
                    request.backend_service_name,
                    "depend=",
                    request.pg_service_name,
                ]
            ),
            code="backend_depend_failed",
        )
        _require_windows()
        require_ok(
            self._runner.run(
                [
                    "icacls",
                    request.data_root,
                    "/T",
                    "/grant",
                    f"NT SERVICE\\{request.backend_service_name}:(OI)(CI)M",
                ]
            ),
            code="data_root_backend_acl_failed",
        )
        _seal_pgdata_acl(self._runner, request)
        _grant_backend_env_read(self._runner, request)
        return "registered"

    def _start_backend(self, request: InstallRequest) -> str:
        _start_service(self._runner, request.backend_service_name, code="backend_start_failed")
        deadline = time.time() + 60
        while time.time() < deadline:
            if self._is_running(request.backend_service_name):
                return "started"
            time.sleep(1)
        raise LifecycleError("backend_not_running", "TicketboxBackend did not reach RUNNING")

    def _refuse_foreign_service(self, name: str, *expected_fragments: str) -> None:
        if not self._service_exists(name):
            return
        completed = self._runner.run(["sc.exe", "qc", name])
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        missing = [
            fragment
            for fragment in expected_fragments
            if fragment and fragment.lower() not in text
        ]
        if completed.returncode != 0 or missing:
            raise LifecycleViolation(
                "scm_collision",
                f"service {name} exists with a foreign ImagePath",
            )

    def _set_identity(self, name: str) -> None:
        require_ok(
            self._runner.run(
                ["sc.exe", "config", name, "obj=", "NT AUTHORITY\\LocalService", "password=", ""]
            ),
            code="service_logon_failed",
        )
        require_ok(
            self._runner.run(["sc.exe", "sidtype", name, "unrestricted"]),
            code="service_sid_failed",
        )
        require_ok(
            self._runner.run(["sc.exe", "config", name, "start=", "auto"]),
            code="service_start_type_failed",
        )
        require_ok(
            self._runner.run(
                [
                    "sc.exe",
                    "failure",
                    name,
                    "reset=",
                    "3600",
                    "actions=",
                    "restart/5000/restart/10000/restart/60000",
                ]
            ),
            code="service_recovery_failed",
        )

    def _service_exists(self, name: str) -> bool:
        completed = self._runner.run(["sc.exe", "query", name])
        return completed.returncode == 0

    def _require_service(self, name: str) -> None:
        if not self._service_exists(name):
            raise LifecycleError("postcondition_missing", f"service {name} is not registered")

    def _is_running(self, name: str) -> bool:
        completed = self._runner.run(["sc.exe", "query", name])
        return completed.returncode == 0 and "RUNNING" in completed.stdout.upper()

    def _require_running(self, name: str) -> None:
        if not self._is_running(name):
            raise LifecycleError("postcondition_missing", f"service {name} is not RUNNING")


class _DatasetAdapter:
    name = "dataset"

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

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
        expected_id = _installation_id_for_app_data(Path(request.data_root) / "app")
        if payload.get("installation_id") != expected_id:
            raise LifecycleError(
                "health_identity_mismatch",
                "installation health identity does not match this DataRoot",
            )
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


class WindowsAdapterBundle:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        command_runner = runner or SubprocessCommandRunner()
        self.files = _FilesAdapter()
        self.security = _SecurityAdapter(command_runner)
        self.postgres = _PostgresAdapter(command_runner)
        self.alembic = _AlembicAdapter(command_runner)
        self.scm = _ScmAdapter(command_runner)
        self.dataset = _DatasetAdapter(command_runner)


def _require_windows() -> None:
    if os.name != "nt":
        raise LifecycleError("not_windows", "TicketboxLifecycle.exe only mutates a Windows host")


def _installation_id_for_app_data(app_data: Path) -> str:
    canonical = os.path.normcase(str(app_data.resolve())).encode("utf-8")
    digest = hashlib.sha256(_INSTALLATION_ID_NAMESPACE + canonical).hexdigest()
    return f"ticketbox-{digest[:32]}"


def _current_user_sid(runner: CommandRunner) -> str:
    completed = runner.run(["whoami", "/user"])
    require_ok(completed, code="whoami_failed")
    for token in completed.stdout.replace(",", " ").replace('"', " ").split():
        if token.startswith("S-1-") and token.count("-") >= 3:
            return token
    raise LifecycleError("whoami_failed", "whoami /user did not return a SID")


def _protect_lifecycle_secret(runner: CommandRunner, path: Path) -> None:
    # Elevated CreateFile owners are often Administrators; the frozen helper
    # requires owner == current process SID and an exact protected DACL.
    require_ok(runner.run(["takeown", "/F", str(path)]), code="secret_owner_failed")
    user_sid = _current_user_sid(runner)
    require_ok(
        runner.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{user_sid}:(F)",
                "*S-1-5-18:(F)",
                "*S-1-5-32-544:(F)",
            ]
        ),
        code="secret_acl_failed",
    )


def _grant_backend_env_read(runner: CommandRunner, request: InstallRequest) -> None:
    require_ok(
        runner.run(
            [
                "icacls",
                str(layout.backend_env_file(request)),
                "/grant",
                f"NT SERVICE\\{request.backend_service_name}:(R)",
            ]
        ),
        code="backend_env_acl_failed",
    )


def _require_backend_env_bearer(runner: CommandRunner, request: InstallRequest) -> None:
    env_path = layout.backend_env_file(request)
    completed = runner.run(["icacls", str(env_path)])
    text = f"{completed.stdout}\n{completed.stderr}".upper()
    if completed.returncode != 0:
        raise LifecycleError("backend_env_acl_verify_failed", "icacls could not read backend.env")
    if f"NT SERVICE\\{request.backend_service_name}".upper() not in text:
        raise LifecycleError("backend_env_acl_missing_backend", "backend.env is not readable by TicketboxBackend")
    for name in _CLUSTER_SECRET_NAMES:
        secret = layout.secrets_dir(request) / name
        if not secret.is_file():
            continue
        observed = runner.run(["icacls", str(secret)])
        observed_text = f"{observed.stdout}\n{observed.stderr}".upper()
        if f"NT SERVICE\\{request.backend_service_name}".upper() in observed_text:
            raise LifecycleError("secret_acl_leaked_backend", f"{name} grants TicketboxBackend")


def _ensure_credentials(request: InstallRequest) -> None:
    secrets_root = layout.secrets_dir(request)
    secrets_root.mkdir(parents=True, exist_ok=True)
    postgres_password = _read_or_create_secret(layout.postgres_password_file(request))
    migrator_password = _read_or_create_secret(layout.migrator_password_file(request))
    runtime_password = _read_or_create_secret(layout.runtime_password_file(request))
    layout.postgres_pwfile(request).write_text(postgres_password + "\n", encoding="utf-8")
    pass_lines = [
        f"127.0.0.1:{request.pg_port}:*:postgres:{postgres_password}",
        f"127.0.0.1:{request.pg_port}:{DATABASE_NAME}:{MIGRATOR_ROLE}:{migrator_password}",
        f"127.0.0.1:{request.pg_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{runtime_password}",
        f"localhost:{request.pg_port}:*:postgres:{postgres_password}",
        f"localhost:{request.pg_port}:{DATABASE_NAME}:{MIGRATOR_ROLE}:{migrator_password}",
        f"localhost:{request.pg_port}:{DATABASE_NAME}:{RUNTIME_ROLE}:{runtime_password}",
    ]
    layout.pg_passfile(request).write_text("\n".join(pass_lines) + "\n", encoding="utf-8")
    env_path = layout.backend_env_file(request)
    app_dir = Path(request.data_root) / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    env_text = "\n".join(
        [
            f"DATABASE_URL={_app_database_url(request)}",
            f"TICKETBOX_DATA_DIR={app_dir}",
            f"HTTP_BOOTSTRAP_SECRET={secrets.token_urlsafe(32)}",
        ]
    ) + "\n"
    if not env_path.is_file():
        env_path.write_text(env_text, encoding="utf-8")


def _read_or_create_secret(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(32)
    path.write_text(value, encoding="utf-8")
    return value


def _app_database_url(request: InstallRequest) -> str:
    password = layout.runtime_password_file(request).read_text(encoding="utf-8").strip()
    return (
        f"postgresql+psycopg://{RUNTIME_ROLE}:{password}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )


def _maintenance_database_url(request: InstallRequest) -> str:
    return (
        f"postgresql+psycopg://{MIGRATOR_ROLE}@127.0.0.1:{request.pg_port}/{DATABASE_NAME}"
        "?require_auth=scram-sha-256"
    )


def _win32_service_path(path: Path) -> str:
    # CreateProcess lpCurrentDirectory rejects the \\?\ prefix (Win32).
    text = os.path.abspath(os.fspath(path))
    prefix = "\\\\?\\"
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def _path_fragment(path: Path) -> str:
    return _win32_service_path(path).replace("/", "\\").lower()


def _sid_string(advapi, kernel, token) -> str | None:
    import ctypes
    from ctypes import wintypes

    class TokenUser(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    get_info = advapi.GetTokenInformation
    get_info.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_info.restype = wintypes.BOOL
    convert = advapi.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    size = wintypes.DWORD()
    get_info(token, 1, None, 0, ctypes.byref(size))
    if size.value < ctypes.sizeof(TokenUser):
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not get_info(token, 1, buf, size.value, ctypes.byref(size)):
        return None
    sid = TokenUser.from_buffer(buf).Sid
    string_sid = wintypes.LPWSTR()
    if not convert(sid, ctypes.byref(string_sid)):
        return None
    result = string_sid.value
    kernel.LocalFree(string_sid)
    return result


def _linked_token_user_sid() -> str | None:
    # Official UAC split token: TokenLinkedToken on an elevated token is the
    # interactive filtered user (Win32 TOKEN_INFORMATION_CLASS).
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 19, None, 0, ctypes.byref(size))
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 19, buf, size.value, ctypes.byref(size)):
            return None
        linked = wintypes.HANDLE.from_buffer(buf).value
        if not linked:
            return None
        try:
            return _sid_string(advapi, kernel, linked)
        finally:
            kernel.CloseHandle(linked)
    finally:
        kernel.CloseHandle(token)


def _explorer_shell_user_sid() -> str | None:
    # Fallback: the shell window still belongs to the interactive session.
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = user32.GetShellWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            return None
        try:
            return _sid_string(advapi, kernel, token)
        finally:
            kernel.CloseHandle(token)
    finally:
        kernel.CloseHandle(handle)


def _shell_user_sid() -> str | None:
    if os.name != "nt":
        return None
    try:
        return _linked_token_user_sid() or _explorer_shell_user_sid()
    except Exception:
        return None


def _start_service(runner: CommandRunner, name: str, *, code: str) -> None:
    completed = runner.run(["sc.exe", "start", name])
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 0 or "1056" in combined or "already been started" in combined.lower():
        return
    require_ok(completed, code=code)


def service_registered(name: str) -> bool:
    if os.name != "nt":
        return False
    completed = SubprocessCommandRunner().run(["sc.exe", "query", name])
    return completed.returncode == 0


def _scm_query_state(runner: CommandRunner, name: str) -> str:
    completed = runner.run(["sc.exe", "query", name])
    text = f"{completed.stdout}\n{completed.stderr}".upper()
    for token in ("START_PENDING", "STOP_PENDING", "RUNNING", "STOPPED"):
        if token in text:
            return token
    return "UNKNOWN"


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


def _durable_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _seal_pgdata_acl(runner: CommandRunner, request: InstallRequest) -> None:
    pgdata = str(layout.pgdata(request))
    require_ok(
        runner.run(
            [
                "icacls",
                pgdata,
                "/T",
                "/C",
                "/remove:g",
                f"NT SERVICE\\{request.backend_service_name}",
            ]
        ),
        code="pgdata_acl_remove_backend_failed",
    )
    require_ok(
        runner.run(
            [
                "icacls",
                pgdata,
                "/inheritance:r",
                "/grant:r",
                "SYSTEM:(OI)(CI)F",
                "Administrators:(OI)(CI)F",
                f"NT SERVICE\\{request.pg_service_name}:(OI)(CI)F",
            ]
        ),
        code="pgdata_acl_failed",
    )


def _require_pgdata_exclusive_acl(runner: CommandRunner, request: InstallRequest) -> None:
    completed = runner.run(["icacls", str(layout.pgdata(request))])
    text = f"{completed.stdout}\n{completed.stderr}".upper()
    if completed.returncode != 0:
        raise LifecycleError("pgdata_acl_verify_failed", "icacls could not read pgdata")
    backend = f"NT SERVICE\\{request.backend_service_name}".upper()
    pg_service = f"NT SERVICE\\{request.pg_service_name}".upper()
    if backend in text:
        raise LifecycleError("pgdata_acl_leaked_backend", "pgdata grants TicketboxBackend")
    if pg_service not in text:
        raise LifecycleError("pgdata_acl_missing_pg", "pgdata missing TicketboxPg")


def _write_cluster_config(request: InstallRequest) -> None:
    conf = layout.pgdata(request) / "postgresql.conf"
    extra = (
        f"\nlisten_addresses = '127.0.0.1'\n"
        f"port = {request.pg_port}\n"
        "password_encryption = scram-sha-256\n"
        "logging_collector = on\n"
    )
    current = conf.read_text(encoding="utf-8") if conf.is_file() else ""
    if "listen_addresses = '127.0.0.1'" not in current:
        current = current + extra
    _durable_write_text(conf, current)
    _durable_write_text(layout.pgdata(request) / "pg_hba.conf", _PG_HBA)
