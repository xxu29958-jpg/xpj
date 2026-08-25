from __future__ import annotations

import ast
import json
import os
import stat
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    expected_membership_probe,
    expected_roles_probe,
    verify_alembic_version_sql,
)
from ticketbox_lifecycle.policy.windows_scm_contract import (
    SERVICE_AUTO_START,
    expected_backend_service,
    expected_pg_service,
)
from ticketbox_lifecycle.runtime import (
    windows_file_security,
    windows_pgdata_security,
    windows_postgres,
    windows_security_native,
)
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.runtime.windows_scm_observation import (
    FailureAction,
    ServiceConfiguration,
)
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

_BACKEND_SERVICE_SID = "S-1-5-80-111-222-333-444-555"
_SHELL_USER_SID = "S-1-5-21-9-9-9-1002"
_PROCESS_USER_SID = "S-1-5-21-9-9-9-1003"


class _HealthResponse:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _stub_direct_health(monkeypatch, payload: dict[str, object]) -> None:
    def build_opener(handler):
        assert isinstance(handler, urllib.request.ProxyHandler)
        assert handler.proxies == {}
        return SimpleNamespace(open=lambda *_args, **_kwargs: _HealthResponse(payload))

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)


def test_windows_adapters_is_only_the_explicit_composition_root() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "lifecycle"
        / "ticketbox_lifecycle"
        / "runtime"
        / "windows_adapters.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [node.name for node in classes] == ["WindowsAdapterBundle"]
    assert [node.name for node in classes[0].body if isinstance(node, ast.FunctionDef)] == [
        "__init__"
    ]
    assert functions == []
    for responsibility in (
        "windows_alembic",
        "windows_dataset",
        "windows_file_security",
        "windows_files",
        "windows_postgres",
        "windows_scm",
        "windows_security",
    ):
        assert f"ticketbox_lifecycle.runtime.{responsibility}" in source


@pytest.fixture(autouse=True)
def _trusted_unit_file_owner(monkeypatch):
    monkeypatch.setattr(windows_security_native, "file_owner_sid", lambda _path: "S-1-5-32-544")
    monkeypatch.setattr(windows_security_native, "shell_user_sid", lambda: _SHELL_USER_SID)
    monkeypatch.setattr(
        windows_security_native,
        "current_process_user_sid",
        lambda: _PROCESS_USER_SID,
        raising=False,
    )

    def create_unit_directory(path: Path, **_kwargs) -> None:
        path.mkdir()

    def require_unit_directory(path: Path, *, code: str, **_kwargs) -> None:
        windows_security_native.require_trusted_owner(
            path,
            code=code,
            message=f"untrusted lifecycle directory: {path}",
        )

    monkeypatch.setattr(
        windows_security_native,
        "create_protected_directory",
        create_unit_directory,
        raising=False,
    )
    monkeypatch.setattr(
        windows_security_native,
        "require_protected_directory",
        require_unit_directory,
        raising=False,
    )


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[dict[str, str] | None] = []
        self.inputs: list[str | None] = []
        self.services: set[str] = set()
        self.running_services: set[str] = set()
        self.image_paths: dict[str, str] = {}
        self.service_configurations: dict[str, ServiceConfiguration] = {}
        self.pg_system_identifier = "7400000000000000001"
        self.online_system_identifier = self.pg_system_identifier
        self.online_data_directory: str | None = None
        self.data_checksums = "on"
        self.initdb_pwfile_seen = False
        self.initdb_returncode = 0
        self.initdb_requires_precreated_pgdata = False
        self.pgdata_acl_extra_sid: str | None = None
        self.pgdata_bootstrap_access = True
        self.pgcontroldata_requires_bootstrap_access = False
        self.fail_password_sql = False
        self.owner_claim_failure_output: str | None = None

    def run(
        self,
        argv,
        *,
        env=None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> CompletedCommand:
        del timeout_s
        recorded = tuple(str(part) for part in argv)
        self.calls.append(recorded)
        self.envs.append(None if env is None else dict(env))
        self.inputs.append(input_text)
        return self._complete(recorded, self._sql_text(recorded, input_text))

    def _sql_text(self, recorded: tuple[str, ...], input_text: str | None) -> str:
        if input_text:
            return input_text
        if len(recorded) >= 2 and recorded[-2] == "-c":
            return recorded[-1]
        return ""

    def _complete(self, recorded: tuple[str, ...], sql_text: str) -> CompletedCommand:
        name = Path(recorded[0]).name.lower()
        if name == "initdb.exe":
            pwfile = Path(recorded[recorded.index("--pwfile") + 1])
            self.initdb_pwfile_seen = pwfile.is_file()
            data = Path(recorded[recorded.index("-D") + 1])
            if self.initdb_requires_precreated_pgdata and not data.is_dir():
                return CompletedCommand(
                    recorded,
                    1,
                    "",
                    "restricted initdb cannot create PGDATA through its protected parent",
                )
            if self.initdb_returncode != 0:
                return CompletedCommand(recorded, self.initdb_returncode, "", "initdb failed")
            _write_complete_cluster(data)
            return CompletedCommand(recorded, 0, "ok", "")
        if name == "pg_controldata.exe":
            if self.pgcontroldata_requires_bootstrap_access and not self.pgdata_bootstrap_access:
                return CompletedCommand(recorded, 1, "", "PGDATA access denied")
            return CompletedCommand(
                recorded,
                0,
                (
                    f"Database system identifier:           {self.pg_system_identifier}\n"
                    "Database cluster state:               shut down\n"
                ),
                "",
            )
        if name in {"pg_ctl.exe", "shawl.exe", "sc.exe"}:
            return self._complete_scm(name, recorded)
        if name == "psql.exe":
            return self._complete_psql(recorded, sql_text)
        if name == "ticketbox-database-maintenance.exe":
            if "--fresh-owner-claim" in recorded:
                if self.owner_claim_failure_output is not None:
                    return CompletedCommand(
                        recorded,
                        1,
                        self.owner_claim_failure_output,
                        "",
                    )
                return CompletedCommand(
                    recorded,
                    0,
                    (
                        '{"contract":"ticketbox-installation-owner-pairing-v1",'
                        '"operation_id":"11111111-1111-4111-8111-111111111111",'
                        '"installation_id":"11111111-1111-4111-8111-111111111111",'
                        '"account_name":"我","ledger_id":"default","ledger_name":"我的小票夹",'
                        '"device_name":"Windows 安装来源","pairing_code":"12345678",'
                        '"pairing_expires_at":"2026-08-25T12:00:00Z",'
                        '"pairing_derivation_index":0,"claim_generation":1}'
                    ),
                    "",
                )
            return CompletedCommand(recorded, 0, '{"result":"upgraded"}', "")
        if name == "whoami":
            return CompletedCommand(
                recorded,
                0,
                "User Name SID\n============= ===\nTBX-QUAL-01\\tbxqual S-1-5-21-1-2-3-1001\n",
                "",
            )
        if name == "icacls" and "/reset" in recorded:
            target = os.path.normcase(os.path.abspath(recorded[1]))
            if target.endswith(os.path.normcase(os.sep + "pgdata")):
                self.pgdata_acl_extra_sid = None
                self.pgdata_bootstrap_access = True
        if name == "icacls" and "/grant:r" in recorded:
            target = os.path.normcase(os.path.abspath(recorded[1]))
            if target.endswith(os.path.normcase(os.sep + "pgdata")):
                grants = " ".join(recorded).upper()
                if "S-1-5-80-" in grants:
                    self.pgdata_bootstrap_access = False
        if name == "icacls" and len(recorded) == 2:
            return self._complete_icacls(recorded)
        return CompletedCommand(recorded, 0, "ok", "")

    def _complete_scm(self, name: str, recorded: tuple[str, ...]) -> CompletedCommand:
        if name == "sc.exe" and recorded[1] == "showsid":
            return CompletedCommand(
                recorded,
                0,
                f"NAME: {recorded[2]}\nSERVICE SID: {_BACKEND_SERVICE_SID}\n",
                "",
            )
        if name == "pg_ctl.exe" and "register" in recorded:
            service = recorded[recorded.index("-N") + 1]
            self.services.add(service)
            self.image_paths[service] = " ".join(recorded)
            self.service_configurations[service] = _recorded_service_configuration(
                name=service,
                argv=(
                    recorded[0],
                    "runservice",
                    "-N",
                    service,
                    "-D",
                    recorded[recorded.index("-D") + 1],
                    "-w",
                ),
                start_type=3,
                dependencies=("RPCSS",),
                account_sid="S-1-5-19",
            )
            return CompletedCommand(recorded, 0, "", "")
        if name == "shawl.exe" and "add" in recorded:
            service = recorded[recorded.index("--name") + 1]
            self.services.add(service)
            self.image_paths[service] = " ".join(recorded)
            self.service_configurations[service] = _recorded_service_configuration(
                name=service,
                argv=(recorded[0], "run", *recorded[2:]),
                start_type=3,
                dependencies=(),
                account_sid="S-1-5-19",
            )
            return CompletedCommand(recorded, 0, "", "")
        if name == "sc.exe" and recorded[1] == "query":
            service = recorded[2]
            if service in self.services:
                state = "4  RUNNING" if service in self.running_services else "1  STOPPED"
                return CompletedCommand(recorded, 0, f"STATE              : {state}", "")
            return CompletedCommand(recorded, 1060, "specified service does not exist", "")
        if name == "sc.exe" and recorded[1] == "start":
            self.running_services.add(recorded[2])
            return CompletedCommand(recorded, 0, "STATE              : 2  START_PENDING", "")
        if name == "sc.exe" and recorded[1] == "qc":
            service = recorded[2]
            if service not in self.services:
                return CompletedCommand(recorded, 1060, "specified service does not exist", "")
            return CompletedCommand(
                recorded,
                0,
                f"BINARY_PATH_NAME   : {self.image_paths.get(service, 'unknown')}",
                "",
            )
        if name == "sc.exe" and recorded[1] == "config":
            service = recorded[2]
            current = self.service_configurations[service]
            if "start=" in recorded:
                start = recorded[recorded.index("start=") + 1]
                current = replace(current, start_type={"auto": 2, "demand": 3}[start])
            if "depend=" in recorded:
                dependency = recorded[recorded.index("depend=") + 1]
                current = replace(current, dependencies=tuple(dependency.split("/")))
            self.service_configurations[service] = current
        if name == "sc.exe" and recorded[1] == "sidtype":
            service = recorded[2]
            self.service_configurations[service] = replace(
                self.service_configurations[service],
                sid_type=1,
            )
        if name == "sc.exe" and recorded[1] == "failure":
            service = recorded[2]
            self.service_configurations[service] = replace(
                self.service_configurations[service],
                failure_reset_seconds=3600,
                failure_actions=(
                    FailureAction(1, 5000),
                    FailureAction(1, 10000),
                    FailureAction(1, 60000),
                ),
            )
        return CompletedCommand(recorded, 0, "ok", "")

    def _complete_psql(self, recorded: tuple[str, ...], sql_text: str) -> CompletedCommand:
        if self.fail_password_sql and "PASSWORD '" in sql_text:
            return CompletedCommand(recorded, 1, "", f"LINE 1: {sql_text}")
        if "pg_control_system()" in sql_text:
            data_directory = self.online_data_directory
            if data_directory is None:
                data_directory = next(
                    (
                        str(Path(call[call.index("-D") + 1]))
                        for call in self.calls
                        if Path(call[0]).name.lower() == "initdb.exe" and "-D" in call
                    ),
                    "C:/foreign-pgdata",
                )
            return CompletedCommand(
                recorded,
                0,
                f"{self.online_system_identifier}|{self.data_checksums}|{data_directory}\n",
                "",
            )
        if "ticketbox_privileges_ready" in sql_text:
            return CompletedCommand(recorded, 0, "true", "")
        if "datname = 'ticketbox'" in sql_text:
            created = any(
                (inp or "") and "CREATE DATABASE ticketbox OWNER ticketbox_owner" in inp
                for inp in self.inputs
            )
            return CompletedCommand(recorded, 0, "1\n" if created else "", "")
        probes = (
            ("dataset_id FROM dataset_authority", "22222222-2222-4222-8222-222222222222"),
            ("pg_auth_members", expected_membership_probe() + "\n"),
            ("rolname || ':'", expected_roles_probe() + "\n"),
            ("pg_roles", "1"),
            ("pg_database", "1"),
            ("alembic_version", "20260821_0001"),
        )
        for needle, stdout in probes:
            if needle in sql_text:
                return CompletedCommand(recorded, 0, stdout, "")
        return CompletedCommand(recorded, 0, "ok", "")

    def _complete_icacls(self, recorded: tuple[str, ...]) -> CompletedCommand:
        target = os.path.normcase(os.path.abspath(recorded[1]))
        if target.endswith(os.path.normcase(os.sep + "pgdata")):
            extra = (
                f"*{self.pgdata_acl_extra_sid}:(OI)(CI)(F)\n"
                if self.pgdata_acl_extra_sid
                else ""
            )
            return CompletedCommand(
                recorded,
                0,
                (
                    f"{recorded[1]} NT SERVICE\\TicketboxPg:(OI)(CI)(F)\n"
                    "*S-1-5-18:(OI)(CI)(F)\n"
                    "*S-1-5-32-544:(OI)(CI)(F)\n"
                    f"{extra}"
                ),
                "",
            )
        protected = any(
            call
            and (
                call[0].lower() == "takeown"
                or (call[0].lower() == "icacls" and "/inheritance:r" in call)
            )
            and any(os.path.normcase(os.path.abspath(part)) == target for part in call[1:])
            for call in self.calls
        )
        if not protected:
            return CompletedCommand(
                recorded,
                0,
                f"{recorded[1]} NT AUTHORITY\\SYSTEM:(I)(F)\nBUILTIN\\Users:(I)(RX)\n",
                "",
            )
        grants: list[str] = []
        for call in self.calls:
            if not call or call[0].lower() != "icacls":
                continue
            if not any(os.path.normcase(os.path.abspath(part)) == target for part in call[1:]):
                continue
            for part in call:
                if ":(" in part:
                    grants.append(part)
        rendered = "\n".join(grants) or "*S-1-5-18:(F)\n*S-1-5-32-544:(F)"
        return CompletedCommand(recorded, 0, f"{recorded[1]} {rendered}\n", "")


class RecordingFileSecurity:
    def protect_file(
        self,
        runner,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None:
        del code
        assert isinstance(runner, RecordingRunner)
        if os.name == "nt" and path.name == "postgres.pwfile":
            windows_file_security._apply_file_dacl(path, reader_sids, code="unit_file_acl")
        runner.run(["takeown", "/A", "/F", str(path)])
        runner.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{windows_security_native.SYSTEM_SID}:(F)",
                f"*{windows_security_native.ADMINISTRATORS_SID}:(F)",
                *(f"*{sid}:(R)" for sid in reader_sids),
            ]
        )


class RecordingScmObserver:
    def __init__(self, runner: RecordingRunner) -> None:
        self._runner = runner

    def observe(self, name: str) -> ServiceConfiguration:
        try:
            return self._runner.service_configurations[name]
        except KeyError as exc:
            raise LifecycleError("scm_query_failed", f"missing recorded service {name}") from exc


def _bundle(runner: RecordingRunner) -> WindowsAdapterBundle:
    return WindowsAdapterBundle(runner, RecordingFileSecurity(), RecordingScmObserver(runner))


def _recorded_service_configuration(
    *,
    name: str,
    argv: tuple[str, ...],
    start_type: int,
    dependencies: tuple[str, ...],
    account_sid: str,
) -> ServiceConfiguration:
    return ServiceConfiguration(
        service_type=0x10,
        start_type=start_type,
        error_control=1,
        argv=argv,
        load_order_group="",
        tag_id=0,
        dependencies=dependencies,
        account_sid=account_sid,
        display_name=name,
        sid_type=0,
        failure_reset_seconds=0,
        failure_actions=(),
        failure_reboot_message="",
        failure_command="",
        failure_actions_on_non_crash=False,
        delayed_auto_start=False,
        trigger_count=0,
    )


def _request(tmp_path: Path) -> InstallRequest:
    app_dir = tmp_path / "app"
    pg_bin = app_dir / "postgresql" / "bin"
    release = app_dir / "releases" / "1.2.0"
    backend = release / "backend"
    pg_bin.mkdir(parents=True)
    backend.mkdir(parents=True)
    (app_dir / "bin").mkdir()
    for name in ("initdb.exe", "pg_controldata.exe", "pg_ctl.exe", "psql.exe", "pg_isready.exe"):
        (pg_bin / name).write_text("fake", encoding="utf-8")
    (backend / "ticketbox-backend.exe").write_text("fake", encoding="utf-8")
    (backend / "ticketbox-database-maintenance.exe").write_text("fake", encoding="utf-8")
    (app_dir / "bin" / "shawl.exe").write_text("fake", encoding="utf-8")
    (release / "release-manifest.json").write_text(
        '{"max_schema_revision":"20260821_0001"}',
        encoding="utf-8",
    )
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        app_dir=str(app_dir),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="b" * 64,
        install_id="11111111-1111-4111-8111-111111111111",
        dataset_id="22222222-2222-4222-8222-222222222222",
        schema_revision="20260821_0001",
        schema_min_compatible="1.2.0",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )


def _argv_text(calls: list[tuple[str, ...]]) -> str:
    return "\n".join(" ".join(call) for call in calls)


def _write_complete_cluster(data: Path, *, major: int = 17) -> None:
    data.mkdir(parents=True, exist_ok=True)
    (data / "PG_VERSION").write_text(f"{major}\n", encoding="utf-8")
    (data / "postgresql.conf").write_text("# initdb\n", encoding="utf-8")
    (data / "pg_hba.conf").write_text("# initdb\n", encoding="utf-8")
    (data / "base").mkdir(exist_ok=True)
    (data / "global").mkdir(exist_ok=True)
    (data / "global" / "pg_control").write_bytes(b"control")
    (data / "pg_wal").mkdir(exist_ok=True)


def test_initdb_uses_pwfile_checksums_and_forbids_no_sync(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PG_RESTRICT_EXEC", "1")
    monkeypatch.setenv("PGDATA", "C:\\attacker-controlled-pgdata")
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    pwfile = Path(request.program_data_root) / "machine" / "secrets" / "postgres.pwfile"
    assert not pwfile.exists()
    bundle.postgres.apply(request, "postgres_initdb")
    bundle.postgres.verify(request, "postgres_initdb")
    initdb = next(call for call in runner.calls if call[0].endswith("initdb.exe"))
    joined = " ".join(initdb)
    assert "--pwfile" in initdb
    assert "--data-checksums" in initdb
    assert "--auth=scram-sha-256" in initdb
    assert "--no-sync" not in initdb
    assert "UTF8" in initdb
    assert "--locale=C" in joined
    conf = (Path(request.data_root) / "pgdata" / "postgresql.conf").read_text(encoding="utf-8")
    assigned = [line.strip() for line in conf.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert "listen_addresses = '127.0.0.1'" in assigned
    assert "logging_collector = on" in assigned
    assert not any(line.startswith("data_checksums") for line in assigned)
    conf_path = Path(request.data_root) / "pgdata" / "postgresql.conf"
    hba_path = Path(request.data_root) / "pgdata" / "pg_hba.conf"
    assert b"\x00" not in conf_path.read_bytes()
    assert b"\x00" not in hba_path.read_bytes()
    assert hba_path.read_text(encoding="utf-8").startswith("# Ticketbox fresh-install")
    assert not pwfile.exists()
    assert runner.initdb_pwfile_seen is True
    pwfile_acl = next(
        call
        for call in runner.calls
        if call[0].lower() == "icacls"
        and os.path.normcase(os.path.abspath(call[1]))
        == os.path.normcase(os.path.abspath(pwfile))
        and "/grant:r" in call
    )
    assert f"*{_PROCESS_USER_SID}:(R)" in pwfile_acl
    assert f"*{_SHELL_USER_SID}:(R)" not in pwfile_acl
    initdb_env = runner.envs[runner.calls.index(initdb)]
    assert initdb_env is not None
    assert not any(key.upper().startswith("PG") for key in initdb_env)
    assert any(Path(call[0]).name.lower() == "pg_controldata.exe" for call in runner.calls)


def test_initdb_precreates_pgdata_for_its_restricted_child(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.initdb_requires_precreated_pgdata = True
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")

    bundle.postgres.apply(request, "postgres_initdb")

    assert (Path(request.data_root) / "pgdata" / "global" / "pg_control").is_file()


def test_pgdata_verification_rejects_a_residual_bootstrap_user(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    pgdata = Path(request.data_root) / "pgdata"
    _write_complete_cluster(pgdata)
    monkeypatch.setattr(
        windows_security_native,
        "_object_dacl_sddl",
        lambda _path: (
            "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
            f"(A;OICI;FA;;;{_BACKEND_SERVICE_SID})(A;OICI;RC;;;OW)"
            f"(A;OICI;FA;;;{_PROCESS_USER_SID})"
        ),
    )

    with pytest.raises(LifecycleError) as caught:
        bundle.security.verify_pgdata_service_acl(request, verify_tree=True)

    assert caught.value.code == "pgdata_acl_unexpected_principal"


def test_pgdata_seal_removes_the_bootstrap_user_before_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.pgdata_acl_extra_sid = _PROCESS_USER_SID
    bundle = _bundle(runner)
    pgdata = Path(request.data_root) / "pgdata"
    _write_complete_cluster(pgdata)
    monkeypatch.setattr(windows_pgdata_security, "_require_exact_tree", lambda *_args, **_kwargs: None)

    bundle.security.seal_pgdata_acl(request)
    bundle.security.verify_pgdata_service_acl(request, verify_tree=True)

    assert runner.pgdata_acl_extra_sid is None


def test_pgdata_recursive_acl_commands_never_follow_reparse_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    pgdata = Path(request.data_root) / "pgdata"
    _write_complete_cluster(pgdata)
    monkeypatch.setattr(windows_pgdata_security, "_require_exact_tree", lambda *_args, **_kwargs: None)

    bundle.security.prepare_initdb_directory(request)
    bundle.security.seal_pgdata_acl(request)

    recursive = [
        call
        for call in runner.calls
        if call[0] == "icacls" and call[1] == str(pgdata) and "/T" in call
    ]
    assert recursive
    assert all("/L" in call for call in recursive)


def test_initdb_refuses_to_create_pwfile_without_process_user_sid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    monkeypatch.setattr(windows_security_native, "current_process_user_sid", lambda: None)

    with pytest.raises(LifecycleError) as caught:
        bundle.postgres.apply(request, "postgres_initdb")

    assert caught.value.code == "initdb_reader_unavailable"
    assert not (Path(request.program_data_root) / "machine" / "secrets" / "postgres.pwfile").exists()
    assert not any(Path(call[0]).name.lower() == "initdb.exe" for call in runner.calls)


def test_initdb_rejects_pwfile_when_exact_reader_acl_did_not_land(tmp_path: Path) -> None:
    class ReaderDroppingFileSecurity(RecordingFileSecurity):
        def protect_file(self, runner, path: Path, *, reader_sids: tuple[str, ...], code: str) -> None:
            super().protect_file(runner, path, reader_sids=(), code=code)

    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(
        runner,
        ReaderDroppingFileSecurity(),
        RecordingScmObserver(runner),
    )
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")

    with pytest.raises(LifecycleViolation) as caught:
        bundle.postgres.apply(request, "postgres_initdb")

    assert caught.value.code == "credential_acl_untrusted"
    assert not (Path(request.program_data_root) / "machine" / "secrets" / "postgres.pwfile").exists()
    assert not any(Path(call[0]).name.lower() == "initdb.exe" for call in runner.calls)


def test_initdb_failure_always_removes_password_input(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.initdb_returncode = 1
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    pwfile = Path(request.program_data_root) / "machine" / "secrets" / "postgres.pwfile"

    with pytest.raises(LifecycleError, match="initdb failed"):
        bundle.postgres.apply(request, "postgres_initdb")

    assert runner.initdb_pwfile_seen is True
    assert not pwfile.exists()


@pytest.mark.parametrize(
    ("raw_primary", "expected_code"),
    [(False, "initdb_failed"), (True, "initdb_platform_failure")],
)
def test_initdb_cleanup_failure_cannot_replace_the_primary_failure(
    tmp_path: Path,
    monkeypatch,
    raw_primary: bool,
    expected_code: str,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.initdb_returncode = 1
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")

    if raw_primary:
        def fail_materialization(_request: InstallRequest) -> Path:
            raise PermissionError("injected primary I/O failure")

        monkeypatch.setattr(bundle.security, "materialize_initdb_password_file", fail_materialization)

    def fail_cleanup(_request: InstallRequest) -> None:
        raise LifecycleError("secret_cleanup_failed", "injected cleanup failure")

    monkeypatch.setattr(bundle.security, "discard_initdb_password_file", fail_cleanup)

    with pytest.raises(LifecycleError) as caught:
        bundle.postgres.apply(request, "postgres_initdb")

    assert caught.value.code == expected_code
    assert "secret_cleanup_failed" in caught.value.message
    if raw_primary:
        assert "injected primary I/O failure" in caught.value.message


def test_roles_refuse_ready_foreign_cluster_before_any_ddl(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    runner.services.add(request.pg_service_name)
    runner.running_services.add(request.pg_service_name)
    runner.online_data_directory = str(tmp_path / "foreign-pgdata")

    with pytest.raises(LifecycleError, match="data directory"):
        bundle.postgres.apply(request, "roles_database")

    assert not any("CREATE ROLE" in (sql or "") for sql in runner.inputs)


def test_running_cluster_requires_data_checksums(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    runner.services.add(request.pg_service_name)
    runner.running_services.add(request.pg_service_name)
    runner.data_checksums = "off"

    with pytest.raises(LifecycleError, match="data checksums"):
        bundle.postgres.verify(request, "start_postgres")


def test_pg_isready_cannot_substitute_for_ticketbox_service_state(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")

    with pytest.raises(LifecycleError, match="service is not RUNNING"):
        bundle.postgres.verify(request, "start_postgres")


def test_initdb_verify_rejects_pg_version_only_directory(tmp_path: Path) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    data.mkdir(parents=True, exist_ok=True)
    (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="complete PostgreSQL cluster"):
        bundle.postgres.verify(request, "postgres_initdb")


def test_initdb_verify_rejects_complete_but_unconfigured_cluster(tmp_path: Path) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    _write_complete_cluster(data)

    with pytest.raises(LifecycleError, match="Ticketbox PostgreSQL configuration"):
        bundle.postgres.verify(request, "postgres_initdb")


def test_initdb_retries_incomplete_cluster_instead_of_starting_it(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    data = Path(request.data_root) / "pgdata"
    data.mkdir(parents=True, exist_ok=True)
    (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
    marker = data / "half-written"
    marker.write_text("crash", encoding="utf-8")
    assert bundle.postgres.apply(request, "postgres_initdb") == "initialized"
    assert not marker.exists()
    bundle.postgres.verify(request, "postgres_initdb")
    assert len([call for call in runner.calls if call[0].endswith("initdb.exe")]) == 1
    assert (data / "base").is_dir()
    assert (data / "postgresql.conf").is_file()


def test_stopped_complete_cluster_reopens_bootstrap_read_without_rerunning_initdb(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    _write_complete_cluster(data)
    runner.calls.clear()
    assert bundle.postgres.apply(request, "postgres_initdb") == "already-present"
    assert not any(call[0].endswith("initdb.exe") for call in runner.calls)
    assert any(call[0] == "icacls" and "/T" in call for call in runner.calls)
    assert runner.pgdata_bootstrap_access is True
    conf = (data / "postgresql.conf").read_text(encoding="utf-8")
    assert "listen_addresses = '127.0.0.1'" in conf
    bundle.postgres.verify(request, "postgres_initdb")


def test_pgdata_seal_rejects_nested_reparse_before_acl_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    _write_complete_cluster(data)
    nested = data / "attacker-junction"
    nested.mkdir()
    original = windows_security_native.reject_reparse_components

    def reject_nested(path: Path) -> None:
        if path == nested:
            raise LifecycleViolation("reparse_path", "nested pgdata reparse")
        original(path)

    monkeypatch.setattr(
        windows_security_native,
        "reject_reparse_components",
        reject_nested,
    )
    runner.calls.clear()

    with pytest.raises(LifecycleViolation, match="nested pgdata reparse"):
        bundle.security.seal_pgdata_acl(request)

    assert not any(call[0] == "icacls" for call in runner.calls)


def test_initdb_verify_rejects_wrong_major_or_missing_control_file(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    data = Path(request.data_root) / "pgdata"

    (data / "PG_VERSION").write_text("16\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="complete PostgreSQL cluster"):
        bundle.postgres.verify(request, "postgres_initdb")

    (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
    (data / "global" / "pg_control").unlink()
    with pytest.raises(LifecycleError, match="complete PostgreSQL cluster"):
        bundle.postgres.verify(request, "postgres_initdb")


def test_initdb_refuses_reparse_before_discarding_incomplete_cluster(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    data.mkdir(parents=True)
    marker = data / "half-written"
    marker.write_text("keep", encoding="utf-8")
    original = windows_postgres.reject_reparse_components

    def reject_pgdata(path: Path) -> None:
        if path == data:
            raise LifecycleViolation("reparse_path", "pgdata reparse")
        original(path)

    monkeypatch.setattr(windows_postgres, "reject_reparse_components", reject_pgdata)
    with pytest.raises(LifecycleViolation, match="pgdata reparse"):
        bundle.postgres.apply(request, "postgres_initdb")
    assert marker.is_file()


def test_register_uses_pg_ctl_and_direct_immutable_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    try:
        bundle.security.verify(request, "acl")
        raise AssertionError("inherited secret ACL must fail acl verify")
    except LifecycleError as exc:
        assert exc.code == "data_root_acl_too_broad"
    bundle.security.apply(request, "acl")
    bundle.security.verify(request, "acl")
    active = Path(request.program_data_root) / "machine" / "operations" / "active.json"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("{}\n", encoding="utf-8")
    bundle.security.protect_machine_json(active, request.backend_service_name)
    _write_complete_cluster(Path(request.data_root) / "pgdata")
    monkeypatch.setattr(windows_pgdata_security, "_require_exact_tree", lambda *_args, **_kwargs: None)
    bundle.scm.apply(request, "scm")
    text = _argv_text(runner.calls)
    assert "takeown" in text
    assert "pgpass" in text
    assert "*S-1-5-21-1-2-3-1001:(OI)(CI)F" not in text
    assert "*S-1-5-21-1-2-3-1001:(F)" not in text
    assert "*S-1-5-18:(OI)(CI)F" in text
    assert "*S-1-5-18:(F)" in text
    assert "*S-1-5-32-544:(OI)(CI)F" in text
    assert "*S-1-5-32-544:(F)" in text
    assert "pg_ctl.exe" in text and "register" in text
    assert "NT AUTHORITY\\LocalService" in text
    assert "sidtype" in text and "unrestricted" in text
    register = next(call for call in runner.calls if call[0].endswith("pg_ctl.exe") and "register" in call)
    assert "-o" not in register
    assert register[register.index("-S") + 1] == "demand"
    assert "shawl.exe" in text and "add" in text
    shawl_add = next(call for call in runner.calls if call[0].endswith("shawl.exe") and "add" in call)
    cwd = shawl_add[shawl_add.index("--cwd") + 1]
    assert not cwd.startswith("\\\\?\\")
    log_dir = str(Path(request.program_data_root) / "logs" / "backend")
    assert shawl_add[shawl_add.index("--log-dir") + 1] == log_dir
    backend_start = [
        call
        for call in runner.calls
        if call[:3] == ("sc.exe", "config", "TicketboxBackend") and "start=" in call
    ]
    assert backend_start[-1][backend_start[-1].index("start=") + 1] == "demand"
    assert any(
        call[:3] == ("sc.exe", "config", "TicketboxBackend")
        and "depend=" in call
        and "TicketboxPg" in call
        for call in runner.calls
    )
    backend_acl_calls = [
        call
        for call in runner.calls
        if call[0] == "icacls" and any(_BACKEND_SERVICE_SID in part for part in call)
    ]
    data_root = str(Path(request.data_root))
    app_data = str(Path(request.data_root) / "app")
    assert any(call[1] == data_root and f"*{_BACKEND_SERVICE_SID}:(RX)" in call for call in backend_acl_calls)
    assert not any(
        call[1] == data_root and any("M" in part for part in call[2:] if _BACKEND_SERVICE_SID in part)
        for call in backend_acl_calls
    )
    assert any(
        call[1] == app_data and f"*{_BACKEND_SERVICE_SID}:(OI)(CI)M" in call
        for call in backend_acl_calls
    )
    assert any(
        call[1] == log_dir and f"*{_BACKEND_SERVICE_SID}:(OI)(CI)M" in call
        for call in backend_acl_calls
    )
    assert any(
        call[0] == "icacls"
        and call[1] == str(Path(request.data_root) / "pgdata")
        and "/reset" in call
        and "/T" in call
        for call in runner.calls
    )
    assert not any(call[0] == "icacls" and "/remove:g" in call for call in runner.calls)
    assert any(
        call[0] == "icacls"
        and call[1] == str(active)
        and f"*{_BACKEND_SERVICE_SID}:(R)" in call
        for call in runner.calls
    )
    runtime_env = str(Path(request.data_root) / "app" / ".env")
    assert any(
        call[0] == "icacls"
        and call[1] == runtime_env
        and "/grant:r" in call
        and f"*{_BACKEND_SERVICE_SID}:(R)" in call
        for call in runner.calls
    )
    assert "operations" in text and "active.json" in text
    assert not any(
        call[0] == "icacls"
        and call[1].endswith("operations")
        and any(part.lower().startswith("/grant") for part in call[2:])
        for call in runner.calls
    )
    bundle.scm.verify(request, "scm")
    assert "TicketboxBackendLauncher.exe" not in text
    assert "ticketbox-backend.exe" in text.lower()
    assert "TICKETBOX_DATA_DIR=" in text
    assert f"TICKETBOX_INSTALLATION_ID={request.install_id}" in text
    assert f"TICKETBOX_DATASET_ID={request.dataset_id}" in text
    assert f"TICKETBOX_RELEASE_ID={request.target_release_id}" in text
    assert "DATABASE_URL=" not in text
    helper_calls = [call for call in runner.calls if call[0].endswith("ticketbox-database-maintenance.exe")]
    assert helper_calls == []


def test_sealed_stopped_cluster_reopens_only_for_offline_verify_then_reseals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.pgcontroldata_requires_bootstrap_access = True
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    active = Path(request.program_data_root) / "machine" / "operations" / "active.json"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("{}\n", encoding="utf-8")
    bundle.security.protect_machine_json(active, request.backend_service_name)
    bundle.postgres.apply(request, "postgres_initdb")
    def require_sealed(*_args, **_kwargs) -> None:
        if runner.pgdata_bootstrap_access:
            raise LifecycleError("pgdata_acl_unexpected_principal", "bootstrap reader remains")

    monkeypatch.setattr(windows_pgdata_security, "_require_exact_tree", require_sealed)
    bundle.scm.apply(request, "scm")
    assert runner.pgdata_bootstrap_access is False

    with pytest.raises(LifecycleError, match="PGDATA access denied"):
        bundle.postgres.verify(request, "postgres_initdb")

    assert bundle.postgres.apply(request, "postgres_initdb") == "already-present"
    bundle.postgres.verify(request, "postgres_initdb")
    assert runner.pgdata_bootstrap_access is True

    with pytest.raises(LifecycleError):
        bundle.scm.verify(request, "scm")
    bundle.scm.apply(request, "scm")
    assert runner.pgdata_bootstrap_access is False


def test_running_sealed_cluster_uses_online_identity_without_offline_pgdata_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.pgcontroldata_requires_bootstrap_access = True
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    active = Path(request.program_data_root) / "machine" / "operations" / "active.json"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("{}\n", encoding="utf-8")
    bundle.security.protect_machine_json(active, request.backend_service_name)
    bundle.postgres.apply(request, "postgres_initdb")
    def require_sealed(*_args, **_kwargs) -> None:
        if runner.pgdata_bootstrap_access:
            raise LifecycleError("pgdata_acl_unexpected_principal", "bootstrap reader remains")

    monkeypatch.setattr(windows_pgdata_security, "_require_exact_tree", require_sealed)
    bundle.scm.apply(request, "scm")
    runner.running_services.add(request.pg_service_name)
    before = sum(Path(call[0]).name.lower() == "pg_controldata.exe" for call in runner.calls)

    bundle.postgres.verify(request, "postgres_initdb")

    after = sum(Path(call[0]).name.lower() == "pg_controldata.exe" for call in runner.calls)
    assert after == before


def test_running_scm_verify_never_walks_or_reseals_live_pgdata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.services.update({request.pg_service_name, request.backend_service_name})
    runner.running_services.update({request.pg_service_name, request.backend_service_name})
    runner.service_configurations.update(
        {
            request.pg_service_name: expected_pg_service(request),
            request.backend_service_name: expected_backend_service(
                request,
                start_type=SERVICE_AUTO_START,
            ),
        }
    )
    bundle = _bundle(runner)
    scopes: list[bool] = []
    monkeypatch.setattr(
        windows_pgdata_security,
        "require_service_policy",
        lambda _path, *, service_sid, verify_tree: scopes.append(verify_tree),
    )
    monkeypatch.setattr(bundle.security, "verify_backend_runtime_authority", lambda _request: None)

    bundle.scm.verify(request, "scm")

    assert scopes == [False]
    assert not any(call[0] == "icacls" and "/T" in call for call in runner.calls)


def test_scm_refuses_to_reconcile_a_running_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.services.add(request.pg_service_name)
    runner.running_services.add(request.pg_service_name)
    runner.image_paths[request.pg_service_name] = " ".join(
        (
            str(Path(request.app_dir) / "postgresql" / "bin" / "pg_ctl.exe"),
            str(Path(request.data_root) / "pgdata"),
        )
    )
    bundle = _bundle(runner)

    with pytest.raises(LifecycleError) as caught:
        bundle.scm.apply(request, "scm")

    assert caught.value.code == "live_scm_mutation_forbidden"
    assert not any(call[0] == "icacls" and "/T" in call for call in runner.calls)


def test_alembic_helper_uses_fresh_switch_without_password_or_generation_program(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.alembic.apply(request, "alembic")
    helper = next(
        call for call in runner.calls if call[0].endswith("ticketbox-database-maintenance.exe")
    )
    joined = " ".join(helper)
    assert "--fresh-schema-upgrade" in helper
    assert "--schema-min-compatible" in helper
    min_compat = helper[helper.index("--schema-min-compatible") + 1]
    assert min_compat == request.target_release_id
    assert min_compat != request.schema_revision
    assert "DATABASE_GENERATION_PROGRAM.json" not in joined
    assert "--generation-program-path" not in helper
    assert "--managed-schema-upgrade" not in helper
    url = helper[helper.index("--database-url") + 1]
    assert "ticketbox_migrator@" in url
    assert "ticketbox:" not in url.split("@", 1)[0]
    assert runner.inputs[-1] == ""
    env = runner.envs[-1]
    assert env is not None
    assert env["PGPASSFILE"].endswith("pgpass")
    assert not any(key.upper().startswith("PG") and key.upper() != "PGPASSFILE" for key in env)
    bundle.alembic.verify(request, "alembic")
    probe_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[0].endswith("psql.exe") and runner.inputs[index] == verify_alembic_version_sql()
    )
    assert runner.calls[probe_index][-2:] == ("-f", "-")
    assert "SET ROLE ticketbox_owner" in (runner.inputs[probe_index] or "")


def test_owner_claim_uses_database_helper_and_keeps_secret_off_argv(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")

    pairing = bundle.dataset.claim_owner(request)

    helper = next(
        call
        for call in runner.calls
        if call[0].endswith("ticketbox-database-maintenance.exe") and "--fresh-owner-claim" in call
    )
    assert pairing.pairing_code == "12345678"
    assert pairing.pairing_expires_at == "2026-08-25T12:00:00Z"
    assert "--operation-id" in helper and request.operation_id in helper
    assert "--installation-id" in helper and request.install_id in helper
    assert runner.inputs[-1]
    assert runner.inputs[-1].strip() not in " ".join(helper)
    pg_env = {
        key: value
        for key, value in (runner.envs[-1] or {}).items()
        if key.upper().startswith("PG")
    }
    assert pg_env == {
        "PGPASSFILE": str(Path(request.program_data_root) / "machine" / "secrets" / "pgpass")
    }


def test_binding_read_acl_grants_only_the_exact_file_readers(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    binding = tmp_path / "programdata" / "machine" / "installation.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}\n", encoding="utf-8")
    bundle.security.grant_backend_binding_read(binding, request.backend_service_name)
    text = _argv_text(runner.calls)
    assert str(binding) in text
    assert str(binding.parent) not in [call[1] for call in runner.calls if len(call) > 1]
    assert f"*{_BACKEND_SERVICE_SID}:(R)" in text
    assert "*S-1-5-21-9-9-9-1002:(R)" in text


def test_no_shell_install_keeps_only_backend_as_binding_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    binding = tmp_path / "programdata" / "machine" / "installation.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(windows_security_native, "shell_user_sid", lambda: None)

    bundle.security.grant_backend_binding_read(binding, request.backend_service_name)

    binding_grant = next(
        call
        for call in runner.calls
        if call[0] == "icacls" and call[1] == str(binding) and "/grant:r" in call
    )
    assert f"*{_BACKEND_SERVICE_SID}:(R)" in binding_grant
    assert not any(_PROCESS_USER_SID in part for part in binding_grant)
    assert not any("S-1-5-32-545" in part for part in binding_grant)


def test_no_shell_install_can_prepare_the_operation_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    monkeypatch.setattr(windows_security_native, "shell_user_sid", lambda: None)

    bundle.security.prepare_operation_store(request)

    assert (Path(request.program_data_root) / "machine" / "operations").is_dir()


def test_runtime_authority_readers_never_mutate_operation_store_directories(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    machine = Path(request.program_data_root) / "machine"
    operations = machine / "operations"
    binding = machine / "installation.json.pending.tmp"
    active = operations / "active.json"
    operations.mkdir(parents=True)
    binding.write_text("{}\n", encoding="utf-8")
    active.write_text("{}\n", encoding="utf-8")

    assert not hasattr(bundle.security, "grant_backend_runtime_authority_read")
    bundle.security.grant_backend_binding_read(binding, request.backend_service_name)

    directory_grants = [
        call
        for call in runner.calls
        if call[0].lower() == "icacls"
        and call[1] in {str(machine), str(operations)}
        and any(part.lower().startswith("/grant") for part in call[2:])
    ]
    assert directory_grants == []


def test_credentials_are_created_only_after_root_acl(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.files.verify(request, "programdata_root")
    assert runner.calls == []
    secrets = Path(request.program_data_root) / "machine" / "secrets"
    assert not (secrets / "postgres.pwfile").exists()
    assert not (Path(request.data_root) / "app" / ".env").exists()

    bundle.security.apply(request, "acl")
    bundle.security.verify(request, "acl")
    assert not (secrets / "postgres.pwfile").exists()
    assert (secrets / "pgpass").is_file()
    assert (secrets / "ticketbox_runtime.password").is_file()
    assert (secrets / "ticketbox_migrator.password").is_file()
    env_path = Path(request.data_root) / "app" / ".env"
    assert env_path.is_file()
    env_text = env_path.read_text(encoding="utf-8")
    assert "ticketbox_runtime" in env_text
    assert "ticketbox_migrator" not in env_text.split("DATABASE_URL", 1)[1].splitlines()[0]
    assert "HTTP_BOOTSTRAP_SECRET=" not in env_text
    assert "UPLOAD_TOKEN=" not in env_text
    assert "APP_TOKEN=" not in env_text
    assert "ADMIN_TOKEN=" not in env_text


def test_acl_retry_does_not_recreate_consumed_initdb_password_input(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    pwfile = Path(request.program_data_root) / "machine" / "secrets" / "postgres.pwfile"
    assert not pwfile.exists()

    bundle.security.apply(request, "acl")
    assert not pwfile.exists()
    assert bundle.postgres.apply(request, "postgres_initdb") == "already-present"
    assert not pwfile.exists()


def test_fresh_inputs_reject_preplanted_secret_or_data(tmp_path: Path) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    bundle.security.prepare_operation_store(request)
    secret = Path(request.program_data_root) / "machine" / "secrets" / "postgres.password"
    secret.parent.mkdir(parents=True)
    secret.write_text("attacker-controlled-secret-value-123456\n", encoding="utf-8")

    with pytest.raises(LifecycleViolation, match="unbound mutable state") as caught:
        bundle.security.require_fresh_inputs(request)

    assert caught.value.code == "preexisting_mutable_state"
    assert secret.is_file()


def test_fresh_inputs_reject_precreated_empty_data_root(tmp_path: Path) -> None:
    request = _request(tmp_path)
    data_root = Path(request.data_root)
    data_root.mkdir(parents=True)
    bundle = _bundle(RecordingRunner())
    bundle.security.prepare_operation_store(request)

    with pytest.raises(LifecycleViolation, match="unbound mutable state") as caught:
        bundle.security.require_fresh_inputs(request)

    assert caught.value.code == "preexisting_mutable_state"
    assert data_root.is_dir() and list(data_root.iterdir()) == []


def test_acl_refuses_untrusted_existing_credential_before_reading_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    bundle.files.apply(request, "programdata_root")
    secret = Path(request.program_data_root) / "machine" / "secrets" / "postgres.password"
    secret.write_text("attacker-controlled-secret-value-123456\n", encoding="utf-8")
    monkeypatch.setattr(
        windows_security_native,
        "file_owner_sid",
        lambda path: (
            "S-1-5-21-9-9-9-1002" if Path(path) == secret else "S-1-5-32-544"
        ),
        raising=False,
    )

    with pytest.raises(LifecycleViolation, match="trusted owner") as caught:
        bundle.security.apply(request, "acl")

    assert caught.value.code == "credential_owner_untrusted"
    assert secret.read_text(encoding="utf-8").startswith("attacker-controlled")


def test_exact_retry_reuses_only_already_protected_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    monkeypatch.setattr(
        windows_security_native,
        "file_owner_sid",
        lambda _path: "S-1-5-32-544",
        raising=False,
    )

    bundle.security.apply(request, "acl")
    before = (Path(request.program_data_root) / "machine" / "secrets" / "postgres.password").read_text(
        encoding="utf-8"
    )
    bundle.security.apply(request, "acl")
    after = (Path(request.program_data_root) / "machine" / "secrets" / "postgres.password").read_text(
        encoding="utf-8"
    )

    assert after == before


def test_operation_root_policy_grants_the_shell_only_non_inheriting_traverse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    shell_sid = "S-1-5-21-9-9-9-1002"
    monkeypatch.setattr(windows_security_native, "shell_user_sid", lambda: shell_sid)
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")

    bundle.security.apply(request, "acl")

    policy = windows_security_native._lifecycle_directory_sddl(_BACKEND_SERVICE_SID, shell_sid)
    assert policy.startswith("O:BA")
    assert ";;;SY)" in policy
    assert ";;;BA)" in policy
    assert f"(A;;0x00000020;;;{shell_sid})" in policy
    assert f"(A;;0x000000a0;;;{_BACKEND_SERVICE_SID})" in policy
    assert f"OICI;0x00000020;;;{shell_sid}" not in policy
    assert shell_sid not in _argv_text(runner.calls)


def test_reparse_component_is_rejected_before_credentials(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    reparse = Path(request.program_data_root)
    real_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path == reparse:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    bundle = _bundle(RecordingRunner())

    with pytest.raises(LifecycleViolation, match="reparse"):
        bundle.files.apply(request, "programdata_root")
    assert not (Path(request.program_data_root) / "machine" / "secrets" / "postgres.password").exists()


def test_roles_adapter_creates_owner_migrator_runtime(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    runner.services.add(request.pg_service_name)
    runner.running_services.add(request.pg_service_name)
    bundle.postgres.apply(request, "roles_database")
    bundle.postgres.verify(request, "roles_database")
    argv_text = _argv_text(runner.calls)
    sql_text = "\n".join(item or "" for item in runner.inputs)
    psql_calls = [call for call in runner.calls if Path(call[0]).name.lower() == "psql.exe"]
    assert psql_calls
    assert all("-c" not in call for call in psql_calls)
    assert all("-f" in call and call[call.index("-f") + 1] == "-" for call in psql_calls)
    assert "PASSWORD" not in argv_text
    migrator_secret = (Path(request.program_data_root) / "machine" / "secrets" / "ticketbox_migrator.password").read_text(encoding="utf-8").strip()
    runtime_secret = (Path(request.program_data_root) / "machine" / "secrets" / "ticketbox_runtime.password").read_text(encoding="utf-8").strip()
    assert migrator_secret not in argv_text
    assert runtime_secret not in argv_text
    assert "CREATE ROLE ticketbox_owner NOLOGIN" in sql_text
    assert "CREATE ROLE ticketbox_migrator LOGIN" in sql_text
    assert "CREATE ROLE ticketbox_runtime LOGIN" in sql_text
    assert "GRANT ticketbox_owner TO ticketbox_migrator WITH INHERIT FALSE, SET TRUE" in sql_text
    assert "CREATE DATABASE ticketbox OWNER ticketbox_owner" in sql_text
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE ticketbox_owner" in sql_text
    assert f"PASSWORD '{migrator_secret}'" in sql_text
    assert any(
        "ticketbox_privileges_ready" in (item or "")
        for item in runner.inputs
    )


def test_role_provision_failure_does_not_expose_generated_passwords(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.fail_password_sql = True
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")
    bundle.postgres.apply(request, "postgres_initdb")
    runner.services.add(request.pg_service_name)
    runner.running_services.add(request.pg_service_name)
    passwords = {
        (Path(request.program_data_root) / "machine" / "secrets" / name)
        .read_text(encoding="utf-8")
        .strip()
        for name in ("ticketbox_migrator.password", "ticketbox_runtime.password")
    }

    with pytest.raises(LifecycleError) as caught:
        bundle.postgres.apply(request, "roles_database")

    assert caught.value.code == "create_role_failed"
    assert all(password not in caught.value.message for password in passwords)


def test_owner_claim_failure_does_not_expose_helper_output(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    leaked = "pairing=12345678 bootstrap=owner-secret-material"
    runner.owner_claim_failure_output = leaked
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.security.apply(request, "acl")

    with pytest.raises(LifecycleError) as caught:
        bundle.dataset.claim_owner(request)

    assert caught.value.code == "owner_claim_failed"
    assert leaked not in caught.value.message


def test_scm_refuses_foreign_same_name_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.services.add("TicketboxPg")
    runner.image_paths["TicketboxPg"] = r"C:\Windows\System32\notepad.exe"
    runner.service_configurations["TicketboxPg"] = _recorded_service_configuration(
        name="TicketboxPg",
        argv=(r"C:\Windows\System32\notepad.exe",),
        start_type=3,
        dependencies=(),
        account_sid="S-1-5-18",
    )
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    try:
        bundle.scm.apply(request, "scm")
        raise AssertionError("foreign SCM must fail closed")
    except LifecycleViolation as exc:
        assert exc.code == "scm_collision"
    text = _argv_text(runner.calls)
    assert "obj=" not in text
    assert "sidtype" not in text
    assert not any(call[0].endswith("pg_ctl.exe") and "register" in call for call in runner.calls)
    assert not any(call[0].endswith("shawl.exe") and "add" in call for call in runner.calls)


def test_scm_refuses_foreign_backend_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.services.add("TicketboxBackend")
    runner.image_paths["TicketboxBackend"] = r"C:\Windows\System32\notepad.exe"
    runner.service_configurations["TicketboxBackend"] = _recorded_service_configuration(
        name="TicketboxBackend",
        argv=(r"C:\Windows\System32\notepad.exe",),
        start_type=3,
        dependencies=(),
        account_sid="S-1-5-18",
    )
    bundle = _bundle(runner)
    bundle.files.apply(request, "programdata_root")
    try:
        bundle.scm.apply(request, "scm")
        raise AssertionError("foreign backend SCM must fail closed")
    except LifecycleViolation as exc:
        assert exc.code == "scm_collision"
    assert not any(
        call[:3] == ("sc.exe", "config", "TicketboxBackend") and "obj=" in call
        for call in runner.calls
    )
    assert not any(call[0].endswith("shawl.exe") and "add" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend_version", "9.9.9"),
        ("installation_id", "22222222-2222-4222-8222-222222222222"),
        ("runtime_access_state", "repair_required"),
        ("owner_state", "recovery_required"),
    ],
)
def test_health_requires_exact_release_identity_and_usable_owner(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: str,
) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    payload = {
        "contract": "ticketbox-installation-health-v2",
        "status": "ok",
        "backend_version": request.target_release_id,
        "installation_id": request.install_id,
        "runtime_access_state": "available",
        "owner_state": "configured",
    }
    payload[field] = value

    _stub_direct_health(monkeypatch, payload)
    monkeypatch.setattr(bundle.dataset, "_live_dataset_id", lambda _request: request.dataset_id)

    with pytest.raises(LifecycleError):
        bundle.dataset.verify(request, "health")


def test_health_ignores_ambient_proxy_and_accepts_exact_identity(tmp_path: Path, monkeypatch) -> None:
    request = _request(tmp_path)
    bundle = _bundle(RecordingRunner())
    payload = {
        "contract": "ticketbox-installation-health-v2",
        "status": "ok",
        "backend_version": request.target_release_id,
        "installation_id": request.install_id,
        "runtime_access_state": "available",
        "owner_state": "configured",
    }

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    _stub_direct_health(monkeypatch, payload)
    monkeypatch.setattr(bundle.dataset, "_live_dataset_id", lambda _request: request.dataset_id)

    bundle.dataset.verify(request, "health")
