from __future__ import annotations

import os
from pathlib import Path

import pytest

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.postgres_roles import (
    expected_membership_probe,
    expected_roles_probe,
    verify_alembic_version_sql,
)
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.envs: list[dict[str, str] | None] = []
        self.inputs: list[str | None] = []
        self.services: set[str] = set()
        self.image_paths: dict[str, str] = {}

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
            data = Path(recorded[recorded.index("-D") + 1])
            data.mkdir(parents=True, exist_ok=True)
            (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
            (data / "postgresql.conf").write_text("# initdb\n", encoding="utf-8")
            (data / "pg_hba.conf").write_text("# initdb\n", encoding="utf-8")
            (data / "base").mkdir(exist_ok=True)
            return CompletedCommand(recorded, 0, "ok", "")
        if name in {"pg_ctl.exe", "shawl.exe", "sc.exe"}:
            return self._complete_scm(name, recorded)
        if name == "psql.exe":
            return self._complete_psql(recorded, sql_text)
        if name == "ticketbox-database-maintenance.exe":
            return CompletedCommand(recorded, 0, '{"result":"upgraded"}', "")
        if name == "whoami":
            return CompletedCommand(
                recorded,
                0,
                "User Name SID\n============= ===\nTBX-QUAL-01\\tbxqual S-1-5-21-1-2-3-1001\n",
                "",
            )
        if name == "icacls" and len(recorded) == 2:
            return self._complete_icacls(recorded)
        return CompletedCommand(recorded, 0, "ok", "")

    def _complete_scm(self, name: str, recorded: tuple[str, ...]) -> CompletedCommand:
        if name == "pg_ctl.exe" and "register" in recorded:
            service = recorded[recorded.index("-N") + 1]
            self.services.add(service)
            self.image_paths[service] = recorded[0]
            return CompletedCommand(recorded, 0, "", "")
        if name == "shawl.exe" and "add" in recorded:
            service = recorded[recorded.index("--name") + 1]
            self.services.add(service)
            self.image_paths[service] = recorded[-1]
            return CompletedCommand(recorded, 0, "", "")
        if name == "sc.exe" and recorded[1] == "query":
            service = recorded[2]
            if service in self.services:
                return CompletedCommand(recorded, 0, "STATE              : 4  RUNNING", "")
            return CompletedCommand(recorded, 1060, "specified service does not exist", "")
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
        return CompletedCommand(recorded, 0, "ok", "")

    def _complete_psql(self, recorded: tuple[str, ...], sql_text: str) -> CompletedCommand:
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
            return CompletedCommand(
                recorded,
                0,
                (
                    f"{recorded[1]} NT SERVICE\\TicketboxPg:(OI)(CI)(F)\n"
                    "*S-1-5-18:(OI)(CI)(F)\n"
                    "*S-1-5-32-544:(OI)(CI)(F)\n"
                ),
                "",
            )
        protected = any(
            call
            and call[0].lower() == "takeown"
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
        backend_grant = any(
            call
            and call[0].lower() == "icacls"
            and "/grant" in call
            and any("TicketboxBackend:(R)" in part for part in call)
            and any(os.path.normcase(os.path.abspath(part)) == target for part in call[1:])
            for call in self.calls
        )
        extra = " NT SERVICE\\TicketboxBackend:(R)\n" if backend_grant else ""
        return CompletedCommand(
            recorded,
            0,
            f"{recorded[1]} *S-1-5-21-1-2-3-1001:(F)\n*S-1-5-18:(F)\n*S-1-5-32-544:(F)\n{extra}",
            "",
        )


def _request(tmp_path: Path) -> InstallRequest:
    app_dir = tmp_path / "app"
    pg_bin = app_dir / "postgresql" / "bin"
    release = app_dir / "releases" / "1.2.0"
    backend = release / "backend"
    pg_bin.mkdir(parents=True)
    backend.mkdir(parents=True)
    (app_dir / "bin").mkdir()
    for name in ("initdb.exe", "pg_ctl.exe", "psql.exe", "pg_isready.exe"):
        (pg_bin / name).write_text("fake", encoding="utf-8")
    (backend / "ticketbox-database-maintenance.exe").write_text("fake", encoding="utf-8")
    (app_dir / "bin" / "shawl.exe").write_text("fake", encoding="utf-8")
    (app_dir / "bin" / "TicketboxBackendLauncher.exe").write_text("fake", encoding="utf-8")
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
        data_root=str(tmp_path / "data"),
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


def test_initdb_uses_pwfile_checksums_and_forbids_no_sync(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
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


def test_initdb_verify_rejects_pg_version_only_directory(tmp_path: Path) -> None:
    request = _request(tmp_path)
    bundle = WindowsAdapterBundle(RecordingRunner())
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    data.mkdir(parents=True, exist_ok=True)
    (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="complete PostgreSQL cluster"):
        bundle.postgres.verify(request, "postgres_initdb")


def test_initdb_retries_incomplete_cluster_instead_of_starting_it(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
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


def test_initdb_skips_complete_cluster_and_still_writes_listen_config(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
    data = Path(request.data_root) / "pgdata"
    data.mkdir(parents=True, exist_ok=True)
    (data / "PG_VERSION").write_text("17\n", encoding="utf-8")
    (data / "postgresql.conf").write_text("# leftover\n", encoding="utf-8")
    (data / "pg_hba.conf").write_text("# leftover\n", encoding="utf-8")
    (data / "base").mkdir()
    assert bundle.postgres.apply(request, "postgres_initdb") == "already-present"
    assert not any(call[0].endswith("initdb.exe") for call in runner.calls)
    conf = (data / "postgresql.conf").read_text(encoding="utf-8")
    assert "listen_addresses = '127.0.0.1'" in conf
    bundle.postgres.verify(request, "postgres_initdb")


def test_register_uses_pg_ctl_local_service_sid_and_stable_launcher(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
    try:
        bundle.security.verify(request, "acl")
        raise AssertionError("inherited secret ACL must fail acl verify")
    except LifecycleError as exc:
        assert exc.code == "postcondition_missing"
    bundle.security.apply(request, "acl")
    bundle.security.verify(request, "acl")
    bundle.scm.apply(request, "scm")
    text = _argv_text(runner.calls)
    assert "takeown" in text
    assert "pgpass" in text
    assert "*S-1-5-21-1-2-3-1001:(OI)(CI)F" in text
    assert "*S-1-5-21-1-2-3-1001:(F)" in text
    assert "*S-1-5-18:(OI)(CI)F" in text
    assert "*S-1-5-18:(F)" in text
    assert "*S-1-5-32-544:(OI)(CI)F" in text
    assert "*S-1-5-32-544:(F)" in text
    assert "pg_ctl.exe" in text and "register" in text
    assert "NT AUTHORITY\\LocalService" in text
    assert "sidtype" in text and "unrestricted" in text
    register = next(call for call in runner.calls if call[0].endswith("pg_ctl.exe") and "register" in call)
    assert "-o" not in register
    assert "shawl.exe" in text and "add" in text
    shawl_add = next(call for call in runner.calls if call[0].endswith("shawl.exe") and "add" in call)
    cwd = shawl_add[shawl_add.index("--cwd") + 1]
    assert not cwd.startswith("\\\\?\\")
    assert any(
        call[:3] == ("sc.exe", "config", "TicketboxBackend") and "start=" in call and "auto" in call
        for call in runner.calls
    )
    assert any(
        call[:3] == ("sc.exe", "config", "TicketboxBackend")
        and "depend=" in call
        and "TicketboxPg" in call
        for call in runner.calls
    )
    assert any(
        call[0] == "icacls" and "/remove:g" in call and "NT SERVICE\\TicketboxBackend" in call
        for call in runner.calls
    )
    assert "NT SERVICE\\TicketboxBackend:(R)" in text
    assert "backend.env" in text
    bundle.scm.verify(request, "scm")
    assert "TicketboxBackendLauncher.exe" in text
    assert "ticketbox-backend.exe" not in text.lower()
    helper_calls = [call for call in runner.calls if call[0].endswith("ticketbox-database-maintenance.exe")]
    assert helper_calls == []


def test_alembic_helper_uses_fresh_switch_without_password_or_generation_program(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
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
    probe = next(call for call in runner.calls if call[0].endswith("psql.exe") and "alembic_version" in call[-1])
    assert probe[-1] == verify_alembic_version_sql()
    assert "SET ROLE ticketbox_owner" in probe[-1]


def test_binding_read_acl_grants_backend_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    binding = tmp_path / "programdata" / "machine" / "installation.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}\n", encoding="utf-8")
    bundle.security.grant_backend_binding_read(binding, request.backend_service_name)
    text = _argv_text(runner.calls)
    assert str(binding.parent) in text
    assert str(binding) in text
    assert "NT SERVICE\\TicketboxBackend:(RX)" in text
    assert "NT SERVICE\\TicketboxBackend:(R)" in text


def test_files_adapter_materializes_secrets_without_platform_commands(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
    bundle.files.verify(request, "programdata_root")
    assert runner.calls == []
    secrets = Path(request.program_data_root) / "machine" / "secrets"
    assert (secrets / "postgres.pwfile").is_file()
    assert (secrets / "pgpass").is_file()
    assert (secrets / "backend.env").is_file()
    assert (secrets / "ticketbox_runtime.password").is_file()
    assert (secrets / "ticketbox_migrator.password").is_file()
    assert not (Path(request.data_root) / "app" / ".env").is_file()
    env_text = (secrets / "backend.env").read_text(encoding="utf-8")
    assert "ticketbox_runtime" in env_text
    assert "ticketbox_migrator" not in env_text.split("DATABASE_URL", 1)[1].splitlines()[0]
    assert "HTTP_BOOTSTRAP_SECRET=" in env_text
    assert "UPLOAD_TOKEN=" not in env_text
    assert "APP_TOKEN=" not in env_text
    assert "ADMIN_TOKEN=" not in env_text


def test_roles_adapter_creates_owner_migrator_runtime(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    bundle = WindowsAdapterBundle(runner)
    bundle.files.apply(request, "programdata_root")
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


def test_scm_refuses_foreign_same_name_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    runner = RecordingRunner()
    runner.services.add("TicketboxPg")
    runner.image_paths["TicketboxPg"] = r"C:\Windows\System32\notepad.exe"
    bundle = WindowsAdapterBundle(runner)
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
    bundle = WindowsAdapterBundle(runner)
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
