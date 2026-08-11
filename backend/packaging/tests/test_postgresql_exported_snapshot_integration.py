from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest
from _postgresql_exported_snapshot_support import (
    DATABASE_SAFETY,
    INSTALLATION_SAFETY,
    PACKAGING,
    ps_literal,
)
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(
    name="windows_postgresql_exported_snapshot"
)

BACKEND = PACKAGING.parent
EXPORTED_SNAPSHOT = PACKAGING / "windows_postgresql_exported_snapshot.ps1"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_powershell_process(
    command: list[str], *, timeout: int
) -> subprocess.CompletedProcess[str]:
    with (
        tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as stdout,
        tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        ) as stderr,
    ):
        completed = subprocess.run(
            command,
            check=False,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
        )
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            stdout.read().lstrip("\ufeff"),
            stderr.read().lstrip("\ufeff"),
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL 17")
def test_real_pg17_split_ready_keeps_snapshot_importable(
    tmp_path: Path,
) -> None:
    engine = powershell_contract_engines()[0]
    storage = BACKEND / "scripts" / "test_pg_storage_contract.ps1"
    start = BACKEND / "scripts" / "start_test_pg.ps1"
    stop = BACKEND / "scripts" / "stop_test_pg.ps1"
    root_probe = subprocess.run(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f". '{ps_literal(storage)}'; "
            "(Initialize-XpjTestPostgresRuntimeRoot) | "
            "ConvertTo-Json -Compress",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
    )
    assert root_probe.returncode == 0, root_probe.stdout + root_probe.stderr
    protected_root = Path(json.loads(root_probe.stdout.strip().splitlines()[-1]))
    data_dir = protected_root / f"xpj_pg_snapshot_{uuid.uuid4().hex}"
    port = _free_loopback_port()
    started = _run_powershell_process(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(start),
            "-Port",
            str(port),
            "-DataDir",
            str(data_dir),
        ],
        timeout=60,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    holder: subprocess.Popen[str] | None = None
    try:
        bin_probe = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f". '{ps_literal(storage)}'; [string](Find-XpjPostgresBin)",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert bin_probe.returncode == 0, bin_probe.stdout + bin_probe.stderr
        pg_bin = Path(bin_probe.stdout.strip().splitlines()[-1])
        psql = pg_bin / "psql.exe"
        pg_dump = pg_bin / "pg_dump.exe"
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("PG")
        }
        environment["PGPASSFILE"] = str(
            data_dir / ".xpj-test-postgres.pgpass"
        )
        database_url = f"postgresql://postgres@localhost:{port}/postgres"
        close_signal = tmp_path / "close-exported-snapshot.signal"
        holder_script = tmp_path / "hold-exported-snapshot.ps1"
        holder_script.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{ps_literal(INSTALLATION_SAFETY)}'
. '{ps_literal(DATABASE_SAFETY)}'
. '{ps_literal(EXPORTED_SNAPSHOT)}'
$holder = $null
try {{
    $holder = Start-TicketboxPostgresqlExportedSnapshotSession `
        -PsqlPath '{ps_literal(psql)}' `
        -ProtectedDatabaseUrl '{ps_literal(database_url)}' `
        -SqlCommands @(
            'BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;',
            "SELECT 'TBX_SNAPSHOT:' || pg_export_snapshot(); " +
                "SELECT 'TBX_READY';"
        )
    $readBudget = [Diagnostics.Stopwatch]::StartNew()
    $snapshotLine = Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $holder `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(10)) `
        -BudgetStopwatch $readBudget -MaximumElapsedMilliseconds 10000
    $readyLine = Read-TicketboxPostgresqlExportedSnapshotLine `
        -Process $holder `
        -AbsoluteDeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(10)) `
        -BudgetStopwatch $readBudget -MaximumElapsedMilliseconds 10000
    [Console]::Out.WriteLine($snapshotLine)
    [Console]::Out.WriteLine($readyLine)
    [Console]::Out.Flush()
    $holdBudget = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath '{ps_literal(close_signal)}')) {{
        if ($holdBudget.ElapsedMilliseconds -gt 30000) {{
            throw 'exported snapshot test close signal timed out'
        }}
        Assert-TicketboxPostgresqlExportedSnapshotSessionAlive $holder
        Start-Sleep -Milliseconds 50
    }}
}}
finally {{
    if ($null -ne $holder) {{
        Stop-TicketboxPostgresqlExportedSnapshotSession $holder 10000
    }}
}}
""",
            encoding="utf-8-sig",
        )
        holder = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(holder_script),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            bufsize=1,
        )
        assert holder.stdout is not None
        lines: queue.Queue[str] = queue.Queue()

        def drain_stdout() -> None:
            assert holder is not None and holder.stdout is not None
            for line in holder.stdout:
                lines.put(line.strip())

        threading.Thread(target=drain_stdout, daemon=True).start()
        snapshot_id = ""
        ready = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not ready:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line.startswith("TBX_SNAPSHOT:"):
                snapshot_id = line.removeprefix("TBX_SNAPSHOT:")
            elif line == "TBX_READY":
                ready = True
        assert ready and snapshot_id and holder.poll() is None

        live_dump = tmp_path / "live.dump"
        live = subprocess.run(
            [
                str(pg_dump),
                "--no-password",
                "--format=custom",
                f"--snapshot={snapshot_id}",
                "--file",
                str(live_dump),
                "--dbname",
                database_url,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=20,
        )
        assert live.returncode == 0, live.stdout + live.stderr
        assert live_dump.stat().st_size > 0

        close_signal.write_text("close\n", encoding="ascii")
        holder.wait(timeout=10)
        assert holder.returncode == 0, (
            holder.stderr.read() if holder.stderr is not None else ""
        )
        holder = None
        closed = subprocess.run(
            [
                str(pg_dump),
                "--no-password",
                "--format=custom",
                f"--snapshot={snapshot_id}",
                "--file",
                str(tmp_path / "closed.dump"),
                "--dbname",
                database_url,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=20,
        )
        assert closed.returncode != 0
        closed_error = closed.stderr.lower()
        assert "snapshot" in closed_error
        assert "does not exist" in closed_error
        assert "set transaction snapshot" in closed_error
    finally:
        if holder is not None and holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)
        stopped = _run_powershell_process(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(stop),
                "-Port",
                str(port),
                "-DataDir",
                str(data_dir),
            ],
            timeout=60,
        )
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
