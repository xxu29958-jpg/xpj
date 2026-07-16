from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    TEST_POSTGRES_CONTRACT,
    _free_local_port,
    _windows_process_is_running,
)
from _powershell_contract import powershell_contract_engines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_bounded_process_times_out_and_releases_lifecycle_mutex(tmp_path: Path) -> None:
    child = tmp_path / "bounded-child.ps1"
    child.write_text(
        "param($PidPath, $HeartbeatPath)\n"
        "[IO.File]::WriteAllText($PidPath, [string]$PID)\n"
        "while ($true) {\n"
        "  [IO.File]::WriteAllText($HeartbeatPath, [string][DateTime]::UtcNow.Ticks)\n"
        "  Start-Sleep -Milliseconds 50\n"
        "}\n",
        encoding="ascii",
    )
    parent = tmp_path / "bounded-parent.ps1"
    parent.write_text(
        "param($Engine, $Child, $PidPath, $HeartbeatPath)\n"
        "& $Engine -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        "-File $Child -PidPath $PidPath -HeartbeatPath $HeartbeatPath\n",
        encoding="ascii",
    )
    successful_child = tmp_path / "successful-child.py"
    successful_child.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "pid_path, heartbeat_path = map(Path, sys.argv[1:])\n"
        "pid_path.write_text(str(os.getpid()), encoding='ascii')\n"
        "while True:\n"
        "    heartbeat_path.write_text(str(time.time_ns()), encoding='ascii')\n"
        "    time.sleep(0.05)\n",
        encoding="ascii",
    )
    atomic_parent = tmp_path / "atomic-parent.ps1"
    atomic_parent.write_text(
        "param($Contract,$Python,$Child,$PidPath,$HeartbeatPath,$StdoutPath,"
        "$StderrPath,$ReadyPath)\n"
        ". $Contract\n"
        "$job = [XpjTestProcessJob]::new()\n"
        "$targetPid = $job.StartProcess($Python,@($Child,$PidPath,$HeartbeatPath),"
        "$StdoutPath,$StderrPath)\n"
        "[IO.File]::WriteAllText($ReadyPath,[string]$targetPid)\n"
        "while ($true) { Start-Sleep -Seconds 1 }\n",
        encoding="ascii",
    )
    probe = tmp_path / "bounded-process.ps1"
    probe.write_text(
        "param($Contract, $Port, $Target, $Parent, $Child, $PidPath, $HeartbeatPath, "
        "$Python, $SuccessfulChild, $CommitPid, $CommitHeartbeat, $AtomicStdout, "
        "$AtomicStderr)\n"
        ". $Contract\n"
        "Invoke-XpjTestPostgresLifecycleLocked -Port $Port -TimeoutSeconds 2 -Operation {\n"
        "  $result = Invoke-XpjTestPostgresBoundedProcess -FilePath $Target "
        "-ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy',"
        "'Bypass','-File',$Parent,'-Engine',$Target,'-Child',$Child,'-PidPath',$PidPath,"
        "'-HeartbeatPath',$HeartbeatPath) -TimeoutSeconds 3\n"
        "  if (-not $result.TimedOut) { throw 'child process did not time out' }\n"
        "}\n"
        "if (-not (Test-Path -LiteralPath $PidPath)) { throw 'grandchild never started' }\n"
        "$heartbeat = Get-Content -LiteralPath $HeartbeatPath -Raw\n"
        "Start-Sleep -Milliseconds 300\n"
        "$childPid = [int](Get-Content -LiteralPath $PidPath -Raw)\n"
        "if (Get-Process -Id $childPid -ErrorAction SilentlyContinue) { "
        "throw 'timed-out process tree survived' }\n"
        "if ((Get-Content -LiteralPath $HeartbeatPath -Raw) -cne $heartbeat) { "
        "throw 'timed-out grandchild is still writing' }\n"
        "$atomicJob = [XpjTestProcessJob]::new()\n"
        "[void]$atomicJob.StartProcess($Python, "
        "@($SuccessfulChild,$CommitPid,$CommitHeartbeat),$AtomicStdout,$AtomicStderr)\n"
        "$pidDeadline = [DateTime]::UtcNow.AddSeconds(5)\n"
        "while (-not (Test-Path -LiteralPath $CommitPid) -and "
        "[DateTime]::UtcNow -lt $pidDeadline) { Start-Sleep -Milliseconds 50 }\n"
        "$deferredPid = [int](Get-Content -LiteralPath $CommitPid -Raw)\n"
        "$deferredProcess = Get-Process -Id $deferredPid -ErrorAction Stop\n"
        "if (-not $atomicJob.ContainsProcess($deferredProcess.Handle)) { "
        "throw 'atomically started process escaped its job' }\n"
        "$atomicJob.Dispose()\n"
        "$exitDeadline = [DateTime]::UtcNow.AddSeconds(5)\n"
        "while ((Get-Process -Id $deferredPid -ErrorAction SilentlyContinue) -and "
        "[DateTime]::UtcNow -lt $exitDeadline) { Start-Sleep -Milliseconds 50 }\n"
        "if (Get-Process -Id $deferredPid -ErrorAction SilentlyContinue) { "
        "throw 'uncommitted successful descendant survived job close' }\n"
        "Remove-Item -LiteralPath $CommitPid,$CommitHeartbeat -Force\n"
        "$committedJob = [XpjTestProcessJob]::new()\n"
        "[void]$committedJob.StartProcess($Python, "
        "@($SuccessfulChild,$CommitPid,$CommitHeartbeat),$AtomicStdout,$AtomicStderr)\n"
        "$pidDeadline = [DateTime]::UtcNow.AddSeconds(5)\n"
        "while (-not (Test-Path -LiteralPath $CommitPid) -and "
        "[DateTime]::UtcNow -lt $pidDeadline) { Start-Sleep -Milliseconds 50 }\n"
        "$committedPid = [int](Get-Content -LiteralPath $CommitPid -Raw)\n"
        "try {\n"
        "  $committedJob.PreserveProcessesOnClose()\n"
        "  $committedJob.Dispose()\n"
        "  Start-Sleep -Milliseconds 300\n"
        "  if (-not (Get-Process -Id $committedPid -ErrorAction SilentlyContinue)) { "
        "throw 'explicitly committed descendant was killed' }\n"
        "}\n"
        "finally { Stop-Process -Id $committedPid -Force -ErrorAction SilentlyContinue }\n"
        "Invoke-XpjTestPostgresLifecycleLocked -Port $Port -TimeoutSeconds 2 -Operation {}\n",
        encoding="ascii",
    )
    for index, engine in enumerate(powershell_contract_engines()):
        pid_path = tmp_path / f"bounded-child-{index}.pid"
        heartbeat_path = tmp_path / f"bounded-child-{index}.heartbeat"
        commit_pid_path = tmp_path / f"committed-child-{index}.pid"
        commit_heartbeat_path = tmp_path / f"committed-child-{index}.heartbeat"
        atomic_stdout_path = tmp_path / f"atomic-child-{index}.stdout"
        atomic_stderr_path = tmp_path / f"atomic-child-{index}.stderr"
        started = time.monotonic()
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-Port",
                str(_free_local_port()),
                "-Target",
                engine,
                "-Parent",
                str(parent),
                "-Child",
                str(child),
                "-PidPath",
                str(pid_path),
                "-HeartbeatPath",
                str(heartbeat_path),
                "-Python",
                sys.executable,
                "-SuccessfulChild",
                str(successful_child),
                "-CommitPid",
                str(commit_pid_path),
                "-CommitHeartbeat",
                str(commit_heartbeat_path),
                "-AtomicStdout",
                str(atomic_stdout_path),
                "-AtomicStderr",
                str(atomic_stderr_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert time.monotonic() - started < 10

        hard_pid_path = tmp_path / f"hard-death-child-{index}.pid"
        hard_heartbeat_path = tmp_path / f"hard-death-child-{index}.heartbeat"
        hard_stdout_path = tmp_path / f"hard-death-child-{index}.stdout"
        hard_stderr_path = tmp_path / f"hard-death-child-{index}.stderr"
        hard_ready_path = tmp_path / f"hard-death-parent-{index}.ready"
        launcher = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(atomic_parent),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-Python",
                sys.executable,
                "-Child",
                str(successful_child),
                "-PidPath",
                str(hard_pid_path),
                "-HeartbeatPath",
                str(hard_heartbeat_path),
                "-StdoutPath",
                str(hard_stdout_path),
                "-StderrPath",
                str(hard_stderr_path),
                "-ReadyPath",
                str(hard_ready_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        hard_child_pid: int | None = None
        try:
            deadline = time.monotonic() + 10
            while not hard_ready_path.exists() and time.monotonic() < deadline:
                assert launcher.poll() is None, launcher.communicate(timeout=2)[0]
                time.sleep(0.05)
            assert hard_ready_path.exists()
            hard_child_pid = int(hard_ready_path.read_text(encoding="ascii"))
            assert _windows_process_is_running(hard_child_pid)
            launcher.kill()
            launcher.communicate(timeout=10)
            deadline = time.monotonic() + 10
            while _windows_process_is_running(hard_child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _windows_process_is_running(hard_child_pid)
            hard_child_pid = None
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.communicate(timeout=10)
            if hard_child_pid is not None:
                with contextlib.suppress(OSError):
                    os.kill(hard_child_pid, 15)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")
def test_python_consumer_exits_when_its_exact_parent_dies(tmp_path: Path) -> None:
    child = tmp_path / "watch-parent-child.py"
    child.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from scripts.test_pg_contract import start_windows_parent_watchdog\n"
        "start_windows_parent_watchdog(label='runtime contract child')\n"
        "Path(sys.argv[2]).write_text(str(os.getpid()), encoding='ascii')\n"
        "while True:\n"
        "    time.sleep(0.1)\n",
        encoding="ascii",
    )
    parent = tmp_path / "watch-parent.py"
    parent.write_text(
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])\n"
        "Path(sys.argv[4]).write_text(str(os.getpid()), encoding='ascii')\n"
        "while True:\n"
        "    time.sleep(0.1)\n",
        encoding="ascii",
    )
    child_ready = tmp_path / "child.ready"
    parent_ready = tmp_path / "parent.ready"
    backend_root = Path(__file__).resolve().parents[2]
    launcher = subprocess.Popen(
        [
            sys.executable,
            str(parent),
            str(child),
            str(backend_root),
            str(child_ready),
            str(parent_ready),
        ],
        cwd=backend_root,
    )
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 10
        while (
            (not child_ready.exists() or not parent_ready.exists())
            and time.monotonic() < deadline
        ):
            assert launcher.poll() is None
            time.sleep(0.05)
        assert child_ready.exists()
        child_pid = int(child_ready.read_text(encoding="ascii"))
        assert _windows_process_is_running(child_pid)
        parent_pid = int(parent_ready.read_text(encoding="ascii"))
        os.kill(parent_pid, 15)
        launcher.wait(timeout=10)
        deadline = time.monotonic() + 10
        while _windows_process_is_running(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _windows_process_is_running(child_pid)
        child_pid = None
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)
        if child_pid is not None:
            with contextlib.suppress(OSError):
                os.kill(child_pid, 15)
