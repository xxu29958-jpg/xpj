from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    TEST_POSTGRES_CONTRACT,
    _free_local_port,
    _open_exact_windows_process,
    _terminate_exact_windows_process,
    _windows_process_handle_is_running,
)
from _powershell_contract import powershell_contract_engines

from scripts.test_pg_protected_file import (
    assert_protected_authority_file,
    write_protected_utf8_file,
)

pytestmark = pytest.mark.packaging_resource("postgres_cluster")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_bounded_process_without_standard_input_does_not_create_a_pipe(
    tmp_path: Path,
) -> None:
    child = tmp_path / "stdin-file-type.py"
    child.write_text(
        "import ctypes\n"
        "handle = ctypes.windll.kernel32.GetStdHandle(-10)\n"
        "print(ctypes.windll.kernel32.GetFileType(handle))\n",
        encoding="ascii",
    )
    probe = tmp_path / "no-standard-input.ps1"
    probe.write_text(
        "param($Contract, $Python, $Child)\n"
        ". $Contract\n"
        "$withoutInput = Invoke-XpjTestPostgresBoundedProcess "
        "-FilePath $Python -ArgumentList @($Child) -TimeoutSeconds 5\n"
        "if ($withoutInput.TimedOut -or $withoutInput.ExitCode -ne 0) {\n"
        "  throw 'child failed without stdin'\n"
        "}\n"
        "if ($withoutInput.Output.Trim() -cne '2') {\n"
        "  throw \"omitted stdin was not NUL: $($withoutInput.Output)\"\n"
        "}\n"
        "$withEmptyInput = Invoke-XpjTestPostgresBoundedProcess "
        "-FilePath $Python -ArgumentList @($Child) -StandardInput '' "
        "-TimeoutSeconds 5\n"
        "if ($withEmptyInput.TimedOut -or $withEmptyInput.ExitCode -ne 0) {\n"
        "  throw 'child failed with explicit empty stdin'\n"
        "}\n"
        "if ($withEmptyInput.Output.Trim() -cne '3') {\n"
        "  throw \"explicit stdin was not a pipe: $($withEmptyInput.Output)\"\n"
        "}\n",
        encoding="ascii",
    )

    for engine in powershell_contract_engines():
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
                "-Python",
                sys.executable,
                "-Child",
                str(child),
            ],
            cwd=tmp_path,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_postmaster_generation_retains_one_exact_process_handle(tmp_path: Path) -> None:
    probe = tmp_path / "postmaster-generation.ps1"
    probe.write_text(
        "param($Contract)\n"
        ". $Contract\n"
        "$source = Get-Process -Id $PID -ErrorAction Stop\n"
        "try {\n"
        "  $epoch = ([DateTimeOffset]$source.StartTime).ToUnixTimeSeconds()\n"
        "}\n"
        "finally { $source.Dispose() }\n"
        "$record = [pscustomobject]@{ ProcessId = $PID; StartEpoch = $epoch }\n"
        "$matching = Get-XpjTestPostgresProcessGeneration $record\n"
        "if ($matching.State -cne 'matching' -or $null -eq $matching.Process) {\n"
        "  throw 'matching process generation did not retain exact authority'\n"
        "}\n"
        "try {\n"
        "  [void]$matching.Process.Handle\n"
        "  $matching.Process.Refresh()\n"
        "  if ($matching.Process.HasExited -or $matching.Process.Id -ne $PID) {\n"
        "    throw 'retained process authority changed generation'\n"
        "  }\n"
        "}\n"
        "finally { $matching.Process.Dispose() }\n"
        "$reusedRecord = [pscustomobject]@{ ProcessId = $PID; StartEpoch = 1 }\n"
        "$reused = Get-XpjTestPostgresProcessGeneration $reusedRecord\n"
        "if ($reused.State -cne 'reused' -or $null -ne $reused.Process) {\n"
        "  throw 'reused process generation leaked a process handle'\n"
        "}\n"
        "$missingRecord = [pscustomobject]@{ ProcessId = 2147483647; StartEpoch = 1 }\n"
        "$missing = Get-XpjTestPostgresProcessGeneration $missingRecord\n"
        "if ($missing.State -cne 'missing' -or $null -ne $missing.Process) {\n"
        "  throw 'missing process generation returned authority'\n"
        "}\n",
        encoding="ascii",
    )

    for engine in powershell_contract_engines():
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
            ],
            cwd=tmp_path,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_standard_input_failure_retains_child_in_job_until_cleanup(tmp_path: Path) -> None:
    child = tmp_path / "close-stdin-child.py"
    child.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from scripts.test_pg_windows_contract import (\n"
        "    _windows_process_created_filetime, _windows_process_kernel32,\n"
        ")\n"
        "identity = Path(sys.argv[1])\n"
        "kernel32 = _windows_process_kernel32()\n"
        "created = _windows_process_created_filetime(kernel32, kernel32.GetCurrentProcess())\n"
        "payload = json.dumps({'pid': os.getpid(), 'created': created})\n"
        "temporary = identity.with_name(f'.{identity.name}.{os.getpid()}.tmp')\n"
        "temporary.write_text(payload, encoding='ascii')\n"
        "temporary.replace(identity)\n"
        "os.close(0)\n"
        "while True:\n"
        "    time.sleep(0.1)\n",
        encoding="ascii",
    )
    probe = tmp_path / "fail-standard-input.ps1"
    probe.write_text(
        "param($Contract,$Python,$Child,$Identity,$BackendRoot,$FailureReady,"
        "$Release,$StdoutPath,$StderrPath)\n"
        ". $Contract\n"
        "$job = [XpjTestProcessJob]::new()\n"
        "$failed = $false\n"
        "try {\n"
        "  [void](Start-XpjTestPostgresProtectedProcess -Job $job "
        "-FilePath $Python -ArgumentList @($Child,$Identity,$BackendRoot) "
        "-StdoutPath $StdoutPath -StderrPath $StderrPath "
        "-StandardInput ('x' * 16777216))\n"
        "}\n"
        "catch {\n"
        "  if ($_.Exception.ToString() -notmatch 'standard input|pipe') { throw }\n"
        "  $failed = $true\n"
        "  [IO.File]::WriteAllText($FailureReady,'failed',[Text.Encoding]::ASCII)\n"
        "  while (-not (Test-Path -LiteralPath $Release)) { "
        "Start-Sleep -Milliseconds 25 }\n"
        "}\n"
        "finally {\n"
        "  $job.Dispose()\n"
        "  Remove-XpjTestPostgresProcessOutput -Path @($StdoutPath,$StderrPath)\n"
        "}\n"
        "if (-not $failed) { throw 'stdin write unexpectedly succeeded' }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        identity_path = tmp_path / f"stdin-child-{index}.json"
        failure_ready = tmp_path / f"stdin-failure-{index}.ready"
        release_path = tmp_path / f"stdin-failure-{index}.release"
        stdout_path = tmp_path / f"stdin-failure-{index}.stdout"
        stderr_path = tmp_path / f"stdin-failure-{index}.stderr"
        process = subprocess.Popen(
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
                "-Python",
                sys.executable,
                "-Child",
                str(child),
                "-Identity",
                str(identity_path),
                "-BackendRoot",
                str(Path(__file__).resolve().parents[2]),
                "-FailureReady",
                str(failure_ready),
                "-Release",
                str(release_path),
                "-StdoutPath",
                str(stdout_path),
                "-StderrPath",
                str(stderr_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        kernel32: object | None = None
        child_handle: object | None = None
        try:
            deadline = time.monotonic() + 10
            while (
                (not identity_path.exists() or not failure_ready.exists())
                and time.monotonic() < deadline
            ):
                assert process.poll() is None, process.communicate(timeout=2)[0]
                time.sleep(0.025)
            assert identity_path.exists()
            assert failure_ready.exists()
            identity = json.loads(identity_path.read_text(encoding="ascii"))
            kernel32, child_handle = _open_exact_windows_process(
                int(identity["pid"]),
                int(identity["created"]),
            )
            assert _windows_process_handle_is_running(kernel32, child_handle)
            release_path.write_text("release", encoding="ascii")
            output = process.communicate(timeout=15)[0]
            assert process.returncode == 0, output
            assert kernel32.WaitForSingleObject(child_handle, 10_000) == 0
            assert not stdout_path.exists()
            assert not stderr_path.exists()
        finally:
            release_path.write_text("release", encoding="ascii")
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
            if kernel32 is not None and child_handle is not None:
                _terminate_exact_windows_process(kernel32, child_handle)
                kernel32.CloseHandle(child_handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows restricted token")
def test_restricted_process_preserves_user_and_drops_admin_groups(
    tmp_path: Path,
) -> None:
    child = tmp_path / "restricted-child.ps1"
    child.write_text(
        "param($ResultPath)\n"
        "$identity = [Security.Principal.WindowsIdentity]::GetCurrent()\n"
        "$principal = [Security.Principal.WindowsPrincipal]::new($identity)\n"
        "$isAdmin = $principal.IsInRole("
        "[Security.Principal.WindowsBuiltInRole]::Administrator)\n"
        "[IO.File]::WriteAllText($ResultPath, "
        "($identity.User.Value + '|' + $identity.Owner.Value + '|' + $isAdmin))\n",
        encoding="ascii",
    )
    probe = tmp_path / "restricted-process.ps1"
    probe.write_text(
        "param($Contract,$Engine,$Child,$ResultPath,$StdoutPath,$StderrPath)\n"
        ". $Contract\n"
        "$expectedUser = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value\n"
        "$job = [XpjTestProcessJob]::new()\n"
        "try {\n"
        "  [void](Start-XpjTestPostgresProtectedProcess -Job $job "
        "-FilePath $Engine -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive',"
        "'-ExecutionPolicy','Bypass','-File',$Child,'-ResultPath',$ResultPath) "
        "-StdoutPath $StdoutPath -StderrPath $StderrPath "
        "-RestrictWindowsAdminAuthority)\n"
        "  if (-not $job.WaitForStartedProcess(5000)) { "
        "throw 'restricted child did not exit' }\n"
        "  if ($job.GetStartedProcessExitCode() -ne 0) { "
        "throw 'restricted child failed' }\n"
        "}\n"
        "finally { $job.Dispose() }\n"
        "$parts = ([IO.File]::ReadAllText($ResultPath)).Split('|')\n"
        "if ($parts.Count -ne 3 -or $parts[0] -cne $expectedUser -or "
        "$parts[2] -cne 'False') { throw 'restricted token contract mismatch' }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        result_path = tmp_path / f"restricted-{index}.txt"
        stdout_path = tmp_path / f"restricted-{index}.stdout"
        stderr_path = tmp_path / f"restricted-{index}.stderr"
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
                "-Engine",
                engine,
                "-Child",
                str(child),
                "-ResultPath",
                str(result_path),
                "-StdoutPath",
                str(stdout_path),
                "-StderrPath",
                str(stderr_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        parts = result_path.read_text(encoding="utf-8").split("|")
        assert len(parts) == 3
        assert parts[0]
        assert parts[1]
        assert parts[2] == "False"
        for output_path in (stdout_path, stderr_path):
            assert_protected_authority_file(
                output_path.resolve(),
                label="Restricted PostgreSQL process output",
            )


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
        "$targetPid = Start-XpjTestPostgresProtectedProcess -Job $job "
        "-FilePath $Python -ArgumentList @($Child,$PidPath,$HeartbeatPath) "
        "-StdoutPath $StdoutPath -StderrPath $StderrPath\n"
        "$target = Get-Process -Id $targetPid -ErrorAction Stop\n"
        "try { $created = $target.StartTime.ToUniversalTime().ToFileTimeUtc() } "
        "finally { $target.Dispose() }\n"
        "$readyTemp = $ReadyPath + '.' + $PID + '.tmp'\n"
        "$readyPayload = @{ pid = $targetPid; created = $created } "
        "| ConvertTo-Json -Compress\n"
        "[IO.File]::WriteAllText($readyTemp,$readyPayload,[Text.Encoding]::ASCII)\n"
        "[IO.File]::Move($readyTemp,$ReadyPath)\n"
        "while ($true) { Start-Sleep -Seconds 1 }\n",
        encoding="ascii",
    )
    probe = tmp_path / "bounded-process.ps1"
    probe.write_text(
        "param($Contract, $Port, $Target, $Parent, $Child, $PidPath, $HeartbeatPath, "
        "$Python, $SuccessfulChild, $CommitPid, $CommitHeartbeat, $AtomicStdout, "
        "$AtomicStderr)\n"
        ". $Contract\n"
        "Invoke-XpjTestPostgresLifecycleLocked -Port $Port "
        "-DataDirectory ($PidPath + '.cluster') -TimeoutSeconds 2 -Operation {\n"
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
        "[void](Start-XpjTestPostgresProtectedProcess -Job $atomicJob "
        "-FilePath $Python "
        "-ArgumentList @($SuccessfulChild,$CommitPid,$CommitHeartbeat) "
        "-StdoutPath $AtomicStdout -StderrPath $AtomicStderr)\n"
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
        "Remove-XpjTestPostgresProcessOutput "
        "-Path @($AtomicStdout,$AtomicStderr)\n"
        "$committedJob = [XpjTestProcessJob]::new()\n"
        "[void](Start-XpjTestPostgresProtectedProcess -Job $committedJob "
        "-FilePath $Python "
        "-ArgumentList @($SuccessfulChild,$CommitPid,$CommitHeartbeat) "
        "-StdoutPath $AtomicStdout -StderrPath $AtomicStderr)\n"
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
        "finally {\n"
        "  $committedProcess = Get-Process -Id $committedPid -ErrorAction SilentlyContinue\n"
        "  if ($null -ne $committedProcess) {\n"
        "    Stop-Process -InputObject $committedProcess -Force -ErrorAction Stop\n"
        "    if (-not $committedProcess.WaitForExit(2000)) { "
        "throw 'committed descendant did not stop' }\n"
        "    $committedProcess.Dispose()\n"
        "  }\n"
        "}\n"
        "Invoke-XpjTestPostgresLifecycleLocked -Port $Port "
        "-DataDirectory ($PidPath + '.cluster') -TimeoutSeconds 2 -Operation {}\n",
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
        for output_path in (atomic_stdout_path, atomic_stderr_path):
            assert_protected_authority_file(
                output_path.resolve(),
                label="Atomic PostgreSQL process output",
            )

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
        hard_kernel32: object | None = None
        hard_child_handle: object | None = None
        try:
            deadline = time.monotonic() + 10
            while not hard_ready_path.exists() and time.monotonic() < deadline:
                assert launcher.poll() is None, launcher.communicate(timeout=2)[0]
                time.sleep(0.05)
            assert hard_ready_path.exists()
            hard_ready = json.loads(hard_ready_path.read_text(encoding="ascii"))
            hard_kernel32, hard_child_handle = _open_exact_windows_process(
                int(hard_ready["pid"]),
                int(hard_ready["created"]),
            )
            assert _windows_process_handle_is_running(hard_kernel32, hard_child_handle)
            launcher.kill()
            launcher.communicate(timeout=10)
            assert hard_kernel32.WaitForSingleObject(hard_child_handle, 10_000) == 0
            for output_path in (hard_stdout_path, hard_stderr_path):
                assert_protected_authority_file(
                    output_path.resolve(),
                    label="Hard-death PostgreSQL process output",
                )
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.communicate(timeout=10)
            if hard_kernel32 is not None and hard_child_handle is not None:
                _terminate_exact_windows_process(hard_kernel32, hard_child_handle)
                hard_kernel32.CloseHandle(hard_child_handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")
def test_python_consumer_exits_when_its_declared_parent_authority_dies(
    tmp_path: Path,
) -> None:
    child = tmp_path / "watch-parent-child.py"
    child.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from scripts.test_pg_contract import (\n"
        "    EPHEMERAL_SERVICE_AUTHORITY, TEST_CLUSTER_AUTHORITY_ENV,\n"
        "    TEST_POSTGRES_CREDENTIAL_FILE_ENV, start_windows_parent_watchdog,\n"
        "    test_postgres_credential_environment,\n"
        "    WINDOWS_PARENT_AUTHORITY_CREATED_ENV,\n"
        "    WINDOWS_PARENT_AUTHORITY_PID_ENV,\n"
        ")\n"
        "from scripts.test_pg_protected_reader import _open_windows_protected_read_descriptor\n"
        "from scripts.test_pg_windows_contract import (\n"
        "    _windows_process_created_filetime, _windows_process_kernel32,\n"
        ")\n"
        "ready = Path(sys.argv[2])\n"
        "credential = Path(sys.argv[3])\n"
        "database_url = 'postgresql+psycopg://postgres@127.0.0.1:5432/xpj_test'\n"
        "os.environ['CI'] = 'true'\n"
        "os.environ[TEST_CLUSTER_AUTHORITY_ENV] = EPHEMERAL_SERVICE_AUTHORITY\n"
        "os.environ[TEST_POSTGRES_CREDENTIAL_FILE_ENV] = str(credential)\n"
        "with test_postgres_credential_environment(database_url, os.environ) as passfile:\n"
        "    descriptor = _open_windows_protected_read_descriptor(\n"
        "        passfile, label='Hard-exit passfile'\n"
        "    )\n"
        "    try:\n"
        "        kernel32 = _windows_process_kernel32()\n"
        "        created = _windows_process_created_filetime(\n"
        "            kernel32, kernel32.GetCurrentProcess()\n"
        "        )\n"
        "        authority_pid = int(os.environ[WINDOWS_PARENT_AUTHORITY_PID_ENV])\n"
        "        authority_created = int(os.environ[WINDOWS_PARENT_AUTHORITY_CREATED_ENV])\n"
        "        start_windows_parent_watchdog(label='runtime contract child')\n"
        "        sys.stderr.close()\n"
        "        payload = json.dumps(\n"
        "            {'pid': os.getpid(), 'created': created, 'passfile': str(passfile),\n"
        "             'authority_pid': authority_pid,\n"
        "             'authority_created': authority_created}\n"
        "        )\n"
        "        ready_temp = ready.with_name(f'.{ready.name}.{os.getpid()}.tmp')\n"
        "        ready_temp.write_text(payload, encoding='utf-8')\n"
        "        os.replace(ready_temp, ready)\n"
        "        while True:\n"
        "            time.sleep(0.1)\n"
        "    finally:\n"
        "        os.close(descriptor)\n",
        encoding="ascii",
    )
    parent = tmp_path / "watch-parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from scripts.test_pg_contract import bind_windows_child_authority\n"
        "environment = __import__('os').environ.copy()\n"
        "bind_windows_child_authority(environment)\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]],\n"
        "    env=environment,\n"
        ")\n"
        "while True:\n"
        "    time.sleep(0.1)\n",
        encoding="ascii",
    )
    child_ready = tmp_path / "child.ready"
    credential_authority = tmp_path / ".xpj-test-postgres-password"
    write_protected_utf8_file(
        credential_authority,
        f"{'c' * 43}\n",
        label="Parent-death PostgreSQL credential authority",
    )
    backend_root = Path(__file__).resolve().parents[2]
    launcher = subprocess.Popen(
        [
            sys.executable,
            str(parent),
            str(child),
            str(backend_root),
            str(child_ready),
            str(credential_authority),
        ],
        cwd=backend_root,
    )
    child_kernel32: object | None = None
    child_handle: object | None = None
    authority_kernel32: object | None = None
    authority_handle: object | None = None
    derived_passfile: Path | None = None
    try:
        deadline = time.monotonic() + 10
        while not child_ready.exists() and time.monotonic() < deadline:
            assert launcher.poll() is None
            time.sleep(0.05)
        assert child_ready.exists()
        ready = json.loads(child_ready.read_text(encoding="utf-8"))
        derived_passfile = Path(ready["passfile"])
        assert_protected_authority_file(
            derived_passfile.resolve(),
            label="Hard-exit passfile",
        )
        child_kernel32, child_handle = _open_exact_windows_process(
            int(ready["pid"]),
            int(ready["created"]),
        )
        assert _windows_process_handle_is_running(child_kernel32, child_handle)
        authority_kernel32, authority_handle = _open_exact_windows_process(
            int(ready["authority_pid"]),
            int(ready["authority_created"]),
        )
        assert _windows_process_handle_is_running(
            authority_kernel32,
            authority_handle,
        )
        _terminate_exact_windows_process(authority_kernel32, authority_handle)
        assert authority_kernel32.WaitForSingleObject(authority_handle, 10_000) == 0
        assert child_kernel32.WaitForSingleObject(child_handle, 10_000) == 0, ready
        exit_code = ctypes.c_uint32()
        assert child_kernel32.GetExitCodeProcess(
            child_handle,
            ctypes.byref(exit_code),
        )
        assert exit_code.value == 3
        assert not derived_passfile.exists()
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)
        if child_kernel32 is not None and child_handle is not None:
            _terminate_exact_windows_process(child_kernel32, child_handle)
            child_kernel32.CloseHandle(child_handle)
        if authority_kernel32 is not None and authority_handle is not None:
            _terminate_exact_windows_process(authority_kernel32, authority_handle)
            authority_kernel32.CloseHandle(authority_handle)
