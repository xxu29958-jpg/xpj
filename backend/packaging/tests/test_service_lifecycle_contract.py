import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]

# A fresh two-core Windows CI VM has to cold-start Windows PowerShell 5.1 and
# compile the helper's native Add-Type substrate. Exact-head CI has exceeded
# both the former 45-second and 90-second success budgets while the bounded
# process tree remained live, so retain a finite 150-second inner deadline plus
# outer cleanup margin. This does not relax the 1,000/3,200 ms fail-closed
# probes below.
POWERSHELL_51_COLD_START_TIMEOUT_MS = 150_000
POWERSHELL_51_HARNESS_CLEANUP_MARGIN_SECONDS = 90
POWERSHELL_51_HELPER_INVOCATIONS_PER_MULTI_HARNESS = 6
POWERSHELL_51_COLD_START_HARNESS_TIMEOUT_SECONDS = (
    POWERSHELL_51_COLD_START_TIMEOUT_MS // 1000 + POWERSHELL_51_HARNESS_CLEANUP_MARGIN_SECONDS
)
POWERSHELL_51_MULTI_SCENARIO_HARNESS_TIMEOUT_SECONDS = (
    POWERSHELL_51_HELPER_INVOCATIONS_PER_MULTI_HARNESS * POWERSHELL_51_COLD_START_TIMEOUT_MS // 1000
    + POWERSHELL_51_HARNESS_CLEANUP_MARGIN_SECONDS
)
SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_STATUS = 0x0004
DELETE_SERVICE_ACCESS = 0x00010000
ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_MARKED_FOR_DELETE = 1072


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _ps_literal(path: str | Path) -> str:
    return str(path).replace("'", "''")


def _powershell_function_loader(source: Path, function_name: str) -> str:
    return f"""
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{_ps_literal(source)}',
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {{ throw 'source parse failed' }}
$functionAst = $ast.FindAll({{
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -ceq '{function_name}'
}}, $true) | Select-Object -First 1
if ($null -eq $functionAst) {{ throw 'missing production function: {function_name}' }}
Invoke-Expression $functionAst.Extent.Text
"""


def _windows_scm_api():
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenSCManagerW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.DeleteService.argtypes = [wintypes.HANDLE]
    advapi32.DeleteService.restype = wintypes.BOOL
    advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi32.CloseServiceHandle.restype = wintypes.BOOL
    return ctypes, advapi32


def _open_scm_manager(ctypes, advapi32):
    manager = advapi32.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not manager:
        raise ctypes.WinError(ctypes.get_last_error())
    return manager


def _assert_scm_probe_services_absent(service_names: list[str]) -> None:
    ctypes, advapi32 = _windows_scm_api()
    manager = _open_scm_manager(ctypes, advapi32)
    try:
        for service_name in service_names:
            handle = advapi32.OpenServiceW(
                manager,
                service_name,
                SERVICE_QUERY_STATUS,
            )
            if handle:
                advapi32.CloseServiceHandle(handle)
                raise AssertionError(f"refusing to reuse pre-existing SCM probe: {service_name}")
            error = ctypes.get_last_error()
            if error != ERROR_SERVICE_DOES_NOT_EXIST:
                raise ctypes.WinError(error)
    finally:
        advapi32.CloseServiceHandle(manager)


def _delete_scm_probe_service(ctypes, advapi32, manager, service_name: str) -> None:
    handle = advapi32.OpenServiceW(
        manager,
        service_name,
        DELETE_SERVICE_ACCESS | SERVICE_QUERY_STATUS,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in {ERROR_SERVICE_DOES_NOT_EXIST, ERROR_SERVICE_MARKED_FOR_DELETE}:
            return
        raise ctypes.WinError(error)
    try:
        if not advapi32.DeleteService(handle):
            error = ctypes.get_last_error()
            if error != ERROR_SERVICE_MARKED_FOR_DELETE:
                raise ctypes.WinError(error)
    finally:
        advapi32.CloseServiceHandle(handle)


def _scm_probe_service_is_present(ctypes, advapi32, manager, service_name: str) -> bool:
    handle = advapi32.OpenServiceW(manager, service_name, SERVICE_QUERY_STATUS)
    if handle:
        advapi32.CloseServiceHandle(handle)
        return True
    error = ctypes.get_last_error()
    if error == ERROR_SERVICE_DOES_NOT_EXIST:
        return False
    if error == ERROR_SERVICE_MARKED_FOR_DELETE:
        return True
    raise ctypes.WinError(error)


def _cleanup_scm_probe_services(service_names: list[str]) -> None:
    ctypes, advapi32 = _windows_scm_api()
    manager = _open_scm_manager(ctypes, advapi32)
    try:
        for service_name in reversed(service_names):
            _delete_scm_probe_service(ctypes, advapi32, manager, service_name)

        remaining = set(service_names)
        deadline = time.monotonic() + 20
        while remaining and time.monotonic() < deadline:
            remaining = {
                service_name
                for service_name in remaining
                if _scm_probe_service_is_present(
                    ctypes,
                    advapi32,
                    manager,
                    service_name,
                )
            }
            if remaining:
                time.sleep(0.1)
        assert not remaining, f"SCM probe cleanup did not settle: {sorted(remaining)}"
    finally:
        advapi32.CloseServiceHandle(manager)


def test_database_tools_are_bounded_under_powershell_51_and_7(tmp_path: Path) -> None:
    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    generation_program_adapter = PACKAGING / "windows_database_generation_program_adapter.ps1"
    generation_program_execution = PACKAGING / "windows_database_generation_program_execution.ps1"
    database_safety_source = database_safety.read_text(encoding="utf-8-sig")
    assert "WriteStandardInputAsync" in database_safety_source
    assert "$nativeProcess.WriteStandardInputAsync(" in database_safety_source
    assert "$nativeProcess.CloseStandardInput()" in database_safety_source
    assert "StandardInput.FlushAsync" not in database_safety_source
    assert "new StreamWriter(" not in database_safety_source
    assert "FileAccess.Write,\n                1,\n                false" in database_safety_source
    assert "-InputWriteTask $inputTaskForCleanup" in database_safety_source
    assert (
        """$inputTaskForCleanup = $stdinWriteTask
            if ($null -ne $inputFailure) {
                $inputTaskForCleanup = $null
            }
            try {
                Stop-TicketboxBoundedNativeProcessTree `
                    -NativeProcess $nativeProcess `
                    -SettlementMilliseconds $TerminationSettlementMilliseconds `
                    -InputWriteTask $inputTaskForCleanup"""
        in database_safety_source
    )
    assert "$InputWriteTask.IsCompleted" in database_safety_source
    assert "Array.Clear(bytes, 0, byteCount);" in database_safety_source
    assert "Array.Clear(bytes, 0, bytes.Length);" in database_safety_source
    assert (
        "[Parameter(Mandatory = $true)][AllowNull()]\n        [Threading.Tasks.Task]$InputWriteTask"
        in database_safety_source
    )
    surrogate_boundary_sha = hashlib.sha256(("x" * 4095 + "😀").encode()).hexdigest()
    flood_bytes = 1024 * 1024
    flood_script = tmp_path / "bounded-native-output-flood.py"
    flood_script.write_text(
        """import sys

size = int(sys.argv[1])
sys.stdout.buffer.write(b'O' * size)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(b'E' * size)
sys.stderr.buffer.flush()
""",
        encoding="utf-8",
    )
    environment_probe = tmp_path / "bounded-native-environment-probe.py"
    environment_probe.write_text(
        """import json
import os

print(json.dumps({
    "pg": sorted(
        [[name, value] for name, value in os.environ.items()
         if name.upper().startswith("PG")],
        key=lambda item: item[0].upper(),
    ),
    "sentinel": os.environ.get("TICKETBOX_C07_ENV_SENTINEL"),
    "has_pseudo": any(name.startswith("=") for name in os.environ),
}, separators=(",", ":")))
""",
        encoding="utf-8",
    )
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"bounded-native-{index}.ps1"
        harness.write_text(
            f"""
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(database_safety)}'
. '{_ps_literal(generation_program_adapter)}'
. '{_ps_literal(generation_program_execution)}'
$ambientPg = [ordered]@{{
    PGHOSTADDR = '203.0.113.8'
    pgService = 'ambient-service'
    PGSSLMODE = 'disable'
    PGOPTIONS = '-c search_path=ambient'
    PGTARGETSESSIONATTRS = 'read-only'
    PGDATESTYLE = 'SQL, DMY'
    PGPASSWORD = 'ambient-secret'
    PGPASSFILE = 'C:\\ambient\\.pgpass'
}}
foreach ($entry in $ambientPg.GetEnumerator()) {{
    [Environment]::SetEnvironmentVariable(
        [string]$entry.Key,
        [string]$entry.Value,
        [EnvironmentVariableTarget]::Process
    )
}}
[Environment]::SetEnvironmentVariable(
    'TICKETBOX_C07_ENV_SENTINEL',
    '保留-小票夹',
    [EnvironmentVariableTarget]::Process
)
$trustedPgPassFile = '{_ps_literal(tmp_path / "trusted-c07.pgpass")}'
    $isolatedEnvironment = New-TicketboxDatabaseGenerationHelperChildEnvironment `
    -PgPassFilePath $trustedPgPassFile
$isolatedEnvironment['=C:'] = 'C:\\ignored-current-directory'
$isolatedEnvironmentProbe = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('{_ps_literal(environment_probe)}') `
    -TimeoutMilliseconds 10000 `
    -Label 'isolated environment probe' `
    -ChildEnvironment $isolatedEnvironment
$inheritedEnvironmentProbe = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('{_ps_literal(environment_probe)}') `
    -TimeoutMilliseconds 10000 `
    -Label 'inherited environment probe'
$parentEnvironmentUnchanged = $true
foreach ($entry in $ambientPg.GetEnumerator()) {{
    if (
        [Environment]::GetEnvironmentVariable(
            [string]$entry.Key,
            [EnvironmentVariableTarget]::Process
        ) -cne [string]$entry.Value
    ) {{
        $parentEnvironmentUnchanged = $false
    }}
}}
$success = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(engine)}' `
    -Arguments @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '[Console]::Out.Write([Console]::In.ReadToEnd())') `
    -StandardInputText 'bounded input' `
    -TimeoutMilliseconds 10000 `
    -Label 'bounded success probe'
$emptyInput = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('-c', 'import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())') `
    -StandardInputText '' `
    -TimeoutMilliseconds 10000 `
    -Label 'empty input probe'
$unicodeBoundary = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('-c', 'import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())') `
    -StandardInputText (('x' * 4095) + ([string][char]0xD83D) + ([string][char]0xDE00)) `
    -TimeoutMilliseconds 10000 `
    -Label 'surrogate boundary probe'
$negativeExit = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(engine)}' `
    -Arguments @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'exit -1') `
    -TimeoutMilliseconds 10000 `
    -Label 'signed exit-code probe'
$flood = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('{_ps_literal(flood_script)}', '{flood_bytes}') `
    -TimeoutMilliseconds 10000 `
    -Label 'bounded output flood probe'
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$timedOut = $false
try {{
    Invoke-TicketboxBoundedNativeProcess `
        -FilePath '{_ps_literal(engine)}' `
        -Arguments @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30') `
        -TimeoutMilliseconds 1000 `
        -Label 'bounded timeout probe' | Out-Null
}}
catch {{
    $timedOut = $_.Exception.Message -like '*超过允许*'
}}
$watch.Stop()
if (-not $timedOut) {{ throw 'bounded process timeout was not enforced' }}
if ($watch.ElapsedMilliseconds -ge 10000) {{ throw 'bounded process timeout exceeded its kill budget' }}
$stdinWatch = [System.Diagnostics.Stopwatch]::StartNew()
$blockedInputTimedOut = $false
try {{
    Invoke-TicketboxBoundedNativeProcess `
        -FilePath '{_ps_literal(engine)}' `
        -Arguments @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 30') `
        -StandardInputText ('x' * 65536) `
        -TimeoutMilliseconds 1000 `
        -Label 'bounded blocked stdin probe' | Out-Null
}}
catch {{
    $blockedInputTimedOut = $_.Exception.Message -like '*超过允许*'
}}
$stdinWatch.Stop()
if (-not $blockedInputTimedOut) {{ throw 'blocked stdin escaped the process deadline' }}
if ($stdinWatch.ElapsedMilliseconds -ge 10000) {{ throw 'blocked stdin exceeded its kill budget' }}
[ordered]@{{
    ExitCode = $success.ExitCode
    Output = $success.StandardOutput
    EmptyInputLength = $emptyInput.StandardOutput.Length
    UnicodeBoundarySha = $unicodeBoundary.StandardOutput.Trim()
    NegativeExitCode = $negativeExit.ExitCode
    FloodExitCode = $flood.ExitCode
    FloodOutputLength = $flood.StandardOutput.Length
    FloodErrorLength = $flood.StandardError.Length
    TimedOut = $timedOut
    BlockedInputTimedOut = $blockedInputTimedOut
    IsolatedEnvironmentJson = $isolatedEnvironmentProbe.StandardOutput.Trim()
    InheritedEnvironmentJson = $inheritedEnvironmentProbe.StandardOutput.Trim()
    ParentEnvironmentUnchanged = $parentEnvironmentUnchanged
}} | ConvertTo-Json -Compress
""",
            encoding="utf-8-sig",
        )
        completed = subprocess.run(  # noqa: S603
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(harness),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert '"ExitCode":0' in completed.stdout
        assert '"Output":"bounded input"' in completed.stdout
        assert '"EmptyInputLength":0' in completed.stdout
        assert f'"UnicodeBoundarySha":"{surrogate_boundary_sha}"' in completed.stdout
        assert '"NegativeExitCode":-1' in completed.stdout
        assert '"FloodExitCode":0' in completed.stdout
        assert f'"FloodOutputLength":{flood_bytes}' in completed.stdout
        assert f'"FloodErrorLength":{flood_bytes}' in completed.stdout
        assert '"TimedOut":true' in completed.stdout
        assert '"BlockedInputTimedOut":true' in completed.stdout
        evidence = json.loads(completed.stdout.strip().splitlines()[-1])
        isolated = json.loads(evidence["IsolatedEnvironmentJson"])
        inherited = json.loads(evidence["InheritedEnvironmentJson"])
        assert isolated == {
            "pg": [["PGPASSFILE", str(tmp_path / "trusted-c07.pgpass")]],
            "sentinel": None,
            "has_pseudo": False,
        }
        inherited_pg = {name.upper(): value for name, value in inherited["pg"]}
        assert inherited_pg["PGHOSTADDR"] == "203.0.113.8"
        assert inherited_pg["PGSERVICE"] == "ambient-service"
        assert inherited_pg["PGPASSFILE"] == r"C:\ambient\.pgpass"
        assert inherited["sentinel"] == "保留-小票夹"
        assert evidence["ParentEnvironmentUnchanged"] is True


def test_bounded_native_process_kills_real_descendant_trees_on_all_failures(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows Job Object behavior contract")

    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    tree_script = tmp_path / "bounded-native-process-tree.py"
    tree_script.write_text(
        """import os
import subprocess
import sys
import time

pid_path = sys.argv[1]
marker_path = sys.argv[2]
mode = sys.argv[3]
depth = int(sys.argv[4])
with open(pid_path, "a", encoding="ascii") as pid_file:
    pid_file.write(str(os.getpid()) + "\\n")
    pid_file.flush()
    os.fsync(pid_file.fileno())

if depth > 0:
    child_stdin = subprocess.PIPE if mode == "stdin_failure" else None
    child = subprocess.Popen(
        [sys.executable, __file__, pid_path, marker_path, mode, str(depth - 1)],
        stdin=child_stdin,
        close_fds=True,
    )
    if mode == "stdin_failure":
        child.stdin.close()
    if mode == "detached":
        raise SystemExit(0)
    if mode == "stdin_failure" and depth == 2:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with open(pid_path, encoding="ascii") as pid_file:
                if len(pid_file.read().splitlines()) >= 3:
                    break
            time.sleep(0.01)
        sys.stdin.buffer.read()
    child.wait()
else:
    sys.stdout.write("grandchild inherited stdout\\n")
    sys.stdout.flush()
    while True:
        with open(marker_path, "a", encoding="ascii") as marker_file:
            marker_file.write("x")
            marker_file.flush()
            os.fsync(marker_file.fileno())
        time.sleep(0.01)
""",
        encoding="utf-8",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        timeout_pids = tmp_path / f"timeout-tree-{index}.pids"
        timeout_marker = tmp_path / f"timeout-tree-{index}.marker"
        stdin_pids = tmp_path / f"stdin-tree-{index}.pids"
        stdin_marker = tmp_path / f"stdin-tree-{index}.marker"
        injected_pids = tmp_path / f"injected-tree-{index}.pids"
        injected_marker = tmp_path / f"injected-tree-{index}.marker"
        harness = tmp_path / f"bounded-native-tree-{index}.ps1"
        harness.write_text(
            f"""
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(database_safety)}'

function Assert-TreeSettledAtReturn([string]$PidPath, [string]$MarkerPath) {{
    $pids = @(
        Get-Content -LiteralPath $PidPath -Encoding UTF8 -ErrorAction Stop |
            ForEach-Object {{ [int]$_ }}
    )
    if ($pids.Count -ne 3) {{
        throw "process tree did not start fully: pids=$($pids -join ',')"
    }}
    $processHandles = @(
        foreach ($processId in $pids) {{
            $candidate = $null
            $runningAtReturn = $false
            try {{
                $candidate = [Diagnostics.Process]::GetProcessById($processId)
                $null = $candidate.Handle
                $runningAtReturn = -not $candidate.WaitForExit(0)
            }}
            catch [System.ArgumentException] {{
            }}
            catch [System.InvalidOperationException] {{
            }}
            [pscustomobject]@{{
                ProcessId = $processId
                Process = $candidate
                RunningAtReturn = $runningAtReturn
            }}
        }}
    )
    try {{
        $runningAtReturn = @(
            $processHandles |
                Where-Object {{ $_.RunningAtReturn }} |
                ForEach-Object {{ $_.ProcessId }}
        )
        $before = (Get-Item -LiteralPath $MarkerPath -Force -ErrorAction Stop).Length
        Start-Sleep -Milliseconds 200
        $after = (Get-Item -LiteralPath $MarkerPath -Force -ErrorAction Stop).Length
        if ($after -ne $before) {{
            throw "descendant marker grew after wrapper return: before=$before after=$after"
        }}
        if ($runningAtReturn.Count -ne 0) {{
            throw "wrapper returned before process-tree signal: pids=$($pids -join ',') running=$($runningAtReturn -join ',')"
        }}
    }}
    finally {{
        $processHandles | ForEach-Object {{
            if ($null -ne $_.Process) {{
                $_.Process.Dispose()
            }}
        }}
    }}
}}

# Compile/JIT outside the measured hard-timeout cases.
$warmup = Invoke-TicketboxBoundedNativeProcess `
    -FilePath '{_ps_literal(sys.executable)}' `
    -Arguments @('-c', 'pass') `
    -TimeoutMilliseconds 5000 `
    -Label 'native job warmup'
if ($warmup.ExitCode -ne 0) {{ throw 'native job warmup failed' }}

$timeoutWatch = [Diagnostics.Stopwatch]::StartNew()
$timeoutKilled = $false
try {{
    Invoke-TicketboxBoundedNativeProcess `
        -FilePath '{_ps_literal(sys.executable)}' `
        -Arguments @('{_ps_literal(tree_script)}', '{_ps_literal(timeout_pids)}', '{_ps_literal(timeout_marker)}', 'detached', '2') `
        -TimeoutMilliseconds 1000 `
        -Label 'detached descendant timeout' | Out-Null
}}
catch {{
    $timeoutKilled = $_.Exception.Message -like '*超过允许*'
}}
$timeoutWatch.Stop()
if (-not $timeoutKilled) {{ throw 'detached descendant escaped timeout' }}
if ($timeoutWatch.ElapsedMilliseconds -ge 3000) {{ throw 'descendant pipe extended the absolute deadline' }}
Assert-TreeSettledAtReturn '{_ps_literal(timeout_pids)}' '{_ps_literal(timeout_marker)}'

$stdinWatch = [Diagnostics.Stopwatch]::StartNew()
$stdinKilled = $false
$stdinFailureMessage = ''
$stdinFailureWasDuplicated = $false
try {{
    Invoke-TicketboxBoundedNativeProcess `
        -FilePath '{_ps_literal(sys.executable)}' `
        -Arguments @('{_ps_literal(tree_script)}', '{_ps_literal(stdin_pids)}', '{_ps_literal(stdin_marker)}', 'stdin_failure', '2') `
        -StandardInputText (('x' * 65536) + ([string][char]0xD800)) `
        -TimeoutMilliseconds 10000 `
        -Label 'stdin descendant failure' | Out-Null
}}
catch {{
    $stdinFailureMessage = $_.Exception.Message
    $stdinFailureWasDuplicated =
        $_.Exception -is [TicketboxProcessTreeTerminationAggregateException]
    $stdinKilled = $stdinFailureMessage -notlike '*超过允许*'
}}
$stdinWatch.Stop()
if (-not $stdinKilled) {{ throw "stdin failure was converted into a timeout: $stdinFailureMessage" }}
if ($stdinFailureWasDuplicated) {{ throw 'stdin action failure was duplicated as a cleanup failure' }}
if ($stdinWatch.ElapsedMilliseconds -ge 3000) {{ throw 'stdin failure cleanup was not bounded' }}
Assert-TreeSettledAtReturn '{_ps_literal(stdin_pids)}' '{_ps_literal(stdin_marker)}'

$successfulAbort = [pscustomobject]@{{}}
$successfulAbort | Add-Member ScriptMethod Abort {{ param([int]$Milliseconds) }}
$delayedInput = [Threading.Tasks.Task]::Delay(200)
$delayedWatch = [Diagnostics.Stopwatch]::StartNew()
Stop-TicketboxBoundedNativeProcessTree `
    -NativeProcess $successfulAbort `
    -SettlementMilliseconds 1000 `
    -InputWriteTask $delayedInput
$delayedWatch.Stop()
if (-not $delayedInput.IsCompleted -or $delayedWatch.ElapsedMilliseconds -lt 100) {{
    throw 'stdin settlement returned before the write task reached a terminal state'
}}

$failedAbort = [pscustomobject]@{{}}
$failedAbort | Add-Member ScriptMethod Abort {{
    param([int]$Milliseconds)
    throw [TicketboxProcessTreeTerminationException]::new('injected abort failure')
}}
$preFault = [Threading.Tasks.TaskCompletionSource[bool]]::new()
$preFault.SetException([InvalidOperationException]::new('pre-abort stdin failure'))
$retainedPreFault = $false
try {{
    Stop-TicketboxBoundedNativeProcessTree `
        -NativeProcess $failedAbort `
        -SettlementMilliseconds 1000 `
        -InputWriteTask $preFault.Task
}}
catch {{
    $inner = @($_.Exception.InnerExceptions)
    $retainedPreFault =
        $_.Exception -is [TicketboxProcessTreeTerminationAggregateException] -and
        $inner.Count -eq 2 -and
        $inner[0].Message -like '*injected abort failure*' -and
        $inner[1].Message -like '*pre-abort stdin failure*'
}}
if (-not $retainedPreFault) {{ throw 'pre-abort stdin failure was not retained' }}

$singlePreFault = [Threading.Tasks.TaskCompletionSource[bool]]::new()
$singlePreFault.SetException([InvalidOperationException]::new('single stdin failure'))
$retainedSinglePreFault = $false
try {{
    Stop-TicketboxBoundedNativeProcessTree `
        -NativeProcess $successfulAbort `
        -SettlementMilliseconds 1000 `
        -InputWriteTask $singlePreFault.Task
}}
catch {{
    $retainedSinglePreFault =
        $_.Exception.Message -like '*single stdin failure*'
}}
if (-not $retainedSinglePreFault) {{ throw 'single pre-abort stdin failure was swallowed' }}

$singleNeverSettles = [Threading.Tasks.TaskCompletionSource[bool]]::new()
$retainedSingleSettlementFailure = $false
try {{
    Stop-TicketboxBoundedNativeProcessTree `
        -NativeProcess $successfulAbort `
        -SettlementMilliseconds 200 `
        -InputWriteTask $singleNeverSettles.Task
}}
catch {{
    $retainedSingleSettlementFailure =
        $_.Exception -is [TicketboxProcessTreeTerminationException] -and
        $_.Exception.Message -like '*standard input write did not settle*'
}}
if (-not $retainedSingleSettlementFailure) {{
    throw 'single stdin settlement failure was swallowed'
}}

$script:duringAbortFault = [Threading.Tasks.TaskCompletionSource[bool]]::new()
$faultingAbort = [pscustomobject]@{{}}
$faultingAbort | Add-Member ScriptMethod Abort {{
    param([int]$Milliseconds)
    $script:duringAbortFault.SetException(
        [InvalidOperationException]::new('during-abort stdin failure')
    )
}}
try {{
    Stop-TicketboxBoundedNativeProcessTree `
        -NativeProcess $faultingAbort `
        -SettlementMilliseconds 1000 `
        -InputWriteTask $script:duringAbortFault.Task
}}
catch {{
    throw "abort-induced stdin fault was misclassified as cleanup failure: $($_.Exception.Message)"
}}
if (-not $script:duringAbortFault.Task.IsCompleted) {{
    throw 'abort-induced stdin fault did not reach a terminal state'
}}

$slowFailedAbort = [pscustomobject]@{{}}
$slowFailedAbort | Add-Member ScriptMethod Abort {{
    param([int]$Milliseconds)
    Start-Sleep -Milliseconds 200
    throw [TicketboxProcessTreeTerminationException]::new('slow abort failure')
}}
$neverSettles = [Threading.Tasks.TaskCompletionSource[bool]]::new()
$budgetWatch = [Diagnostics.Stopwatch]::StartNew()
$retainedSettlementFailure = $false
try {{
    Stop-TicketboxBoundedNativeProcessTree `
        -NativeProcess $slowFailedAbort `
        -SettlementMilliseconds 600 `
        -InputWriteTask $neverSettles.Task
}}
catch {{
    $inner = @($_.Exception.InnerExceptions)
    $retainedSettlementFailure =
        $_.Exception -is [TicketboxProcessTreeTerminationAggregateException] -and
        $inner.Count -eq 2 -and
        $inner[0].Message -like '*slow abort failure*' -and
        $inner[1].Message -like '*standard input write did not settle*'
}}
$budgetWatch.Stop()
if (
    -not $retainedSettlementFailure -or
    $budgetWatch.ElapsedMilliseconds -lt 450 -or
    $budgetWatch.ElapsedMilliseconds -ge 750
) {{
    throw "stdin settlement did not preserve one total budget: $($budgetWatch.ElapsedMilliseconds)"
}}

# Deterministically inject an unconfirmed settlement after performing the real
# kill. The wrapper must retain both the action failure and the typed settlement
# failure; neither may be flattened into a generic cleanup message.
function Stop-TicketboxBoundedNativeProcessTree {{
    param(
        [object]$NativeProcess,
        [int]$SettlementMilliseconds,
        [Threading.Tasks.Task]$InputWriteTask
    )
    $NativeProcess.Abort($SettlementMilliseconds)
    throw [TicketboxProcessTreeTerminationException]::new(
        'injected settlement timeout'
    )
}}
$injectedAggregate = $false
try {{
    Invoke-TicketboxBoundedNativeProcess `
        -FilePath '{_ps_literal(sys.executable)}' `
        -Arguments @('{_ps_literal(tree_script)}', '{_ps_literal(injected_pids)}', '{_ps_literal(injected_marker)}', 'heartbeat', '2') `
        -TimeoutMilliseconds 1000 `
        -TerminationSettlementMilliseconds 1000 `
        -Label 'injected settlement timeout' | Out-Null
}}
catch {{
    $failure = $_.Exception
    $inner = @($failure.InnerExceptions)
    $injectedAggregate =
        $failure -is [TicketboxProcessTreeTerminationAggregateException] -and
        $failure.FailureCode -ceq 'tree_termination_unconfirmed' -and
        $failure.Data['TicketboxFailureCode'] -ceq 'tree_termination_unconfirmed' -and
        $inner.Count -eq 2 -and
        $inner[0].Message -like '*超过允许*' -and
        $inner[1] -is [TicketboxProcessTreeTerminationException] -and
        $inner[1].FailureCode -ceq 'tree_termination_unconfirmed'
}}
if (-not $injectedAggregate) {{
    throw 'settlement timeout did not preserve action and typed termination failures'
}}
Assert-TreeSettledAtReturn '{_ps_literal(injected_pids)}' '{_ps_literal(injected_marker)}'

[ordered]@{{
    TimeoutKilled = $timeoutKilled
    TimeoutElapsed = $timeoutWatch.ElapsedMilliseconds
    StdinKilled = $stdinKilled
    StdinElapsed = $stdinWatch.ElapsedMilliseconds
    InjectedAggregate = $injectedAggregate
}} | ConvertTo-Json -Compress
""",
            encoding="utf-8-sig",
        )
        completed = subprocess.run(  # noqa: S603
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(harness),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        evidence = json.loads(completed.stdout.strip().splitlines()[-1])
        assert evidence["TimeoutKilled"] is True
        assert evidence["StdinKilled"] is True
        assert evidence["InjectedAggregate"] is True
        assert evidence["TimeoutElapsed"] < 3000
        assert evidence["StdinElapsed"] < 3000


def test_bounded_native_process_uses_suspended_job_assignment_before_resume() -> None:
    database_safety = _read("windows_database_safety.ps1")
    recovery_generation = _read("windows_database_generation_target_recovery.ps1")
    native_start = database_safety[
        database_safety.index("public static TicketboxBoundedNativeProcess Start(") : database_safety.index(
            "private void AssertOpen()"
        )
    ]

    assert "JobObjectLimitKillOnJobClose" in database_safety
    assert "ProcThreadAttributeHandleList" in database_safety
    assert "SortedDictionary<string, string>" in database_safety
    assert "StringComparer.OrdinalIgnoreCase" in database_safety
    assert "block.Append('\\0')" in database_safety
    assert "creationFlags |= CreateUnicodeEnvironment" in native_start
    assert "BuildEnvironmentBlock(environmentVariables)" in native_start
    assert "CreateSuspended" in native_start
    assert native_start.index("CreateProcessW(") < native_start.index(
        "AssignProcessToJobObject(jobHandle, processHandle)"
    )
    assert native_start.index("AssignProcessToJobObject(jobHandle, processHandle)") < native_start.index(
        "ResumeThread(threadHandle)"
    )
    assert "TerminateCreatedProcessAndConfirm(" in native_start
    assert "TerminateProcess(processHandle, 1)" in database_safety
    settlement = database_safety[
        database_safety.index("private static void WaitForTreeSettlement(") : database_safety.index(
            "private static void TerminateCreatedProcessAndConfirm("
        )
    ]
    assert "rootSignaled = IsProcessSignaled(processHandle)" in settlement
    assert "activeProcesses = ReadActiveProcessCount(jobHandle)" in settlement
    assert "rootSignaled && activeProcesses == 0" in settlement
    assert "tree_termination_unconfirmed" in database_safety
    assert "[PowerShell]::Create()" not in database_safety
    assert "BeginStop(" not in database_safety
    assert "[Environment]::FailFast(" not in database_safety
    assert "DatabaseAuthorityCredential" not in database_safety
    assert "database_authority_credential" not in recovery_generation
    assert "Process.Start()" not in database_safety
    assert ".Kill()" not in database_safety
    assert "$process.WaitForExit()" not in database_safety


def test_service_lifecycle_requires_exact_image_path_and_terminal_states() -> None:
    lifecycle = _read("windows_service_contract.ps1") + "\n" + _read("windows_service_lifecycle.ps1")

    assert "Get-CimInstance -ClassName Win32_Service" in lifecycle
    assert "ConvertTo-TicketboxServiceExecutablePath" in lifecycle
    assert "StringComparison]::OrdinalIgnoreCase" in lifecycle
    assert "拒绝操作同名外部服务" in lifecycle
    assert 'Wait-TicketboxServiceState @waitArguments -DesiredState "stopped"' in lifecycle
    assert 'Wait-TicketboxServiceState @waitArguments -DesiredState "running"' in lifecycle
    assert '-DesiredState "absent"' in lifecycle
    assert "Stop-Service -Name $Name -Force -ErrorAction Stop" in lifecycle
    assert "Restart-TicketboxOwnedServiceIfExists" in lifecycle
    assert "拒绝未加引号且含空格" in lifecycle
    assert "Assert-TicketboxServiceArgumentPath" in lifecycle
    assert "Assert-TicketboxPgServiceCommand" in lifecycle
    assert "Assert-TicketboxShawlServiceCommand" in lifecycle
    assert "Assert-TicketboxServiceIdentityShape" in lifecycle
    assert "function Assert-TicketboxServiceAccount" not in lifecycle
    assert "Wait-TicketboxServiceSettledState" in lifecycle
    assert "New-TicketboxWaitDeadline" in lifecycle
    assert "Get-TicketboxWaitAttempts" not in lifecycle
    assert "New-TicketboxPgServiceImagePath" in lifecycle
    assert "New-TicketboxShawlServiceImagePath" in lifecycle
    assert "Get-TicketboxServiceDependencies" in lifecycle
    assert "QueryServiceConfigW" in lifecycle
    assert "QUERY_SERVICE_CONFIGW" in lifecycle
    assert "SCM dependency MULTI_SZ" in lifecycle
    assert "$record.Dependencies" not in lifecycle
    assert "Initialize-TicketboxServiceFailurePolicyNativeMethods" in lifecycle
    assert "QueryServiceConfig2" in lifecycle
    assert "Assert-TicketboxServiceFailurePolicy" in lifecycle
    assert '"--kill-process-tree"' in lifecycle
    assert "Wait-TicketboxBackendRuntimeStopped" in lifecycle
    assert "Get-TicketboxListeningProcessIds" in lifecycle
    assert "Get-TicketboxServiceProcessId" in lifecycle
    assert "Get-TicketboxExpectedRuntimeProcessIds" in lifecycle
    assert "Get-CimInstance -ClassName Win32_Process" in lifecycle
    assert "[Environment]::SystemDirectory" in lifecycle
    assert 'Join-Path $systemDirectory "sc.exe"' in lifecycle
    assert "Test-Path -LiteralPath $scExecutable -PathType Leaf" in lifecycle
    assert "[System.IO.FileAttributes]::ReparsePoint" in lifecycle
    assert "Invoke-TicketboxBoundedNativeProcess" in lifecycle
    assert "& $scExecutable @ScArgs" not in lifecycle
    assert "& sc.exe @ScArgs" not in lifecycle
    assert "Set-TicketboxOwnedServiceDemandStartIfExists" in lifecycle
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" in lifecycle
    install = _read("install_bundled_services.ps1")
    assert '$BackupDir = Join-Path $DataRoot "backups"' in install
    assert '$BackupDir = Join-Path $AppData "backups"' not in install
    prepare = _read("prepare_bundled_upgrade.ps1")
    uninstall = _read("uninstall_bundled_services.ps1")
    recovery_cleanup = prepare[
        prepare.index("function Remove-TicketboxRecoveryPgServiceIfExists") : prepare.index(
            "function Assert-TicketboxDeferredPreservedPgServiceConfiguration"
        )
    ]
    assert "if (-not (Test-TicketboxServiceExists $PgRecoveryServiceName)) { return }" not in recovery_cleanup
    assert recovery_cleanup.index("Get-TicketboxServiceSid") < recovery_cleanup.index(
        "Assert-TicketboxRecoveryServiceAclTransition"
    )
    assert recovery_cleanup.index("Remove-TicketboxOwnedServiceIfExists") < recovery_cleanup.index(
        "Set-TicketboxRecoveryServiceDataAcl"
    )
    assert "Get-TicketboxPathEntryKindNoFollow" in recovery_cleanup
    assert "ValidateInstalledServicesOnly" in install
    assert "ExpectedBackendServiceName" in install
    validation = install[install.index("if ($ValidateInstalledServicesOnly)") : install.index("$operationLock =")]
    assert "Assert-ExpectedServiceConfiguration $PgServiceName" in validation
    assert "Assert-ExpectedServiceConfiguration $BackendServiceName" in validation
    assert validation.count("Assert-TicketboxServiceFailurePolicy `") == 2
    assert "-ExpectedResetSeconds $ScmFailureResetSeconds" in validation
    assert "-ExpectedRestartDelaysMs @($ReleaseConfig.scm_restart_delays_ms)" in validation
    assert validation.count("Assert-TicketboxServiceDelayedAutoStart") == 2
    stopped_validation = install[
        install.index("if ($ValidateBackendRuntimeStoppedOnly)") : install.index("$operationLock =")
    ]
    assert "Wait-TicketboxBackendRuntimeStopped `" in stopped_validation
    assert "-BackendPort $BackendPort" in stopped_validation
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in stopped_validation
    for entry_script in (install, prepare, uninstall):
        assert "[int]$InstallerLockOwnerProcessId = 0" in entry_script
        assert "Enter-TicketboxLifecycleLock `" in entry_script
        assert "-ExternalOwnerProcessId $InstallerLockOwnerProcessId" in entry_script
        assert "InstallerLockHeld" not in entry_script
    lifecycle_lock = _read("windows_lifecycle_lock.ps1")
    assert "installer-operation.lock" in lifecycle_lock
    assert "Enter-TicketboxExclusiveFileLock $operationLockPath" not in lifecycle_lock
    assert "Enter-TicketboxProtectedExclusiveFileLock `" in lifecycle_lock
    assert "Operation = $operationLock" in lifecycle_lock
    assert "Get-TicketboxServiceSid" in lifecycle
    assert 'Invoke-TicketboxScChecked @("showsid", $Name)' in lifecycle
    assert "$initialAclAccounts" not in install
    preclassification = install.index("$preExistingPgService = Service-Exists")
    secure_install_root = install.index(
        "Initialize-TicketboxSecureInstallRoot",
        preclassification,
    )
    assert install.index("Assert-ExpectedServiceConfiguration", preclassification) < secure_install_root
    assert install.index("Assert-TicketboxServiceFailurePolicy", preclassification) < secure_install_root
    stop_backend = install.index("Stop-ServiceIfExists", install.index("$hadExistingPgService"))
    isolate_acl = install.index("Set-TicketboxAcl", stop_backend)
    generation_owner = install.index("Invoke-TicketboxInstalledDatabaseGeneration", isolate_acl)
    assert stop_backend < isolate_acl < generation_owner
    assert "Invoke-PreUpgradeBackupIfNeeded" not in install
    assert "-IncludeBackendService $hadExistingBackendService" in install
    prepare_commit = prepare[
        prepare.index("function Complete-TicketboxInterruptedInitdbServiceCommit") : prepare.index(
            "function Remove-TicketboxAbortedInitdbPgData"
        )
    ]
    assert (
        prepare_commit.index('"failure", $PgServiceName')
        < prepare_commit.index("Assert-TicketboxServiceFailurePolicy")
        < prepare_commit.index("Remove-TicketboxInitdbServiceReceipt")
    )
    uninstall_recovery = uninstall[
        uninstall.index("function Invoke-TicketboxInitdbServiceUninstallRecovery") : uninstall.index(
            'Write-Host "=== 小票夹服务卸载 ==="'
        )
    ]
    env_guard = uninstall_recovery.index('Join-Path $AppData ".env"')
    formal_branch = uninstall_recovery.index('if ($serviceShape -ceq "formal_pg_ctl")')
    formal_disable = uninstall_recovery.index(
        "Disable-TicketboxOwnedServiceIfExists",
        formal_branch,
    )
    formal_policy = uninstall_recovery.index(
        '"failure", $PgServiceName',
        formal_disable,
    )
    formal_policy_assert = uninstall_recovery.index(
        "Assert-TicketboxServiceFailurePolicy",
        formal_policy,
    )
    formal_receipt_retire = uninstall_recovery.index(
        "Remove-TicketboxInitdbServiceReceipt",
        formal_policy_assert,
    )
    assert env_guard < formal_branch < formal_disable < formal_policy
    assert formal_policy < formal_policy_assert < formal_receipt_retire
    assert "-RuntimePort $PgPort" in uninstall_recovery
    for runtime_contract in (install, prepare):
        assert "$ServiceBootstrapExposureRecoveryGuardPath" in runtime_contract
        assert "Get-TicketboxRuntimeBootstrapRecoveryGuardPath $binding.RuntimeDataRoot" in runtime_contract
    assert "-BootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath" in install
    assert "-ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath" in prepare
    acl_function = install[install.index("function Set-TicketboxAcl") : install.index("function Assert-PortAvailable")]
    assert acl_function.index("-Path $AppData") < acl_function.index(
        "Initialize-TicketboxInstallerStateDirectory $InstallerState"
    )
    assert '$markerReadAccounts += "NT SERVICE\\$BackendServiceName"' in acl_function
    assert "$backupReadAccounts" not in acl_function
    backup_acl = acl_function.index("-Path $BackupDir")
    assert acl_function.index("-Accounts $systemAndAdmins", backup_acl) > backup_acl
    assert "-InheritableReadExecuteAccounts" not in acl_function[backup_acl:]
    marker_acl = acl_function.index("-Path (Get-TicketboxDataRootMarkerPath $DataRoot)")
    assert acl_function.index("-ReadExecuteAccounts $markerReadAccounts", marker_acl) > marker_acl
    operation = install[install.index("$operationLock =") :]
    assert operation.index("Initialize-TicketboxInstallerStateArtifacts") < operation.index(
        "Adopt-TicketboxOwnerBootstrapHandoff"
    )
    pg_registration = install[
        install.index("function Register-PgService") : install.index("function Register-BackendService")
    ]
    backend_registration = install[
        install.index("function Register-BackendService") : install.index("function Invoke-IcaclsChecked")
    ]
    assert "Remove-ServiceIfExists" not in pg_registration
    assert "Remove-ServiceIfExists" not in backend_registration
    assert '"create", $PgServiceName' in pg_registration
    assert '"binPath=", $pgImagePath' in pg_registration
    assert '"obj=", $PgServiceLogonAccount' in pg_registration
    assert "Set-TicketboxServiceIdentityContract" in pg_registration
    assert "-SidType $TargetServiceSidType" in pg_registration
    assert "& $PgCtl register" not in pg_registration
    assert "password=" not in pg_registration.lower()
    fresh_pg = pg_registration[pg_registration.index("else {") :]
    assert fresh_pg.index('"create", $PgServiceName') < fresh_pg.index(
        "Assert-ExpectedServiceConfiguration $PgServiceName"
    )
    assert '"create", $BackendServiceName' in backend_registration
    assert '"start=", "disabled"' in backend_registration
    assert '"start=", "demand"' not in backend_registration
    assert '"start=", "delayed-auto"' not in backend_registration
    assert 'ExpectedStartMode "Disabled"' in backend_registration
    assert '"depend=", $PgServiceName' in backend_registration

    mutation = install[install.index("$mutationStarted = $true") :]
    register_backend = mutation.index("Register-BackendService")
    write_guard = mutation.index("Write-TicketboxInstallerRuntimeRecoveryGuard")
    enable_demand = mutation.index("Set-TicketboxOwnedServiceDemandStartIfExists")
    start_backend = mutation.index('Write-Step "启动后端服务"')
    assert register_backend < write_guard < enable_demand < start_backend

    receipt = _read("windows_lifecycle_receipt.ps1")
    promotion = receipt[
        receipt.index("function Enable-TicketboxInstalledServicesAutoStart") : receipt.index(
            "function Complete-TicketboxInstalledLifecycleTransaction"
        )
    ]
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" in promotion
    assert "Assert-TicketboxServiceDelayedAutoStart" in promotion

    backend_bootstrap = _read("windows_backend_bootstrap.ps1")
    exposure_recovery = _read("windows_bootstrap_exposure_recovery.ps1")
    assert "Wait-BackendHealth" not in install
    assert "Wait-BackendHealth" not in exposure_recovery
    assert "Wait-TicketboxInstalledBackendHealth" in install
    assert "Wait-TicketboxInstalledBackendHealth" in exposure_recovery
    restart = backend_bootstrap[
        backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists") : backend_bootstrap.index(
            "Wait-TicketboxInstalledBackendHealth",
            backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists"),
        )
    ]
    assert "-BackendPort $BackendPort" in restart
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in restart

    database = _read("windows_bundled_database.ps1")
    postgres_host = _read("windows_pg_recovery_tools.ps1")
    assert '"-tAc", $Sql' not in database
    assert '"--dbname", $DatabaseUrl' in postgres_host
    assert '"--tuples-only",' in postgres_host
    assert '"--no-align",' in postgres_host
    assert "Invoke-TicketboxWithPgPassFile" in postgres_host
    assert "Invoke-TicketboxPostgresqlHostNative" in postgres_host
    assert 'StandardInputText = $Sql + "`n"' in postgres_host
    assert "$out = $Sql | & $psql @args 2>&1" not in database
    assert "：$Sql`n$out" not in database


def test_fresh_preflight_has_no_database_only_backup_authority() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    install = _read("install_bundled_services.ps1")
    database = _read("windows_bundled_database.ps1")
    for retired in (
        "Invoke-TicketboxPgDumpCustom",
        "Invoke-TicketboxPgRestoreList",
        "Invoke-TicketboxPreservedDataReinstallBackup",
        "Invoke-PreUpgradeBackupIfNeeded",
        "$backupRequired",
        "$usingRecoveryPgService",
    ):
        assert retired not in prepare
        assert retired not in install
        assert retired not in database
    source_classification = prepare.index("$mode = Get-TicketboxPreparedInstallMode")
    fresh_gate = prepare.index('$mode -cne "fresh_install"', source_classification)
    receipt_write = prepare.index("Write-TicketboxLifecycleReceipt", fresh_gate)
    assert source_classification < fresh_gate < receipt_write
    assert "windows_dataset_backup.ps1" in _read("ticketbox-installer.iss")


def test_complete_dataset_backup_owner_rejects_noncanonical_result_identity() -> None:
    backup = _read("windows_dataset_backup.ps1")
    validator_start = backup.index("function Assert-TicketboxInstalledCompleteBackupResult")
    validator_end = backup.index(
        "function Invoke-TicketboxInstalledCompleteBackupHelper",
        validator_start,
    )
    validator = backup[validator_start:validator_end]

    assert '$datasetId = ([guid][string]$Result.dataset_id).ToString("D")' in validator
    assert "$datasetId -cne [string]$Result.dataset_id" in validator


def test_complete_dataset_backup_persists_request_before_stopping_writers() -> None:
    backup = _read("windows_dataset_backup.ps1")
    request_contract = _read("windows_installed_dataset_operation.ps1")
    maintenance_cli = (PACKAGING.parent / "app" / "dataset_maintenance_cli.py").read_text(encoding="utf-8")

    request = backup.index("Start-TicketboxInstalledDatasetBackupOperation")
    stop = backup.index("Stop-TicketboxOwnedServiceIfExists", request)
    assert request < stop
    assert "BackupId = [string]$Request.Payload.backup_id" in backup
    assert '"--backup-id", $captured.BackupId' in backup
    assert "Remove-TicketboxInstalledDatasetOperation" in backup
    assert '[ValidateSet("manual")]' in request_contract
    assert 'ValidateSet("manual", "scheduled")' not in request_contract
    assert 'choices=("manual",)' in maintenance_cli


def test_dataset_operation_is_retriable_and_supersedes_only_empty_backup_cross_engine(
    tmp_path: Path,
) -> None:
    contract = PACKAGING / "windows_installed_dataset_operation.ps1"
    harness = tmp_path / "dataset-backup-request-contract.ps1"
    state_root = tmp_path / "state"
    state_root.mkdir()
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
function Assert-TicketboxDatabaseGenerationExactProperties {{
    param([object]$Value, [string[]]$ExpectedNames, [string]$Label)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($ExpectedNames | Sort-Object)
    if (($actual -join ',') -cne ($expected -join ',')) {{
        throw "$Label properties drifted"
    }}
}}
function Assert-TicketboxDatabaseGenerationLowerSha256 {{
    param([string]$Value, [string]$Label)
    if ($Value -cnotmatch '^[0-9a-f]{{64}}$') {{ throw "$Label is not sha256" }}
}}
function ConvertTo-TicketboxDatabaseGenerationCanonicalJson {{
    param([object]$Value)
    return $Value | ConvertTo-Json -Depth 10 -Compress
}}
function Get-TicketboxDatabaseGenerationTextSha256 {{
    param([string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {{ return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }}
    finally {{ $sha.Dispose() }}
}}
function Get-TicketboxPathEntryKindNoFollow {{
    param([string]$Path)
    if ([IO.File]::Exists($Path)) {{ return 'File' }}
    if ([IO.Directory]::Exists($Path)) {{ return 'Directory' }}
    return 'Missing'
}}
function Write-TicketboxProtectedUtf8FileDurable {{
    param(
        [string]$Path, [string]$Text, [string[]]$FullControlAccounts,
        [string]$OwnerAccount, [switch]$ReplaceExisting
    )
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}}
function Read-TicketboxProtectedUtf8Artifact {{
    param([string]$Path, [string[]]$FullControlAccounts, [string]$OwnerAccount)
    return [pscustomobject]@{{ Text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) }}
}}
function Assert-TicketboxLifecycleOperationLease {{ param([object]$LifecycleLock) }}
function Get-TicketboxDatabaseGenerationPayloadProperties {{
    param([string]$Kind)
    if ($Kind -ceq 'intent') {{ return @('schema', 'operation_id', 'installation_id') }}
    if ($Kind -ceq 'current') {{
        return @('schema', 'operation_id', 'installation_id', 'intent_sha256', 'committed_revision')
    }}
    throw "unexpected payload kind: $Kind"
}}
. '{_ps_literal(contract)}'
$installation = '11111111-1111-4111-8111-111111111111'
$predecessorOperation = '22222222-2222-4222-8222-222222222222'
$intentPayload = [pscustomobject][ordered]@{{
    schema = 'ticketbox-database-generation-intent-v2'
    operation_id = $predecessorOperation
    installation_id = $installation
}}
$intentSha = Get-TicketboxDatabaseGenerationTextSha256 (
    ConvertTo-TicketboxDatabaseGenerationCanonicalJson $intentPayload
)
$currentPayload = [pscustomobject][ordered]@{{
    schema = 'ticketbox-current-database-generation-v1'
    operation_id = $predecessorOperation
    installation_id = $installation
    intent_sha256 = $intentSha
    committed_revision = '20260821_0001'
}}
$currentSha = Get-TicketboxDatabaseGenerationTextSha256 (
    ConvertTo-TicketboxDatabaseGenerationCanonicalJson $currentPayload
)
$subject = [pscustomobject]@{{
    Identity = [pscustomobject]@{{
        InstallationId = $installation
        DataRoot = '{_ps_literal(tmp_path / "data")}'
    }}
    Manifest = [pscustomobject]@{{ Sha256 = ('b' * 64) }}
}}
[void][IO.Directory]::CreateDirectory((Join-Path $subject.Identity.DataRoot 'backups'))
$authority = [pscustomobject]@{{
    StateRoot = '{_ps_literal(state_root)}'
    Intent = [pscustomobject]@{{ PayloadSha256 = $intentSha; Payload = $intentPayload }}
    Current = [pscustomobject]@{{ PayloadSha256 = $currentSha; Payload = $currentPayload }}
}}
$inspection = [pscustomobject]@{{ Evidence = [pscustomobject]@{{
    generation = 'ticketbox-backup-33333333-3333-4333-8333-333333333333'
    manifest_sha256 = ('c' * 64)
    backup_id = '33333333-3333-4333-8333-333333333333'
    dataset_id = '44444444-4444-4444-8444-444444444444'
    restore_epoch = 0
    schema_revision = '20260821_0001'
}} }}
$lease = [pscustomobject]@{{ Held = $true }}
$first = Start-TicketboxInstalledDatasetBackupOperation `
    $subject $authority manual $true $lease
$second = Start-TicketboxInstalledDatasetBackupOperation `
    $subject $authority manual $false $lease
if (
    $first.PayloadSha256 -cne $second.PayloadSha256 -or
    $first.Payload.operation_id -cne $second.Payload.operation_id -or
    $first.Payload.backup_id -cne $second.Payload.backup_id -or
    $second.Payload.backup_kind -cne 'manual' -or
    -not [bool]$second.Payload.restart_backend
) {{ throw 'retry did not reuse the exact durable request' }}
$activePath = Get-TicketboxInstalledDatasetOperationPath $authority.StateRoot
$backupBytes = [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8)
$restore = Start-TicketboxInstalledDatasetRestoreOperation `
    $subject $authority $inspection `
    '55555555-5555-4555-8555-555555555555' `
    '44444444-4444-4444-8444-444444444444' 0 $false `
    $lease
if (
    [string]$restore.Payload.operation_kind -cne 'restore' -or
    [string]$restore.Payload.operation_id -cne '55555555-5555-4555-8555-555555555555' -or
    -not [bool]$restore.Payload.restart_backend -or
    [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8) -ceq $backupBytes
) {{ throw 'empty failed backup was not atomically superseded by restore' }}
Remove-TicketboxInstalledDatasetOperation $restore $lease

$partial = Start-TicketboxInstalledDatasetBackupOperation `
    $subject $authority manual $false $lease
$partialBytes = [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8)
$partialPath = Join-Path `
    (Join-Path $subject.Identity.DataRoot 'backups') `
    ('.ticketbox-backup-' + [string]$partial.Payload.backup_id + '.staging')
[void][IO.Directory]::CreateDirectory($partialPath)
$rejected = $false
try {{
    Start-TicketboxInstalledDatasetRestoreOperation `
        $subject $authority $inspection `
        '66666666-6666-4666-8666-666666666666' `
        '44444444-4444-4444-8444-444444444444' 0 $false `
        $lease | Out-Null
}}
catch {{ $rejected = $_.Exception.Message -like '*physical state*' }}
if (-not $rejected -or [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8) -cne $partialBytes) {{
    throw 'partial backup did not block restore without mutation'
}}
Remove-TicketboxInstalledDatasetOperation $partial $lease
[IO.Directory]::Delete($partialPath)

$restore = Start-TicketboxInstalledDatasetRestoreOperation `
    $subject $authority $inspection `
    '77777777-7777-4777-8777-777777777777' `
    '44444444-4444-4444-8444-444444444444' 0 $false `
    $lease
$restoreBytes = [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8)
$rejected = $false
try {{
    Start-TicketboxInstalledDatasetBackupOperation `
        $subject $authority manual $false $lease | Out-Null
}}
catch {{ $rejected = $_.Exception.Message -like '*restore operation is already active*' }}
if (-not $rejected -or [IO.File]::ReadAllText($activePath, [Text.Encoding]::UTF8) -cne $restoreBytes) {{
    throw 'active restore did not reject backup without mutation'
}}
Remove-TicketboxInstalledDatasetOperation $restore $lease
'DATASET_BACKUP_REQUEST_OK'
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_existing_backend_stop_reuses_preflight_identity_classification_cross_engine(
    tmp_path: Path,
) -> None:
    install_script = PACKAGING / "install_bundled_services.ps1"
    install = _read("install_bundled_services.ps1")
    stop_start = install.index("if ($hadExistingBackendService)")
    stop_call = install[stop_start : install.index("else {", stop_start)]
    assert "-ExpectedReleaseConfig $PreviousReleaseConfig" in stop_call

    harness = tmp_path / "stop-service-installed-identity-contract.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
{_powershell_function_loader(install_script, "Stop-ServiceIfExists")}

$script:BackendServiceName = 'TicketboxBackend'
$script:BackendPort = 8001
$script:BackendExe = 'C:\Program Files\Ticketbox\backend.exe'
$script:ShawlExe = 'C:\Program Files\Ticketbox\shawl.exe'
$script:PgCtl = 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe'
$script:PgBin = 'C:\Program Files\Ticketbox\pg\bin'
$script:StopTimeoutMs = 30000
$script:RestartDelayMs = 5000
$script:ServiceWaitArguments = @{{
    TimeoutMilliseconds = 1000
    PollMilliseconds = 1
}}
$script:ReleaseConfig = [pscustomobject]@{{
    schema = 'ticketbox-windows-release-v2'
}}
$installedConfig = [pscustomobject]@{{
    schema = 'ticketbox-windows-release-v1'
}}
$script:observedInstalledConfig = $null
$script:stopCalls = 0

function Assert-ExpectedServiceConfiguration {{
    param(
        $Name,
        $ExpectedStopTimeoutMs,
        $ExpectedRestartDelayMs,
        $ExpectedReleaseConfig,
        [switch]$AllowTargetPolicyFallback,
        [switch]$AllowMissingInstallerRecoveryGuard,
        [switch]$AllowLegacyRuntimeDataContract,
        [switch]$AllowMissingOwnerRecoveryChannel
    )
    $script:observedInstalledConfig = $ExpectedReleaseConfig
}}
function Get-ExpectedServiceExecutable {{ param($Name) return $script:ShawlExe }}
function Stop-TicketboxOwnedServiceIfExists {{
    param(
        $Name,
        $ExpectedExecutable,
        $BackendPort,
        $ExpectedRuntimeExecutables,
        $TimeoutMilliseconds,
        $PollMilliseconds
    )
    $script:stopCalls += 1
}}

Stop-ServiceIfExists `
    -Name $script:BackendServiceName `
    -ExpectedReleaseConfig $installedConfig `
    -AllowTargetPolicyFallback `
    -AllowMissingInstallerRecoveryGuard `
    -AllowLegacyRuntimeDataContract `
    -AllowMissingOwnerRecoveryChannel
if (-not [object]::ReferenceEquals(
        $script:observedInstalledConfig,
        $installedConfig
    )) {{
    throw 'stop boundary discarded the already-classified installed identity contract'
}}
if ($script:stopCalls -ne 1) {{
    throw 'validated existing backend was not passed to the bounded stop primitive'
}}
"STOP_SERVICE_INSTALLED_IDENTITY_OK"
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_pre_copy_compensation_preserves_exact_start_policy_mutation() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")
    lifecycle = _read("windows_service_lifecycle.ps1")

    capture = prepare.index("$backendStartPolicy = if ($hasBackendService)")
    mutation = prepare.index("$installAclMutationStarted = $true", capture)
    assert capture < mutation
    assert "Get-TicketboxServiceStartPolicy $BackendServiceName" in prepare[capture:mutation]
    assert "Get-TicketboxServiceStartPolicy $PgServiceName" in prepare[capture:mutation]
    assert "-PreviousPgStartPolicy $pgStartPolicy" in prepare
    assert "-PreviousBackendStartPolicy $backendStartPolicy" in prepare

    restore = prepare[
        prepare.index("function Restore-PreviousServiceState") : prepare.index(
            "function Initialize-LegacyInstalledServicePolicy"
        )
    ]
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" not in restore
    assert restore.count("Set-TicketboxOwnedServiceStartPolicyIfExists") == 3
    restart_catch = restore.index("$restartFailure = $_.Exception.Message")
    exact_policy_restore = restore.index("$policyFailures = @()", restart_catch)
    aggregate_failure = restore.index("if ($null -ne $restartFailure", exact_policy_restore)
    assert restart_catch < exact_policy_restore < aggregate_failure
    assert "@{ Name = $PgServiceName; Executable = $PgCtl; Value = $PgStartPolicy }" in restore
    assert "@{ Name = $BackendServiceName; Executable = $ShawlExe; Value = $BackendStartPolicy }" in restore
    assert '$PgStartPolicy -eq "disabled"' in restore
    assert '$BackendStartPolicy -eq "disabled"' in restore
    assert '"manual"' in restore
    assert "Get-TicketboxServiceStartPolicy" in lifecycle
    assert "Set-TicketboxOwnedServiceStartPolicyIfExists" in lifecycle


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SCM dependency contract")
def test_real_scm_dependencies_are_exact_under_powershell_51_and_optional_7() -> None:
    import ctypes

    if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
        if any(
            os.environ.get(marker, "").strip().lower() == "true" for marker in ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS")
        ):
            pytest.fail("Windows packaging CI is not elevated; the real SCM dependency contract is unqualified")
        pytest.skip("real SCM dependency contract requires elevation")

    powershell_51 = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell_51 is not None, "Windows PowerShell 5.1 is required"
    engines = [(powershell_51, "Desktop51")]
    powershell_7 = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if powershell_7 is not None:
        engines.append((powershell_7, "Core7"))

    harness = PACKAGING / "tests" / "elevated_scm_dependency_contract.ps1"
    assert harness.is_file()
    results: list[dict[str, object]] = []
    for index, (engine, expected_host) in enumerate(engines):
        suffix = f"{uuid.uuid4().hex[:8]}{index}"
        probe_service_names = [
            f"TbxScmDepA{suffix}",
            f"TbxScmDepB{suffix}",
            f"TbxScmTarget{suffix}",
        ]
        _assert_scm_probe_services_absent(probe_service_names)
        try:
            completed = subprocess.run(  # noqa: S603
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(harness),
                    "-PackagingDirectory",
                    str(PACKAGING),
                    "-Suffix",
                    suffix,
                    "-ExpectedHost",
                    expected_host,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=120,
            )
        finally:
            _cleanup_scm_probe_services(probe_service_names)
        assert completed.returncode == 0, f"{engine}:\n{completed.stdout}\n{completed.stderr}"
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        assert output_lines, f"{engine} returned no real SCM evidence"
        payload = json.loads(output_lines[-1])
        assert payload["schema"] == "ticketbox-real-scm-dependency-contract-v1"
        assert payload["create_exit_codes"] == [0, 0, 0]
        assert payload["empty_dependency_count"] == 0
        assert payload["mismatch_rejected"] is True
        assert set(payload["two_dependencies"]) == {
            f"TbxScmDepA{suffix}",
            f"TbxScmDepB{suffix}",
        }
        assert payload["single_dependency"] == [f"TbxScmDepA{suffix}"]
        assert payload["group_dependency"] == ["+NetworkProvider"]
        results.append(payload)

    assert results[0]["host"] == "Desktop"
    assert str(results[0]["powershell_version"]).startswith("5.1.")
    if powershell_7 is not None:
        assert len(results) == 2
        assert results[1]["host"] == "Core"
        assert int(str(results[1]["powershell_version"]).split(".", 1)[0]) >= 7


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell service contract")
def test_service_policy_and_sid_contract_in_powershell_5_and_7(tmp_path: Path) -> None:
    install = _read("install_bundled_services.ps1")
    lifecycle_load = install.index(". $LifecycleScript")
    safety_load = install.index(". $SafetyScript", lifecycle_load)
    receipt_load = install.index(". $ReceiptScript", safety_load)
    database_safety_load = install.index(". $DatabaseSafetyScript", receipt_load)
    first_sid_query = install.index("Get-TicketboxServiceSid", database_safety_load)
    assert lifecycle_load < safety_load < receipt_load < database_safety_load < first_sid_query
    assert install.count('$DatabaseSafetyScript = Join-Path $ScriptDir "windows_database_safety.ps1"') == 1

    harness = tmp_path / "service-start-policy.ps1"
    lifecycle = str(PACKAGING / "windows_service_lifecycle.ps1").replace("'", "''")
    installation_safety = str(PACKAGING / "windows_installation_safety.ps1").replace("'", "''")
    database_safety = str(PACKAGING / "windows_database_safety.ps1").replace("'", "''")
    receipt = str(PACKAGING / "windows_lifecycle_receipt.ps1").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{lifecycle}'
. '{installation_safety}'
. '{receipt}'
. '{database_safety}'
$sid = Get-TicketboxServiceSid 'TicketboxPgRecoveryContractProbe'
if ($sid -cnotmatch '^S-1-5-80-(?:[0-9]+-){{4}}[0-9]+$') {{
    throw "invalid virtual service SID: $sid"
}}
$script:scModes = @()
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $true }}
function Invoke-TicketboxScChecked([string[]]$ScArgs) {{
    $script:scModes += $ScArgs[-1]
    return ''
}}
function Assert-TicketboxServiceStartPolicy([string]$Name, [string]$ExpectedStartPolicy) {{ }}
foreach ($policy in @('disabled', 'manual', 'auto', 'delayed_auto')) {{
    Set-TicketboxOwnedServiceStartPolicyIfExists `
        -Name Demo `
        -ExpectedExecutable 'C:\\Demo\\demo.exe' `
        -StartPolicy $policy
}}
$actual = $script:scModes -join ','
if ($actual -ne 'disabled,demand,auto,delayed-auto') {{ throw "policy mapping changed: $actual" }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SCM process boundary")
def test_service_sc_uses_unified_bounded_process_cross_engine(
    tmp_path: Path,
) -> None:
    lifecycle_path = PACKAGING / "windows_service_lifecycle.ps1"
    lifecycle = _read("windows_service_lifecycle.ps1")
    dispatcher = lifecycle[
        lifecycle.index("function Invoke-TicketboxScProcess") : lifecycle.index("function Get-TicketboxServiceSid")
    ]
    assert "Invoke-TicketboxBoundedNativeProcess" in dispatcher
    assert "-TimeoutMilliseconds 30000" in dispatcher
    assert "& $scExecutable @ScArgs" not in lifecycle
    assert "return Invoke-TicketboxScCreateChecked $ScArgs" not in dispatcher
    assert "return Invoke-TicketboxScConfigWithBinaryPathChecked $ScArgs" not in dispatcher

    harness = tmp_path / "service-sc-bounded-process-contract.ps1"
    lifecycle_literal = str(lifecycle_path).replace("'", "''")
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
. '{lifecycle_literal}'
$script:calls = @()
$script:exitCode = 0
$script:standardOutput = '[SC] CreateService SUCCESS'
$script:standardError = ''
function Invoke-TicketboxBoundedNativeProcess {{
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutMilliseconds,
        [string]$Label
    )
    $script:calls += [pscustomobject]@{{
        FilePath = $FilePath
        Arguments = [string[]]$Arguments
        TimeoutMilliseconds = $TimeoutMilliseconds
        Label = $Label
    }}
    return [pscustomobject]@{{
        ExitCode = $script:exitCode
        StandardOutput = $script:standardOutput
        StandardError = $script:standardError
    }}
}}
$image = '"C:\Program Files\Ticketbox 空格\shawl\shawl.exe" run --name TicketboxBackend -- "C:\Program Files\Ticketbox 空格\backend.exe"'
$createResult = Invoke-TicketboxScChecked @(
    'CREATE','TicketboxBackend','binPath=',$image,'start=','disabled',
    'depend=','TicketboxPg/RpcSs','obj=','NT AUTHORITY\LocalService',
    'displayName=','小票夹后端服务'
)
if ($createResult -cne '[SC] CreateService SUCCESS' -or $script:calls.Count -ne 1) {{
    throw 'create did not cross the bounded sc.exe boundary exactly once'
}}
$createCall = $script:calls[0]
$expectedSc = [IO.Path]::GetFullPath(
    (Join-Path ([Environment]::SystemDirectory) 'sc.exe')
)
if ($createCall.FilePath -cne $expectedSc -or
    $createCall.TimeoutMilliseconds -ne 30000 -or
    $createCall.Label -cne 'Windows 服务控制器' -or
    $createCall.Arguments.Count -ne 12 -or
    $createCall.Arguments[0] -cne 'CREATE' -or
    $createCall.Arguments[3] -cne $image -or
    $createCall.Arguments[7] -cne 'TicketboxPg/RpcSs' -or
    $createCall.Arguments[9] -cne 'NT AUTHORITY\LocalService' -or
    $createCall.Arguments[11] -cne '小票夹后端服务') {{
    throw 'bounded create lost an exact sc.exe argument'
}}

$script:standardOutput = '[SC] ChangeServiceConfig SUCCESS'
$legacyMutationRejected = $false
try {{
    Invoke-TicketboxScChecked @(
        'CONFIG','TicketboxPg','binPath=',$image,'start=','disabled',
        'obj=','NT SERVICE\TicketboxPg'
    ) | Out-Null
}}
catch {{ $legacyMutationRejected = $true }}
if (-not $legacyMutationRejected -or $script:calls.Count -ne 1) {{
    throw 'legacy audit identity crossed the current SCM mutation boundary'
}}
$script:standardOutput = '[SC] ChangeServiceConfig SUCCESS'
Invoke-TicketboxScChecked @(
    'config','TicketboxPg','start=','delayed-auto'
) | Out-Null
if ($script:calls.Count -ne 2 -or
    ($script:calls[1].Arguments -join ',') -cne 'config,TicketboxPg,start=,delayed-auto') {{
    throw 'simple config did not use the unified sc.exe boundary'
}}
$script:standardOutput = '[SC] ChangeServiceConfig SUCCESS'
Invoke-TicketboxScChecked @(
    'config','TicketboxBackend','depend=',''
) | Out-Null
if ($script:calls.Count -ne 3 -or
    $script:calls[2].Arguments.Count -ne 4 -or
    $script:calls[2].Arguments[2] -cne 'depend=' -or
    $script:calls[2].Arguments[3] -cne '') {{
    throw 'explicit dependency clear lost its empty argv element'
}}
$script:standardOutput = '[SC] ChangeServiceConfig SUCCESS'
Invoke-TicketboxScChecked @(
    'config','TicketboxBackend','obj=','nt authority\localservice'
) | Out-Null
if ($script:calls.Count -ne 4 -or
    $script:calls[3].Arguments[3] -cne 'nt authority\localservice') {{
    throw 'LocalService logon account did not cross the bounded SCM boundary'
}}

$callsBeforeReject = $script:calls.Count
foreach ($case in @(
    @('create','TicketboxPg','binPath=',$image,'start=','disabled','obj=','LocalSystem'),
    @('config','TicketboxPg','obj=','LocalSystem'),
    @('config','TicketboxPg','obj=','NT AUTHORITY\NetworkService'),
    @('config','TicketboxPg','password=','DO_NOT_LOG_THIS_SECRET'),
    @('config',("TicketboxPg" + [char]0 + 'tail'),'binPath=',$image),
    @('config','TicketboxPg','binPath=',($image + [char]0 + 'tail')),
    @('query',("TicketboxPg" + [char]13 + 'tail')),
    @('query',("TicketboxPg" + [char]10 + 'tail'))
)) {{
    $rejected = $false
    try {{ Invoke-TicketboxScChecked $case | Out-Null }}
    catch {{ $rejected = $true }}
    if (-not $rejected -or $script:calls.Count -ne $callsBeforeReject) {{
        throw 'unsafe sc.exe request crossed the process boundary'
    }}
}}

$script:exitCode = 1639
$script:standardOutput = ''
$script:standardError = 'SC_USAGE_PROBE'
$failedClosed = $false
try {{
    Invoke-TicketboxScChecked @(
        'config','TicketboxPg','binPath=',$image
    ) | Out-Null
}}
catch {{
    $failedClosed = (
        $_.Exception.Message -like '*exit=1639*' -and
        $_.Exception.Message -like '*SC_USAGE_PROBE*' -and
        $_.Exception.Message -notlike "*$image*" -and
        $_.Exception.Message -like '*options=binpath=*'
    )
}}
if (-not $failedClosed) {{ throw 'sc.exe non-zero exit was hidden' }}

$secretSummary = Format-TicketboxScOperationForLog @(
    'config','TicketboxPg','password=','DO_NOT_LOG_THIS_SECRET'
)
if ($secretSummary -like '*DO_NOT_LOG_THIS_SECRET*' -or
    $secretSummary -cne 'sc.exe config TicketboxPg options=password=') {{
    throw 'sc.exe error summary exposed an option value'
}}

$script:exitCode = 0
$script:standardError = ''
$emptySuccess = Invoke-TicketboxScChecked @('query','TicketboxPg')
if ($emptySuccess -cne '[SC] query SUCCESS (exit=0)') {{
    throw 'empty successful sc.exe result lost exit=0 evidence'
}}
"SC_BOUNDED_PROCESS_OK"
""",
        encoding="utf-8-sig",
    )
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows TCP cmdlet contract")
def test_tcp_listener_query_handles_native_empty_and_close_in_powershell_5_and_7(
    tmp_path: Path,
) -> None:
    flow = _read("ticketbox-installer-flow.isph")
    assert "CmdletizationQuery_NotFound,Get-NetTCPConnection" in flow
    assert "catch { exit 2 }" not in flow

    harness = tmp_path / "tcp-listener-query.ps1"
    lifecycle = str(PACKAGING / "windows_service_lifecycle.ps1").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{lifecycle}'
$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$active = @(Get-TicketboxListeningProcessIds -Port $port)
if ($active.Count -eq 0 -or $active -notcontains $PID) {{
    throw 'native listener was not reported'
}}
$listener.Stop()
$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {{
    $closed = @(Get-TicketboxListeningProcessIds -Port $port)
    if ($closed.Count -eq 0) {{ break }}
    Start-Sleep -Milliseconds 50
}} while ([DateTime]::UtcNow -lt $deadline)
if ($closed.Count -ne 0) {{ throw 'closed listener was still reported' }}
$unused = @(Get-TicketboxListeningProcessIds -Port $port)
if ($unused.Count -ne 0) {{ throw 'unused port was not treated as empty' }}
$cimFailurePropagated = $false
try {{
    Get-TicketboxListeningProcessIds `
        -Port $port `
        -ConnectionReader {{
            throw [System.InvalidOperationException]::new('simulated CIM failure')
        }} | Out-Null
}}
catch {{
    $cimFailurePropagated = $_.Exception.Message -eq 'simulated CIM failure'
}}
if (-not $cimFailurePropagated) {{ throw 'real CIM failure was swallowed' }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line contract")
def test_service_image_paths_roundtrip_in_powershell_5_and_7(tmp_path: Path) -> None:
    contract = PACKAGING / "windows_service_contract.ps1"
    harness = tmp_path / "service-image-roundtrip.ps1"
    harness.write_text(
        rf"""
$ErrorActionPreference = 'Stop'
. '{str(contract).replace("'", "''")}'
$pg = New-TicketboxPgServiceImagePath `
    -PgCtlPath 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe' `
    -ServiceName TicketboxPg `
    -DataRoot 'D:\Ticketbox Data\pgdata'
$pgParts = @(Split-TicketboxWindowsCommandLine $pg)
if ($pgParts.Count -ne 7 -or $pgParts[5] -cne 'D:\Ticketbox Data\pgdata') {{
    throw 'PostgreSQL ImagePath did not roundtrip'
}}
$shawl = New-TicketboxShawlServiceImagePath `
    -ShawlPath 'C:\Program Files\Ticketbox\shawl\shawl.exe' `
    -ServiceName TicketboxBackend `
    -WorkingDirectory 'D:\Ticketbox Data\app' `
    -LogDirectory 'D:\Ticketbox Data\app\logs' `
    -BackendPath 'C:\Program Files\Ticketbox\program\ticketbox-backend\ticketbox-backend.exe' `
    -PgDumpPath 'C:\Program Files\Ticketbox\pg\bin\pg_dump.exe' `
    -PgRestorePath 'C:\Program Files\Ticketbox\pg\bin\pg_restore.exe' `
    -BootstrapRecoveryGuardPath 'D:\Ticketbox Data\bootstrap-exposure-recovery-pending' `
    -InstallerRecoveryGuardPath 'D:\Ticketbox Data\installer-runtime-recovery-pending' `
    -DataRootMarkerPath 'C:\ProgramData\TicketboxRuntimeBinding\data-root\.ticketbox-data-root.json' `
    -DataVolumeIdentity '\\?\Volume{{01234567-89AB-CDEF-0123-456789ABCDEF}}\' `
    -OwnerRecoveryChannel managed_host `
    -StopTimeoutMs 25000 `
    -RestartDelayMs 5000
$shawlParts = @(Split-TicketboxWindowsCommandLine $shawl)
if ($shawlParts[-1] -cne 'C:\Program Files\Ticketbox\program\ticketbox-backend\ticketbox-backend.exe') {{
    throw 'Shawl ImagePath did not roundtrip'
}}
if (@($shawlParts | Where-Object {{ $_ -ceq '--kill-process-tree' }}).Count -ne 1) {{
    throw 'Shawl process-tree termination flag did not roundtrip exactly once'
}}
if (@($shawlParts | Where-Object {{ $_ -ceq 'TICKETBOX_DATA_VOLUME_IDENTITY=\\?\VOLUME{{01234567-89AB-CDEF-0123-456789ABCDEF}}\' }}).Count -ne 1) {{
    throw 'Shawl Volume GUID authority did not roundtrip exactly once'
}}
if (@($shawlParts | Where-Object {{ $_ -ceq 'TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host' }}).Count -ne 1) {{
    throw 'Shawl owner recovery capability did not roundtrip exactly once'
}}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_deadline_secret_cleanup_and_lock_bitness_fail_closed(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell security behavior contract")

    host_guard = """function Assert-TicketboxSupportedPowerShellHost {
    Assert-TicketboxPowerShellBitness `
        -Is64BitOperatingSystem ([Environment]::Is64BitOperatingSystem) `
        -Is64BitProcess ([Environment]::Is64BitProcess)
}"""
    assert host_guard in _read("windows_lifecycle_lock.ps1")

    def literal(path: Path) -> str:
        return str(path).replace("'", "''")

    behavior_script = tmp_path / "security-behavior.ps1"
    secret_path = tmp_path / "locked-secret.txt"
    lifecycle_lock_path = tmp_path / "installer-lifecycle.lock"
    lifecycle_owner_path = tmp_path / "installer-lifecycle.owner"
    behavior_script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{literal(PACKAGING / "windows_release_config.ps1")}'
. '{literal(PACKAGING / "windows_service_lifecycle.ps1")}'
. '{literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{literal(PACKAGING / "windows_lifecycle_lock.ps1")}'
. '{literal(PACKAGING / "windows_bundled_database.ps1")}'
Assert-TicketboxPowerShellBitness -Is64BitOperatingSystem $true -Is64BitProcess $true
$bitnessRejected = $false
try {{
    Assert-TicketboxPowerShellBitness -Is64BitOperatingSystem $true -Is64BitProcess $false
}}
catch {{
    if ($_.Exception.Message -notlike '*64 位 PowerShell*') {{ throw }}
    $bitnessRejected = $true
}}
if (-not $bitnessRejected) {{ throw '32-bit PowerShell host was accepted' }}
$trustedSc = Get-TicketboxTrustedScExecutable
$expectedSc = [System.IO.Path]::GetFullPath((Join-Path ([Environment]::SystemDirectory) 'sc.exe'))
if (-not [System.IO.Path]::IsPathRooted($trustedSc) -or
    -not [string]::Equals($trustedSc, $expectedSc, [System.StringComparison]::OrdinalIgnoreCase)) {{
    throw 'trusted sc.exe did not resolve from the Windows system directory'
}}
$trustedScItem = Get-Item -LiteralPath $trustedSc -Force -ErrorAction Stop
if (($trustedScItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {{
    throw 'trusted sc.exe resolved to a reparse point'
}}
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$ownerIdentity = Get-TicketboxProcessIdentity -ProcessId $PID
Write-TicketboxLifecycleLockOwnerRecord `
    -Path '{literal(lifecycle_owner_path)}' `
    -OwnerIdentity $ownerIdentity `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
$lifecycleHandle = [System.IO.File]::Open(
    '{literal(lifecycle_lock_path)}',
    [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)
function Get-TicketboxLifecycleLockPath {{ return '{literal(lifecycle_lock_path)}' }}
function Get-TicketboxLifecycleLockOwnerPath {{ return '{literal(lifecycle_owner_path)}' }}
function Get-TicketboxParentProcessId {{ return $PID }}
try {{
    Assert-TicketboxExternalLifecycleLock `
        -OwnerProcessId $PID `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
finally {{
    $lifecycleHandle.Dispose()
}}
$releasedLockRejected = $false
try {{
    Assert-TicketboxExternalLifecycleLock `
        -OwnerProcessId $PID `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount | Out-Null
}}
catch {{ $releasedLockRejected = $true }}
if (-not $releasedLockRejected) {{ throw 'released external lifecycle lock was accepted' }}
$script:deadlineProbeCount = 0
$timedOut = $false
try {{
    Wait-TicketboxServiceSettledState -Name Demo -TimeoutMilliseconds 20 -PollMilliseconds 20 -StateReader {{ param($Name) $script:deadlineProbeCount += 1; 'startpending' }} -SleepAction {{ param($Ms) Start-Sleep -Milliseconds ($Ms + 25) }} | Out-Null
}} catch {{ $timedOut = $true }}
if (-not $timedOut -or $script:deadlineProbeCount -ne 1) {{ throw 'deadline allowed a post-timeout probe' }}
$script:runtimePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoBackend `
    -BackendPort 8765 `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe', 'C:\\Ticketbox\\shawl.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -ListenerReader {{
        param($Port)
        $script:runtimePoll += 1
        return @()
    }} `
    -RuntimeProcessReader {{
        if ($script:runtimePoll -eq 1) {{
            return [pscustomobject]@{{
                Name = 'ticketbox-backend.exe'
            ExecutablePath = 'C:\\Ticketbox\\ticketbox-backend.exe'
                ProcessId = 5101
            }}
        }}
        return @()
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:runtimePoll -ne 2) {{ throw 'backend runtime stop proof ignored a drift-port orphan process' }}
$script:pidReusePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoBackend `
    -BackendPort 8765 `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe', 'C:\\Ticketbox\\shawl.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -ListenerReader {{ param($Port) return @() }} `
    -RuntimeProcessReader {{
        $script:pidReusePoll += 1
        return [pscustomobject]@{{
            Name = 'unrelated.exe'
            ExecutablePath = 'C:\\Other\\unrelated.exe'
            ProcessId = 4101
        }}
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:pidReusePoll -ne 1) {{ throw 'unrelated reused PID blocked runtime stop proof' }}
$script:zeroPortRuntimePoll = 0
Wait-TicketboxBackendRuntimeStopped `
    -Name DemoPg `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1 `
    -RuntimeProcessReader {{
        $script:zeroPortRuntimePoll += 1
        if ($script:zeroPortRuntimePoll -eq 1) {{
            return [pscustomobject]@{{
                Name = 'postgres.exe'
                ExecutablePath = 'C:\\Ticketbox\\postgres.exe'
                ProcessId = 5201
            }}
        }}
        return @()
    }} `
    -SleepAction {{ param($Ms) }}
if ($script:zeroPortRuntimePoll -ne 2) {{
    throw 'BackendPort=0 bypassed the expected-runtime executable scan'
}}
$script:missingServiceRuntimeChecks = 0
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $false }}
function Get-TicketboxExpectedRuntimeProcessIds {{
    param([string[]]$ExpectedExecutables, [scriptblock]$ProcessSnapshotReader)
    $script:missingServiceRuntimeChecks += 1
    return @()
}}
Stop-TicketboxOwnedServiceIfExists `
    -Name MissingBackend `
    -ExpectedExecutable 'C:\\Ticketbox\\shawl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\ticketbox-backend.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
Remove-TicketboxOwnedServiceIfExists `
    -Name MissingPg `
    -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
if ($script:missingServiceRuntimeChecks -ne 2) {{
    throw 'missing SCM records bypassed runtime executable scans'
}}
$script:zeroPortStopWaits = 0
function Assert-TicketboxServiceOwnership([string]$Name, [string]$ExpectedExecutable) {{ return $true }}
function Get-TicketboxServiceProcessId([string]$Name) {{ return 6101 }}
function Wait-TicketboxServiceSettledState {{
    param([string]$Name, [int]$TimeoutMilliseconds, [int]$PollMilliseconds)
    return 'stopped'
}}
function Wait-TicketboxBackendRuntimeStopped {{
    param(
        [string]$Name,
        [int]$BackendPort,
        [string[]]$ExpectedRuntimeExecutables,
        [int]$TimeoutMilliseconds,
        [int]$PollMilliseconds
    )
    $script:zeroPortStopWaits += 1
    if ($BackendPort -ne 0) {{ throw 'PostgreSQL stop unexpectedly required a backend port' }}
    if ($ExpectedRuntimeExecutables.Count -ne 1 -or
        $ExpectedRuntimeExecutables[0] -cne 'C:\\Ticketbox\\postgres.exe') {{
        throw 'BackendPort=0 did not forward expected runtime executables'
    }}
}}
Stop-TicketboxOwnedServiceIfExists `
    -Name DemoPg `
    -ExpectedExecutable 'C:\\Ticketbox\\pg_ctl.exe' `
    -ExpectedRuntimeExecutables @('C:\\Ticketbox\\postgres.exe') `
    -TimeoutMilliseconds 1000 `
    -PollMilliseconds 1
if ($script:zeroPortStopWaits -ne 1) {{
    throw 'BackendPort=0 skipped the post-stop runtime proof'
}}
Set-Content -LiteralPath '{literal(secret_path)}' -Value 'secret'
$handle = [System.IO.File]::Open('{literal(secret_path)}', 'Open', 'Read', 'None')
$blocked = $false
try {{ Remove-TicketboxSensitiveFile '{literal(secret_path)}' }} catch {{ $blocked = $true }}
finally {{ $handle.Dispose() }}
if (-not $blocked) {{ throw 'locked sensitive file deletion failed open' }}
Remove-TicketboxSensitiveFile '{literal(secret_path)}'
if (Test-Path -LiteralPath '{literal(secret_path)}') {{ throw 'sensitive file survived verified cleanup' }}
""",
        encoding="utf-8-sig",
    )
    engines = powershell_contract_engines()
    for engine in engines:
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", behavior_script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_initdb_one_shot_command_and_terminal_states_cross_engine(
    tmp_path: Path,
) -> None:
    lifecycle = PACKAGING / "windows_service_lifecycle.ps1"
    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    release_config = PACKAGING / "windows_release_config.ps1"
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"initdb-one-shot-{index}.ps1"
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(release_config)}'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(lifecycle)}'
$shawl = 'C:\\Program Files\\Ticketbox\\shawl\\shawl.exe'
$pgBin = 'C:\\Program Files\\Ticketbox\\pg\\bin'
$initdb = Join-Path $pgBin 'initdb.exe'
$pgData = 'C:\\ProgramData\\Ticketbox\\pgdata'
$pwfile = 'C:\\ProgramData\\Ticketbox\\.ticketbox-initdb-password'
$imagePath = New-TicketboxInitdbServiceImagePath `
    -ShawlPath $shawl `
    -ServiceName 'TicketboxPg' `
    -WorkingDirectory $pgBin `
    -InitdbPath $initdb `
    -DataRoot $pgData `
    -PasswordFile $pwfile `
    -StopTimeoutMs 25000
$arguments = @(Split-TicketboxWindowsCommandLine $imagePath)
$expected = @(
    $shawl, 'run', '--name', 'TicketboxPg', '--no-restart', '--no-log',
    '--kill-process-tree', '--stop-timeout', '25000', '--cwd', $pgBin,
    '--', $initdb, '-D', $pgData, '-U', 'postgres',
    '--auth-local=scram-sha-256', '--auth-host=scram-sha-256',
    '--encoding=UTF8', '--no-locale', "--pwfile=$pwfile"
)
if ($arguments.Count -ne 22) {{ throw 'initdb command argument count drifted' }}
for ($index = 0; $index -lt $expected.Count; $index++) {{
    if ([string]$arguments[$index] -cne [string]$expected[$index]) {{
        throw "initdb command mismatch at $index"
    }}
}}
$script:serviceImagePath = $imagePath
function Get-TicketboxServiceImagePath {{ param($Name) return $script:serviceImagePath }}
function Get-TicketboxServiceDependencies {{ param($Name) return @() }}
Assert-TicketboxInitdbServiceCommand `
    -Name 'TicketboxPg' `
    -ExpectedShawl $shawl `
    -ExpectedServiceName 'TicketboxPg' `
    -ExpectedWorkingDirectory $pgBin `
    -ExpectedInitdb $initdb `
    -ExpectedDataRoot $pgData `
    -ExpectedPasswordFile $pwfile `
    -ExpectedStopTimeoutMs 25000 `
    -ExpectedImagePath $imagePath
$script:serviceImagePath = $imagePath.Replace('--no-restart', '--restart')
$poisonRejected = $false
try {{
    Assert-TicketboxInitdbServiceCommand `
        -Name 'TicketboxPg' `
        -ExpectedShawl $shawl `
        -ExpectedServiceName 'TicketboxPg' `
        -ExpectedWorkingDirectory $pgBin `
        -ExpectedInitdb $initdb `
        -ExpectedDataRoot $pgData `
        -ExpectedPasswordFile $pwfile `
        -ExpectedStopTimeoutMs 25000 `
        -ExpectedImagePath $imagePath
}}
catch {{ $poisonRejected = $true }}
if (-not $poisonRejected) {{ throw 'poisoned initdb command was accepted' }}

function Assert-TicketboxServiceOwnership {{ param($Name,$ExpectedExecutable) return $true }}
function Wait-TicketboxBackendRuntimeStopped {{ param($Name,$ExpectedRuntimeExecutables,$TimeoutMilliseconds,$PollMilliseconds) }}
$script:startCount = 0
$script:successRead = 0
function Invoke-TicketboxScChecked {{
    param([object[]]$Arguments)
    if ([string]$Arguments[0] -cne 'start') {{ throw 'unexpected sc action' }}
    $script:startCount += 1
}}
function Get-TicketboxServiceRuntimeSnapshot {{
    param($Name)
    if ($script:scenario -ceq 'exit23') {{
        return [pscustomobject]@{{ State='stopped'; ProcessId=0; ExitCode=0; ServiceSpecificExitCode=23 }}
    }}
    if ($script:scenario -ceq 'hang') {{
        return [pscustomobject]@{{ State='running'; ProcessId=42; ExitCode=0; ServiceSpecificExitCode=0 }}
    }}
    $script:successRead += 1
    if ($script:successRead -eq 1) {{
        return [pscustomobject]@{{ State='running'; ProcessId=41; ExitCode=0; ServiceSpecificExitCode=0 }}
    }}
    return [pscustomobject]@{{ State='stopped'; ProcessId=0; ExitCode=0; ServiceSpecificExitCode=0 }}
}}
$success = Invoke-TicketboxOwnedOneShotService `
    -Name 'TicketboxPg' `
    -ExpectedExecutable $shawl `
    -ExpectedRuntimeExecutables @($shawl,$initdb) `
    -TimeoutMilliseconds 2000 `
    -PollMilliseconds 10
if ($success.ExitCode -ne 0 -or $success.ServiceSpecificExitCode -ne 0) {{
    throw 'successful one-shot terminal was lost'
}}
$script:scenario = 'exit23'
$exit23 = Invoke-TicketboxOwnedOneShotService `
    -Name 'TicketboxPg' `
    -ExpectedExecutable $shawl `
    -ExpectedRuntimeExecutables @($shawl,$initdb) `
    -TimeoutMilliseconds 2000 `
    -PollMilliseconds 10
if ($exit23.ServiceSpecificExitCode -ne 23) {{
    throw 'non-zero one-shot terminal was hidden'
}}
$script:scenario = 'hang'
$hangRejected = $false
try {{
    Invoke-TicketboxOwnedOneShotService `
        -Name 'TicketboxPg' `
        -ExpectedExecutable $shawl `
        -ExpectedRuntimeExecutables @($shawl,$initdb) `
        -TimeoutMilliseconds 250 `
        -PollMilliseconds 10 | Out-Null
}}
catch {{ $hangRejected = $_.Exception.Message -like '*未在*内停止*' }}
if (-not $hangRejected) {{ throw 'hung one-shot service escaped its deadline' }}
if ($script:startCount -ne 3) {{ throw 'one-shot service start count drifted' }}
""",
            encoding="utf-8-sig",
        )
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_service_owned_initdb_collision_and_public_failure_are_production_wired(
    tmp_path: Path,
) -> None:
    install_script = PACKAGING / "install_bundled_services.ps1"
    template = r"""
$ErrorActionPreference = 'Stop'
__FUNCTION_LOADER__

$script:ShawlExe = 'C:\Program Files\Ticketbox\shawl\shawl.exe'
$script:PgServiceName = 'TicketboxPg'
$script:PgBin = 'C:\Program Files\Ticketbox\pg\bin'
$script:InitdbExe = 'C:\Program Files\Ticketbox\pg\bin\initdb.exe'
$script:PgData = 'C:\ProgramData\Ticketbox\pgdata'
$script:InitdbPasswordPath = 'C:\ProgramData\Ticketbox\.ticketbox-initdb-password'
$script:StopTimeoutMs = 25000
$script:PgServiceLogonAccount = 'NT AUTHORITY\LocalService'
$script:TargetServiceSidType = 'unrestricted'
$script:InitdbServiceReceiptPath = 'C:\ProgramData\Ticketbox\installer-state\initdb.json'
$script:InstallDir = 'C:\Program Files\Ticketbox'
$script:DataRoot = 'C:\ProgramData\Ticketbox'
$script:TargetPgMajor = 17
$script:ServiceWaitArguments = @{
    TimeoutMilliseconds = 1000
    PollMilliseconds = 1
}
$bootstrap = [pscustomobject]@{ SuperuserPassword = 'secret-value' }

function New-TicketboxInitdbServiceImagePath {
    param($ShawlPath,$ServiceName,$WorkingDirectory,$InitdbPath,$DataRoot,$PasswordFile,$StopTimeoutMs)
    return 'trusted-initdb-image'
}
function Service-Exists {
    param($Name)
    return $script:scenario -ceq 'preexisting'
}
function Write-TicketboxInitdbServiceReceipt {
    param($Path,$InstallDir,$DataRoot,$ServiceName,$ServiceLogonAccount,$ServiceSidType,$ImagePath,$PgMajor,$StopTimeoutMs,$InstallerOwnerProcessId,$Phase)
    if ($ServiceLogonAccount -cne 'NT AUTHORITY\LocalService' -or
        $ServiceSidType -cne 'unrestricted') {
        throw 'initdb receipt did not bind the current service identity'
    }
    $script:receiptWrites += 1
    $script:receipt = [pscustomobject]@{ phase = 'intent_written' }
}
function Get-TicketboxInitdbReceiptOwnerProcessId { return 777 }
function Read-TicketboxCurrentInitdbServiceReceipt { return $script:receipt }
function Invoke-ScChecked {
    param([string[]]$ScArgs)
    $verb = [string]$ScArgs[0]
    $script:scCalls += $verb
    if ($script:scenario -ceq 'race' -and $verb -ceq 'create') {
        throw [InvalidOperationException]::new('service appeared during create')
    }
    return 0
}
function Assert-TicketboxInitdbServiceConfiguration { param($Receipt,$StartMode) }
function Set-TicketboxServiceIdentityContract {
    param($Name,$LogonAccount,$SidType)
    if ($Name -cne 'TicketboxPg' -or
        $LogonAccount -cne 'NT AUTHORITY\LocalService' -or
        $SidType -cne 'unrestricted') {
        throw 'initdb service identity publication drifted'
    }
    $script:identityPublishes += 1
}
function Set-TicketboxCurrentInitdbServiceReceiptPhase {
    param($Receipt,$Phase)
    $script:receipt.phase = $Phase
    return $script:receipt
}
function Set-TicketboxAcl { param($IncludePgService,$IncludeBackendService) }
function Write-TicketboxInitdbPasswordFile {
    param($SuperuserPassword)
    $script:passwordWrites += 1
}
function Invoke-TicketboxOwnedOneShotService {
    param($Name,$ExpectedExecutable,$ExpectedRuntimeExecutables,$TimeoutMilliseconds,$PollMilliseconds)
    if ($script:scenario -ceq 'hang') {
        throw [TimeoutException]::new('one-shot deadline expired')
    }
    if ($script:scenario -ceq 'exit23') {
        return [pscustomobject]@{ ExitCode = 0; ServiceSpecificExitCode = 23 }
    }
    return [pscustomobject]@{ ExitCode = 0; ServiceSpecificExitCode = 0 }
}
function Assert-TicketboxFreshPgClusterComplete {
    if ($script:scenario -ceq 'cluster') {
        throw [InvalidOperationException]::new('cluster incomplete')
    }
}
function Remove-TicketboxInitdbPasswordFileIfPresent {
    param($Receipt)
    $script:passwordRemoves += 1
}
function Repair-PostgresBootstrapRecoveryFileAcl { param($DataRoot,$AppData,$SecretByteCount); return $false }
function Get-PostgresBootstrapRecoveryPath { param($AppData); return $script:InitdbPasswordPath }
function Read-PostgresBootstrapRecoveryState { param($Path,$AppData,$SecretByteCount) return $null }
function Disable-TicketboxInitdbServiceIfPresent {
    param($Receipt)
    $script:disableCalls += 1
}
function Get-TicketboxPathEntryKindNoFollow { param($Path) return 'File' }
function Remove-TicketboxAbortedInitdbServiceReceipt {
    param($Path,$Receipt)
    $script:receiptRemoves += 1
}
function New-TicketboxInitdbFailure {
    param($FailureKind,$ExitCode)
    return [InvalidOperationException]::new("initdb failed: $FailureKind/$ExitCode")
}
function New-TicketboxInstallCompensationAggregateFailure {
    param($InstallFailure,$CompensationFailure)
    return [AggregateException]::new('cleanup failed', @($InstallFailure,$CompensationFailure))
}

function Invoke-TestScenario([string]$Scenario) {
    $script:scenario = $Scenario
    $script:receiptWrites = 0
    $script:receiptRemoves = 0
    $script:disableCalls = 0
    $script:passwordWrites = 0
    $script:passwordRemoves = 0
    $script:identityPublishes = 0
    $script:scCalls = @()
    $script:receipt = $null
    $authority = New-TicketboxInstallServiceCompensationAuthority
    $caught = $null
    try {
        Invoke-TicketboxServiceOwnedInitdb `
            -BootstrapState $bootstrap `
            -CompensationAuthority $authority `
            -DataRoot 'C:\ProgramData\Ticketbox' `
            -AppData 'C:\ProgramData\Ticketbox\app' `
            -SecretByteCount 32 | Out-Null
    }
    catch { $caught = $_.Exception }
    if ($null -eq $caught) { throw "$Scenario did not fail" }
    return [pscustomobject]@{
        Failure = $caught
        ReceiptWrites = $script:receiptWrites
        ReceiptRemoves = $script:receiptRemoves
        DisableCalls = $script:disableCalls
        PasswordWrites = $script:passwordWrites
        PasswordRemoves = $script:passwordRemoves
        IdentityPublishes = $script:identityPublishes
        ScCalls = @($script:scCalls)
        Authority = [string]$authority.PostgresService
    }
}

$preexisting = Invoke-TestScenario 'preexisting'
if ($preexisting.ReceiptWrites -ne 0 -or $preexisting.ScCalls.Count -ne 0 -or
    $preexisting.DisableCalls -ne 0 -or $preexisting.PasswordRemoves -ne 0 -or
    $preexisting.IdentityPublishes -ne 0 -or $preexisting.Authority -cne 'none') {
    throw 'pre-existing collision crossed the create-only read boundary'
}

$race = Invoke-TestScenario 'race'
if ($race.ReceiptWrites -ne 1 -or $race.ScCalls.Count -ne 1 -or
    $race.ScCalls[0] -cne 'create' -or $race.DisableCalls -ne 0 -or
    $race.ReceiptRemoves -ne 1 -or $race.PasswordWrites -ne 0 -or
    $race.IdentityPublishes -ne 0 -or $race.Authority -cne 'none') {
    throw 'create race mutated or disabled the colliding foreign service'
}

foreach ($failureScenario in @('hang','cluster','exit23')) {
    $failure = Invoke-TestScenario $failureScenario
    if ($failure.Failure.Data['TicketboxInstallPublicFailureCode'] -cne
        'postgres_cluster_initialization_failed') {
        throw "$failureScenario was not mapped to the public initdb failure terminal"
    }
    if ($failure.ReceiptWrites -ne 1 -or $failure.ReceiptRemoves -ne 0 -or
        $failure.DisableCalls -ne 1 -or $failure.PasswordRemoves -ne 1 -or
        $failure.IdentityPublishes -ne 1 -or
        $failure.Authority -cne 'created_by_installer') {
        throw "$failureScenario did not preserve the recoverable service receipt boundary"
    }
}
"""
    template = template.replace(
        "__FUNCTION_LOADER__",
        "\n".join(
            _powershell_function_loader(install_script, function_name)
            for function_name in (
                "New-TicketboxInstallServiceCompensationAuthority",
                "Assert-TicketboxInstallServiceCompensationAuthority",
                "Grant-TicketboxInstallServiceCompensationAuthority",
                "Invoke-TicketboxServiceOwnedInitdb",
            )
        ),
    )
    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"production-initdb-failures-{index}.ps1"
        harness.write_text(template, encoding="utf-8-sig")
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_outer_install_compensation_refuses_unclassified_service_races(
    tmp_path: Path,
) -> None:
    install_script = PACKAGING / "install_bundled_services.ps1"
    install = _read("install_bundled_services.ps1")
    mutation = install[install.index("$mutationStarted = $true") :]
    assert mutation.index("if ($hadExistingBackendService)") < mutation.index("Stop-ServiceIfExists")
    assert "-ServiceCompensationAuthority $serviceCompensationAuthority" in mutation

    loaders = "\n".join(
        _powershell_function_loader(install_script, function_name)
        for function_name in (
            "New-TicketboxInstallServiceCompensationAuthority",
            "Assert-TicketboxInstallServiceCompensationAuthority",
            "Grant-TicketboxInstallServiceCompensationAuthority",
            "Invoke-TicketboxInstallFailureCompensation",
        )
    )
    template = r"""
$ErrorActionPreference = 'Stop'
__FUNCTION_LOADERS__

$script:BackendServiceName = 'TicketboxBackend'
$script:BackendPort = 8001
$script:BackendExe = 'C:\Program Files\Ticketbox\backend.exe'
$script:ShawlExe = 'C:\Program Files\Ticketbox\shawl.exe'
$script:PgServiceName = 'TicketboxPg'
$script:PgPort = 5440
$script:PgCtl = 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe'
$script:PgBin = 'C:\Program Files\Ticketbox\pg\bin'
$script:InitdbExe = 'C:\Program Files\Ticketbox\pg\bin\initdb.exe'
$script:InitdbServiceReceiptPath = 'C:\ProgramData\Ticketbox\installer-state\initdb.json'
$script:InstallerState = 'C:\ProgramData\Ticketbox\installer-state'
$script:LegacyRecoveryRequiredPath = 'C:\ProgramData\Ticketbox\legacy-recovery'
$script:RecoveryRequiredPath = 'C:\ProgramData\Ticketbox\installer-state\recovery.json'
$script:InstallDir = 'C:\Program Files\Ticketbox'
$script:DataRoot = 'C:\ProgramData\Ticketbox'
$script:ServiceAppData = 'C:\ProgramData\Ticketbox\app'
$script:SecretByteCount = 32
$script:ServiceWaitArguments = @{ TimeoutMilliseconds = 1000; PollMilliseconds = 1 }

function Service-Exists { param($Name) return $true }
function Assert-TicketboxRuntimeAbsent {
    param($Name,$RuntimePort,$ExpectedRuntimeExecutables)
    $script:runtimeAbsenceChecks += 1
}
function Disable-TicketboxOwnedServiceIfExists {
    param(
        $Name,$ExpectedExecutable,$BackendPort,$ExpectedRuntimeExecutables,
        $TimeoutMilliseconds,$PollMilliseconds
    )
    $script:disableNames += [string]$Name
}
function Get-TicketboxServiceExecutablePath {
    param($Name)
    $script:executableReads += 1
    return $script:PgCtl
}
function Test-TicketboxPathEquals { param($Left,$Right) return $Left -ceq $Right }
function Assert-TicketboxPgClusterStoppedAfterFailure {
    $script:clusterChecks += 1
}
function Ensure-TicketboxInstallerRecoveryMarkerAfterFailure {
    param($InstallerStatePath,$LegacyPath,$CurrentPath,$InstallDir,$DataRoot,$Reason)
    $script:markerWrites += 1
}

$script:disableNames = @()
$script:runtimeAbsenceChecks = 0
$script:executableReads = 0
$script:clusterChecks = 0
$script:markerWrites = 0
$unauthorized = New-TicketboxInstallServiceCompensationAuthority
$caught = $null
try {
    Invoke-TicketboxInstallFailureCompensation `
        -Reason 'injected install failure' `
        -ServiceCompensationAuthority $unauthorized `
        -DataRoot $script:DataRoot `
        -AppData $script:ServiceAppData `
        -SecretByteCount $script:SecretByteCount
}
catch { $caught = $_.Exception }
if ($null -eq $caught -or
    -not [bool]$caught.Data['TicketboxInstallCompensationFailed']) {
    throw 'unclassified service race did not fail compensation closed'
}
if ($script:disableNames.Count -ne 0 -or $script:executableReads -ne 0 -or
    $script:runtimeAbsenceChecks -ne 0) {
    throw 'unclassified service race crossed a mutation or ownership-inference boundary'
}
if ($script:markerWrites -ne 1 -or $script:clusterChecks -ne 1) {
    throw 'unclassified service race skipped independent recovery convergence'
}

$script:disableNames = @()
$script:runtimeAbsenceChecks = 0
$script:executableReads = 0
$script:clusterChecks = 0
$script:markerWrites = 0
$backendOnly = New-TicketboxInstallServiceCompensationAuthority
Grant-TicketboxInstallServiceCompensationAuthority `
    -Authority $backendOnly `
    -Service BackendService `
    -Grant validated_preexisting
$caught = $null
try {
    Invoke-TicketboxInstallFailureCompensation `
        -Reason 'injected install failure' `
        -ServiceCompensationAuthority $backendOnly `
        -DataRoot $script:DataRoot `
        -AppData $script:ServiceAppData `
        -SecretByteCount $script:SecretByteCount
}
catch { $caught = $_.Exception }
if ($null -eq $caught -or
    -not [bool]$caught.Data['TicketboxInstallCompensationFailed'] -or
    ($script:disableNames -join ',') -cne 'TicketboxBackend' -or
    $script:executableReads -ne 0 -or $script:markerWrites -ne 1 -or
    $script:clusterChecks -ne 1) {
    throw 'backend-only authority crossed into PostgreSQL compensation'
}

$script:disableNames = @()
$script:runtimeAbsenceChecks = 0
$script:executableReads = 0
$script:clusterChecks = 0
$script:markerWrites = 0
$postgresOnly = New-TicketboxInstallServiceCompensationAuthority
Grant-TicketboxInstallServiceCompensationAuthority `
    -Authority $postgresOnly `
    -Service PostgresService `
    -Grant created_by_installer
$caught = $null
try {
    Invoke-TicketboxInstallFailureCompensation `
        -Reason 'injected install failure' `
        -ServiceCompensationAuthority $postgresOnly `
        -DataRoot $script:DataRoot `
        -AppData $script:ServiceAppData `
        -SecretByteCount $script:SecretByteCount
}
catch { $caught = $_.Exception }
if ($null -eq $caught -or
    -not [bool]$caught.Data['TicketboxInstallCompensationFailed'] -or
    ($script:disableNames -join ',') -cne 'TicketboxPg' -or
    $script:executableReads -ne 1 -or $script:markerWrites -ne 1 -or
    $script:clusterChecks -ne 1) {
    throw 'PostgreSQL-only authority crossed into backend compensation'
}

$script:disableNames = @()
$script:runtimeAbsenceChecks = 0
$script:executableReads = 0
$script:clusterChecks = 0
$script:markerWrites = 0
$authorized = New-TicketboxInstallServiceCompensationAuthority
Grant-TicketboxInstallServiceCompensationAuthority `
    -Authority $authorized `
    -Service BackendService `
    -Grant validated_preexisting
Grant-TicketboxInstallServiceCompensationAuthority `
    -Authority $authorized `
    -Service PostgresService `
    -Grant created_by_installer
Invoke-TicketboxInstallFailureCompensation `
    -Reason 'injected install failure' `
    -ServiceCompensationAuthority $authorized `
    -DataRoot $script:DataRoot `
    -AppData $script:ServiceAppData `
    -SecretByteCount $script:SecretByteCount
if (($script:disableNames -join ',') -cne 'TicketboxBackend,TicketboxPg' -or
    $script:executableReads -ne 1 -or $script:markerWrites -ne 1 -or
    $script:clusterChecks -ne 1) {
    throw 'classified service compensation did not converge through the production function'
}
""".replace("__FUNCTION_LOADERS__", loaders)

    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"production-outer-compensation-{index}.ps1"
        harness.write_text(template, encoding="utf-8-sig")
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"

    registration_loaders = "\n".join(
        _powershell_function_loader(install_script, function_name)
        for function_name in (
            "New-TicketboxInstallServiceCompensationAuthority",
            "Assert-TicketboxInstallServiceCompensationAuthority",
            "Grant-TicketboxInstallServiceCompensationAuthority",
            "Register-PgService",
            "Register-BackendService",
        )
    )
    registration_template = r"""
$ErrorActionPreference = 'Stop'
__FUNCTION_LOADERS__

$script:PgServiceName = 'TicketboxPg'
$script:BackendServiceName = 'TicketboxBackend'
$script:PgCtl = 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe'
$script:ServicePgData = 'C:\ProgramData\Ticketbox\pgdata'
$script:ShawlExe = 'C:\Program Files\Ticketbox\shawl.exe'
$script:ServiceAppData = 'C:\ProgramData\Ticketbox\app'
$script:ServiceLogDir = 'C:\ProgramData\Ticketbox\logs'
$script:BackendExe = 'C:\Program Files\Ticketbox\backend.exe'
$script:PgDump = 'C:\Program Files\Ticketbox\pg\bin\pg_dump.exe'
$script:PgRestore = 'C:\Program Files\Ticketbox\pg\bin\pg_restore.exe'
$script:ServiceBootstrapExposureRecoveryGuardPath = 'C:\ProgramData\Ticketbox\bootstrap.guard'
$script:InstallerRuntimeRecoveryGuardPath = 'C:\ProgramData\Ticketbox\runtime.guard'
$script:ServiceDataRootMarkerPath = 'C:\ProgramData\Ticketbox\.ticketbox-data-root.json'
$script:ServiceDataVolumeIdentity = '\\?\Volume{11111111-1111-1111-1111-111111111111}\'
$script:OwnerRecoveryChannel = 'managed_host'
$script:StopTimeoutMs = 25000
$script:RestartDelayMs = 5000

function Write-Step { param($Message) }
function New-TicketboxPgServiceImagePath {
    param($PgCtlPath,$ServiceName,$DataRoot)
    return 'trusted-pg-image'
}
function New-TicketboxShawlServiceImagePath {
    param(
        $ShawlPath,$ServiceName,$WorkingDirectory,$LogDirectory,$BackendPath,
        $PgDumpPath,$PgRestorePath,$BootstrapRecoveryGuardPath,
        $InstallerRecoveryGuardPath,$DataRootMarkerPath,$DataVolumeIdentity,
        $OwnerRecoveryChannel,$StopTimeoutMs,$RestartDelayMs
    )
    return 'trusted-backend-image'
}
function Service-Exists { param($Name) return $false }
function Invoke-ScChecked {
    param([string[]]$ScArgs)
    $script:scCalls += (($ScArgs[0..1] -join ':'))
    if ([string]$ScArgs[0] -ceq 'create') {
        throw [InvalidOperationException]::new('injected sc create race')
    }
    return 0
}
function Get-TicketboxServiceExecutablePath {
    param($Name)
    $script:ownershipReads += 1
    return 'foreign.exe'
}
function Assert-TicketboxServiceOwnership {
    param($Name,$ExpectedExecutable)
    $script:ownershipReads += 1
}

foreach ($serviceKind in @('PostgresService','BackendService')) {
    $script:scCalls = @()
    $script:ownershipReads = 0
    $authority = New-TicketboxInstallServiceCompensationAuthority
    $caught = $null
    try {
        if ($serviceKind -ceq 'PostgresService') {
            Register-PgService `
                -CompensationAuthority $authority `
                -DataRoot 'C:\ProgramData\Ticketbox' `
                -AppData $script:ServiceAppData `
                -SecretByteCount 32
        }
        else {
            Register-BackendService -CompensationAuthority $authority
        }
    }
    catch { $caught = $_.Exception }
    $serviceName = if ($serviceKind -ceq 'PostgresService') {
        $script:PgServiceName
    }
    else {
        $script:BackendServiceName
    }
    if ($null -eq $caught -or
        ($script:scCalls -join ',') -cne "create:$serviceName" -or
        $script:ownershipReads -ne 0 -or
        [string]$authority.$serviceKind -cne 'none') {
        throw "$serviceKind create race gained compensation authority or crossed ownership mutation"
    }
}
""".replace("__FUNCTION_LOADERS__", registration_loaders)

    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"production-registration-create-races-{index}.ps1"
        harness.write_text(registration_template, encoding="utf-8-sig")
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"


def test_pg_registration_reads_back_failure_policy_before_retiring_initdb_receipt(
    tmp_path: Path,
) -> None:
    install_script = PACKAGING / "install_bundled_services.ps1"
    loaders = "\n".join(
        _powershell_function_loader(install_script, function_name)
        for function_name in (
            "New-TicketboxInstallServiceCompensationAuthority",
            "Assert-TicketboxInstallServiceCompensationAuthority",
            "Grant-TicketboxInstallServiceCompensationAuthority",
            "Register-PgService",
        )
    )
    template = r"""
$ErrorActionPreference = 'Stop'
__FUNCTION_LOADERS__

$script:PgServiceName = 'TicketboxPg'
$script:PgCtl = 'C:\Program Files\Ticketbox\pg\bin\pg_ctl.exe'
$script:ShawlExe = 'C:\Program Files\Ticketbox\shawl.exe'
$script:ServicePgData = 'C:\ProgramData\Ticketbox\pgdata'
$script:InitdbPasswordPath = 'C:\ProgramData\Ticketbox\.ticketbox-initdb-password'
$script:InitdbServiceReceiptPath = 'C:\ProgramData\Ticketbox\installer-state\initdb.json'
$script:ScmFailureResetSeconds = 86400
$script:ScmRestartActions = 'restart/5000/restart/5000/restart/5000'
$script:PgServiceLogonAccount = 'NT AUTHORITY\LocalService'
$script:TargetServiceSidType = 'unrestricted'
$script:ReleaseConfig = [pscustomobject]@{ scm_restart_delays_ms = @(5000,5000,5000) }

function Write-Step { param($Message) }
function Write-Ok { param($Message) }
function New-TicketboxPgServiceImagePath {
    param($PgCtlPath,$ServiceName,$DataRoot)
    return 'trusted-pg-image'
}
function Service-Exists { param($Name) return $true }
function Get-TicketboxServiceExecutablePath { param($Name) return $script:ShawlExe }
function Test-TicketboxPathEquals { param($Left,$Right) return $Left -ceq $Right }
function Read-TicketboxCurrentInitdbServiceReceipt {
    return [pscustomobject]@{ phase = 'initdb_succeeded' }
}
function Assert-TicketboxInitdbServiceConfiguration { param($Receipt,$StartMode) }
function Assert-TicketboxFreshPgClusterComplete {}
function Get-TicketboxPathEntryKindNoFollow { param($Path) return 'Missing' }
function Repair-PostgresBootstrapRecoveryFileAcl { param($DataRoot,$AppData,$SecretByteCount); return $false }
function Get-PostgresBootstrapRecoveryPath { param($AppData); return $script:InitdbPasswordPath }
function Read-PostgresBootstrapRecoveryState { param($Path,$AppData,$SecretByteCount) return $null }
function Invoke-ScChecked { param([string[]]$ScArgs) return 0 }
function Assert-TicketboxServiceOwnership { param($Name,$ExpectedExecutable) return $true }
function Set-TicketboxServiceIdentityContract {
    param($Name,$LogonAccount,$SidType)
    if ($Name -cne 'TicketboxPg' -or
        $LogonAccount -cne 'NT AUTHORITY\LocalService' -or
        $SidType -cne 'unrestricted') {
        throw 'service identity publish contract drifted'
    }
}
function Assert-TicketboxReleaseServiceIdentity {
    param($Name,$InstalledConfig,$TargetConfig)
    if ($Name -cne 'TicketboxPg' -or $InstalledConfig -ne $TargetConfig) {
        throw 'service identity readback contract drifted'
    }
}
function Assert-TicketboxPgServiceCommand {
    param($Name,$ExpectedExecutable,$ExpectedServiceName,$ExpectedDataRoot)
}
function Assert-TicketboxServiceStartMode { param($Name,$ExpectedStartMode) }
function Assert-ExpectedServiceConfiguration { param($Name) }
function Assert-TicketboxServiceFailurePolicy {
    param($Name,$ExpectedResetSeconds,$ExpectedRestartDelaysMs)
    $script:policyChecks += 1
    if ($script:injectPolicyReadbackFailure) {
        throw 'injected failure-command no-op detected by readback'
    }
}
function Set-TicketboxCurrentInitdbServiceReceiptPhase {
    param($Receipt,$Phase)
    $script:receiptPhaseWrites += 1
    $Receipt.phase = $Phase
    return $Receipt
}
function Remove-TicketboxInitdbServiceReceipt {
    param($Path,$Receipt)
    $script:receiptRemoves += 1
    $script:receiptPresent = $false
}
function Test-Path { param($LiteralPath) return $script:receiptPresent }

$authority = New-TicketboxInstallServiceCompensationAuthority
Grant-TicketboxInstallServiceCompensationAuthority `
    -Authority $authority `
    -Service PostgresService `
    -Grant created_by_installer
$script:policyChecks = 0
$script:receiptPhaseWrites = 0
$script:receiptRemoves = 0
$script:receiptPresent = $true
$script:injectPolicyReadbackFailure = $true
$caught = $null
try {
    Register-PgService `
        -RuntimeBindingTransition `
        -CompensationAuthority $authority `
        -DataRoot 'C:\ProgramData\Ticketbox' `
        -AppData 'C:\ProgramData\Ticketbox\app' `
        -SecretByteCount 32
}
catch { $caught = $_.Exception }
if ($null -eq $caught -or $script:policyChecks -ne 1 -or
    $script:receiptPhaseWrites -ne 0 -or $script:receiptRemoves -ne 0 -or
    -not $script:receiptPresent) {
    throw 'failure-policy no-op retired the initdb recovery receipt'
}

$script:policyChecks = 0
$script:receiptPhaseWrites = 0
$script:receiptRemoves = 0
$script:receiptPresent = $true
$script:injectPolicyReadbackFailure = $false
Register-PgService `
    -RuntimeBindingTransition `
    -CompensationAuthority $authority `
    -DataRoot 'C:\ProgramData\Ticketbox' `
    -AppData 'C:\ProgramData\Ticketbox\app' `
    -SecretByteCount 32
if ($script:policyChecks -ne 1 -or $script:receiptPhaseWrites -ne 1 -or
    $script:receiptRemoves -ne 1 -or $script:receiptPresent) {
    throw 'verified failure policy did not retire the initdb recovery receipt exactly once'
}
""".replace("__FUNCTION_LOADERS__", loaders)

    for index, engine in enumerate(powershell_contract_engines()):
        harness = tmp_path / f"production-pg-policy-readback-{index}.ps1"
        harness.write_text(template, encoding="utf-8-sig")
        result = subprocess.run(
            [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", harness],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
