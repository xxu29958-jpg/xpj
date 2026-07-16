from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    START_TEST_POSTGRES,
    STOP_TEST_POSTGRES,
    TEST_POSTGRES_CONTRACT,
    TEST_POSTGRES_CREDENTIAL,
    _database_exists,
    _free_local_port,
    _postgres_bin,
    _run_lifecycle,
    _run_pg,
    _stop_preserving_data,
    _table_exists,
)
from _powershell_contract import powershell_contract_engines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_local_test_postgres_rejects_a_different_cluster_before_provisioning(
    tmp_path: Path,
) -> None:
    postgres_bin = _postgres_bin()
    powershell_51, powershell_7 = powershell_contract_engines()
    port = _free_local_port()
    expected_dir = tmp_path / "expected cluster"
    actual_dir = tmp_path / "actual listener"

    try:
        expected_start = _run_lifecycle(
            powershell_51,
            START_TEST_POSTGRES,
            port=port,
            data_dir=expected_dir,
            postgres_bin=postgres_bin,
        )
        assert expected_start.returncode == 0, expected_start.stdout + expected_start.stderr
        _stop_preserving_data(postgres_bin, expected_dir)
        (expected_dir / "postmaster.pid").write_text(
            f"{os.getpid()}\n{expected_dir.resolve()}\n1\n{port}\n",
            encoding="ascii",
        )
        reused_pid_restart = _run_lifecycle(
            powershell_7,
            START_TEST_POSTGRES,
            port=port,
            data_dir=expected_dir,
            postgres_bin=postgres_bin,
        )
        assert reused_pid_restart.returncode == 0, reused_pid_restart.stdout + reused_pid_restart.stderr
        _stop_preserving_data(postgres_bin, expected_dir)

        actual_start = _run_lifecycle(
            powershell_7,
            START_TEST_POSTGRES,
            port=port,
            data_dir=actual_dir,
            postgres_bin=postgres_bin,
        )
        assert actual_start.returncode == 0, actual_start.stdout + actual_start.stderr

        actual_reuse = _run_lifecycle(
            powershell_51,
            START_TEST_POSTGRES,
            port=port,
            data_dir=actual_dir,
            postgres_bin=postgres_bin,
        )
        assert actual_reuse.returncode == 0, actual_reuse.stdout + actual_reuse.stderr
        assert "Reusing owned PostgreSQL" in actual_reuse.stdout
        credential_file = actual_dir / TEST_POSTGRES_CREDENTIAL
        credential = credential_file.read_text(encoding="utf-8").strip()
        assert credential not in (actual_start.stdout + actual_start.stderr)
        assert credential not in (actual_reuse.stdout + actual_reuse.stderr)
        assert credential not in (actual_dir / ".xpj-test-cluster.json").read_text(
            encoding="utf-8"
        )
        active_hba = [
            line.strip()
            for line in (actual_dir / "pg_hba.conf").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert active_hba
        assert all("scram-sha-256" in line for line in active_hba)
        assert all("trust" not in line for line in active_hba)

        original_hba = (actual_dir / "pg_hba.conf").read_text(encoding="utf-8")
        for downgraded_authentication in ("trust", "password"):
            try:
                (actual_dir / "pg_hba.conf").write_text(
                    f"host all all 127.0.0.1/32 {downgraded_authentication}\n",
                    encoding="utf-8",
                )
                reloaded = _run_pg(
                    postgres_bin,
                    "pg_ctl.exe",
                    "-D",
                    str(actual_dir),
                    "reload",
                )
                assert reloaded.returncode == 0, reloaded.stdout + reloaded.stderr
                deadline = time.monotonic() + 5
                while True:
                    downgrade_probe = _run_pg(
                        postgres_bin,
                        "psql.exe",
                        "--no-psqlrc",
                        "--no-password",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--username",
                        "postgres",
                        "--dbname",
                        "postgres",
                        "--command",
                        "SELECT 1",
                        credential_file=actual_dir / TEST_POSTGRES_CREDENTIAL,
                        port=port,
                    )
                    if (
                        downgrade_probe.returncode != 0
                        or time.monotonic() >= deadline
                    ):
                        break
                    time.sleep(0.05)
                assert downgrade_probe.returncode != 0, (
                    "libpq accepted downgraded authentication despite the SCRAM "
                    f"requirement: {downgraded_authentication}"
                )
            finally:
                (actual_dir / "pg_hba.conf").write_text(
                    original_hba,
                    encoding="utf-8",
                )
                restored = _run_pg(
                    postgres_bin,
                    "pg_ctl.exe",
                    "-D",
                    str(actual_dir),
                    "reload",
                )
                assert restored.returncode == 0, restored.stdout + restored.stderr

        passwordless = _run_pg(
            postgres_bin,
            "psql.exe",
            "--no-psqlrc",
            "--no-password",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--username",
            "postgres",
            "--dbname",
            "postgres",
            "--command",
            "SELECT 1",
        )
        assert passwordless.returncode != 0, passwordless.stdout + passwordless.stderr
        wrong_credential = actual_dir / ".xpj-wrong-postgres-password"
        wrong_credential.write_text("x" * 43 + "\n", encoding="utf-8")
        try:
            wrong_password = _run_pg(
                postgres_bin,
                "psql.exe",
                "--no-psqlrc",
                "--no-password",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--username",
                "postgres",
                "--dbname",
                "postgres",
                "--command",
                "SELECT 1",
                credential_file=wrong_credential,
                port=port,
            )
        finally:
            wrong_credential.unlink(missing_ok=True)
        assert wrong_password.returncode != 0, wrong_password.stdout + wrong_password.stderr
        assert credential not in (wrong_password.stdout + wrong_password.stderr)
        assert not list(actual_dir.glob(".xpj-pgpass-*"))

        create_sentinel = _run_pg(
            postgres_bin,
            "psql.exe",
            "--no-psqlrc",
            "--no-password",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--username",
            "postgres",
            "--dbname",
            "xpj_smoke",
            "--command",
            "CREATE TABLE reset_probe (id integer)",
            credential_file=actual_dir / TEST_POSTGRES_CREDENTIAL,
            port=port,
        )
        assert create_sentinel.returncode == 0, create_sentinel.stdout + create_sentinel.stderr
        reset_reuse = _run_lifecycle(
            powershell_51,
            START_TEST_POSTGRES,
            port=port,
            data_dir=actual_dir,
            postgres_bin=postgres_bin,
            reset_databases=True,
        )
        assert reset_reuse.returncode == 0, reset_reuse.stdout + reset_reuse.stderr
        assert not _table_exists(
            postgres_bin,
            port,
            "xpj_smoke",
            "reset_probe",
            actual_dir,
        )

        actual_pid_path = actual_dir / "postmaster.pid"
        actual_pid_text = actual_pid_path.read_text(encoding="utf-8")
        actual_pid_lines = actual_pid_text.splitlines()
        actual_pid_path.unlink()
        refused_stop = _run_lifecycle(
            powershell_7,
            STOP_TEST_POSTGRES,
            port=port,
            data_dir=actual_dir,
            postgres_bin=postgres_bin,
        )
        refused_output = refused_stop.stdout + refused_stop.stderr
        assert refused_stop.returncode != 0, refused_output
        assert "is not quiescent" in refused_output, refused_output
        assert actual_dir.exists()
        actual_pid_path.write_text(actual_pid_text, encoding="utf-8")

        (expected_dir / "postmaster.pid").write_text(
            "\n".join(
                (
                    actual_pid_lines[0],
                    str(expected_dir.resolve()),
                    actual_pid_lines[2],
                    str(port),
                )
            )
            + "\n",
            encoding="ascii",
        )

        drop = _run_pg(
            postgres_bin,
            "psql.exe",
            "--no-psqlrc",
            "--no-password",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--username",
            "postgres",
            "--dbname",
            "postgres",
            "--command",
            "DROP DATABASE xpj_smoke",
            credential_file=actual_dir / TEST_POSTGRES_CREDENTIAL,
            port=port,
        )
        assert drop.returncode == 0, drop.stdout + drop.stderr

        mismatched_start = _run_lifecycle(
            powershell_7,
            START_TEST_POSTGRES,
            port=port,
            data_dir=expected_dir,
            postgres_bin=postgres_bin,
        )
        output = mismatched_start.stdout + mismatched_start.stderr
        assert mismatched_start.returncode != 0, output
        assert "XPJ_TEST_POSTGRES_IDENTITY_MISMATCH" in output, output
        assert not _database_exists(postgres_bin, port, "xpj_smoke", actual_dir)
    finally:
        cleanup_failures: list[str] = []
        for engine, data_dir in (
            (powershell_51, actual_dir),
            (powershell_7, expected_dir),
        ):
            if not data_dir.exists():
                continue
            stopped = _run_lifecycle(
                engine,
                STOP_TEST_POSTGRES,
                port=port,
                data_dir=data_dir,
                postgres_bin=postgres_bin,
            )
            if stopped.returncode != 0:
                cleanup_failures.append(stopped.stdout + stopped.stderr)
        assert not cleanup_failures, "\n".join(cleanup_failures)
        assert not actual_dir.exists()
        assert not expected_dir.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
@pytest.mark.parametrize(
    "fault_phase",
    ["after-password", "after-hba-reload"],
)
def test_legacy_trust_cluster_scram_migration_is_reentrant(
    tmp_path: Path,
    fault_phase: str,
) -> None:
    postgres_bin = _postgres_bin()
    engines = powershell_contract_engines()
    prepare = tmp_path / f"prepare-legacy-{fault_phase}.ps1"
    prepare.write_text(
        "param($Contract,$PostgresBin,$DataDir,$Port)\n"
        ". $Contract\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDir\n"
        "$systemIdentifier = Get-XpjTestPostgresControlSystemIdentifier "
        "-PostgresBin $PostgresBin -DataDirectory $DataDir\n"
        "$payload = [ordered]@{\n"
        "  schema_version = 2\n"
        "  kind = 'xiaopiaojia-test-postgres'\n"
        "  purpose = 'local'\n"
        "  port = [int]$Port\n"
        "  instance_id = [Guid]::NewGuid().ToString('N')\n"
        "  system_identifier = [string]$systemIdentifier\n"
        "} | ConvertTo-Json -Compress\n"
        "Write-XpjTestPostgresProtectedUtf8File "
        "-Path (Join-Path $DataDir '.xpj-test-cluster.json') "
        "-Content ($payload + [Environment]::NewLine)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDir\n",
        encoding="ascii",
    )

    for index, first_engine in enumerate(engines):
        recovery_engine = engines[(index + 1) % len(engines)]
        port = _free_local_port()
        data_dir = tmp_path / f"legacy-{fault_phase}-{index}"
        initialized = _run_pg(
            postgres_bin,
            "initdb.exe",
            "-D",
            str(data_dir),
            "-U",
            "postgres",
            "--auth-host=trust",
            "--auth-local=trust",
            "-E",
            "UTF8",
            "--locale=C",
        )
        assert initialized.returncode == 0, initialized.stdout + initialized.stderr
        prepared = subprocess.run(
            [
                first_engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(prepare),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        fault_environment = os.environ.copy()
        fault_environment["XPJ_TEST_POSTGRES_AUTH_FAULT_PHASE"] = fault_phase
        interrupted = _run_lifecycle(
            first_engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
            environment=fault_environment,
        )
        interrupted_output = interrupted.stdout + interrupted.stderr
        assert interrupted.returncode != 0, interrupted_output
        assert (
            f"authentication fault {fault_phase.replace('-', ' ')}"
            in interrupted_output.lower()
        )
        credential_file = data_dir / TEST_POSTGRES_CREDENTIAL
        credential = credential_file.read_text(encoding="utf-8").strip()
        assert len(credential) == 43
        assert credential not in interrupted_output
        assert json.loads(
            (data_dir / ".xpj-test-cluster.json").read_text(encoding="utf-8")
        )["schema_version"] == 2
        assert not list(data_dir.glob(".xpj-pgpass-*"))

        recovered = _run_lifecycle(
            recovery_engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        recovered_output = recovered.stdout + recovered.stderr
        try:
            assert recovered.returncode == 0, recovered_output
            assert credential not in recovered_output
            marker = json.loads(
                (data_dir / ".xpj-test-cluster.json").read_text(
                    encoding="utf-8"
                )
            )
            assert marker["schema_version"] == 3
            assert marker["authentication"] == "scram-sha-256"
            active_hba = [
                line.strip()
                for line in (data_dir / "pg_hba.conf").read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            assert active_hba
            assert all("scram-sha-256" in line for line in active_hba)
            assert all("trust" not in line for line in active_hba)
            for path in (
                data_dir / "server.log",
                data_dir / "server-error.log",
                data_dir / "postgresql.auto.conf",
            ):
                if path.is_file():
                    assert credential not in path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
            assert not list(data_dir.glob(".xpj-pgpass-*"))
        finally:
            stopped = _run_lifecycle(
                recovery_engine,
                STOP_TEST_POSTGRES,
                port=port,
                data_dir=data_dir,
                postgres_bin=postgres_bin,
            )
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
            assert not data_dir.exists()
