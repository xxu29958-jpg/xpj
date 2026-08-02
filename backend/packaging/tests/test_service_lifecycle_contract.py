import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import test_c07_lifecycle_artifacts as c07_lifecycle_support
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.xdist_group(name="windows_powershell_lifecycle")

PACKAGING = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig")


def _ps_literal(path: str | Path) -> str:
    return str(path).replace("'", "''")


def test_database_tools_are_bounded_under_powershell_51_and_7(tmp_path: Path) -> None:
    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    c07_packaged_migration = PACKAGING / "windows_c07_packaged_migration.ps1"
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
. '{_ps_literal(c07_packaged_migration)}'
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
$isolatedEnvironment = New-TicketboxC07MigrationHelperChildEnvironment `
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
        -HeartbeatIntervalMilliseconds 1000 `
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
            "sentinel": "保留-小票夹",
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
    $alive = @(
        $pids | Where-Object {{
            $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue)
        }}
    )
    if ($pids.Count -ne 3 -or $alive.Count -ne 0) {{
        throw "wrapper returned before process-tree settlement: pids=$($pids -join ',') alive=$($alive -join ',')"
    }}
    $before = (Get-Item -LiteralPath $MarkerPath -Force -ErrorAction Stop).Length
    Start-Sleep -Milliseconds 200
    $after = (Get-Item -LiteralPath $MarkerPath -Force -ErrorAction Stop).Length
    if ($after -ne $before) {{
        throw "descendant marker grew after wrapper return: before=$before after=$after"
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
    $stdinKilled = $stdinFailureMessage -notlike '*超过允许*'
}}
$stdinWatch.Stop()
if (-not $stdinKilled) {{ throw "stdin failure was converted into a timeout: $stdinFailureMessage" }}
if ($stdinWatch.ElapsedMilliseconds -ge 3000) {{ throw 'stdin failure cleanup was not bounded' }}
Assert-TreeSettledAtReturn '{_ps_literal(stdin_pids)}' '{_ps_literal(stdin_marker)}'

# Deterministically inject an unconfirmed settlement after performing the real
# kill. The wrapper must retain both the action failure and the typed settlement
# failure; neither may be flattened into a generic cleanup message.
function Stop-TicketboxBoundedNativeProcessTree {{
    param(
        [object]$NativeProcess,
        [int]$SettlementMilliseconds
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
        $failure.Data['TicketboxC07FailureCode'] -ceq 'tree_termination_unconfirmed' -and
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


def test_c07_heartbeat_helper_uses_minimal_real_ps51_environment(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows C07 heartbeat helper environment contract")

    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    lifecycle_lock = PACKAGING / "windows_lifecycle_lock.ps1"
    c07_lifecycle = PACKAGING / "windows_c07_lifecycle.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    heartbeat_helper = PACKAGING / "windows_c07_heartbeat_helper.ps1"
    probe = tmp_path / "heartbeat-helper-environment-probe.ps1"
    probe.write_text(
        """
$names = @(Get-ChildItem Env: | ForEach-Object { [string]$_.Name })
$modulePaths = @(
    $env:PSModulePath -split ';' |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
$missingModulePaths = @(
    $modulePaths |
        Where-Object { -not (Test-Path -LiteralPath $_ -PathType Container) }
)
[ordered]@{
    ps_major = [int]$PSVersionTable.PSVersion.Major
    github_pat_visible = $names -icontains 'GITHUB_PAT'
    docker_auth_visible = $names -icontains 'DOCKER_AUTH_CONFIG'
    pgpassword_visible = $names -icontains 'PGPASSWORD'
    database_url_visible = $names -icontains 'DATABASE_URL'
    aws_access_key_visible = $names -icontains 'AWS_ACCESS_KEY_ID'
    arbitrary_visible =
        $names -icontains 'TICKETBOX_C07_ARBITRARY_CONTEXT'
    ambient_module_path_visible =
        $env:PSModulePath -like '*synthetic-ambient-module-path*'
    system_root_exists =
        Test-Path -LiteralPath $env:SystemRoot -PathType Container
    windir_matches_system_root =
        [IO.Path]::GetFullPath($env:WINDIR) -ceq
            [IO.Path]::GetFullPath($env:SystemRoot)
    comspec_exists = Test-Path -LiteralPath $env:ComSpec -PathType Leaf
    temp_exists = Test-Path -LiteralPath $env:TEMP -PathType Container
    local_app_data_exists =
        Test-Path -LiteralPath $env:LOCALAPPDATA -PathType Container
    tmp_matches_temp =
        [IO.Path]::GetFullPath($env:TMP) -ceq
            [IO.Path]::GetFullPath($env:TEMP)
    module_paths_exist = $missingModulePaths.Count -eq 0
    module_paths = $modulePaths
    names = @($names | Sort-Object)
} | ConvertTo-Json -Depth 4 -Compress
""",
        encoding="utf-8-sig",
    )
    ambient = {
        "GITHUB_PAT": "synthetic-github-pat",
        "DOCKER_AUTH_CONFIG": '{"auths":{"registry.invalid":{"auth":"x"}}}',
        "PGPASSWORD": "synthetic-postgres-password",
        "DATABASE_URL": "postgresql://synthetic.invalid/ticketbox",
        "AWS_ACCESS_KEY_ID": "synthetic-access-key",
        "TICKETBOX_C07_ARBITRARY_CONTEXT": "synthetic-unlisted-secret",
        "PSModulePath": "C:\\synthetic-ambient-module-path",
    }
    for index, coordinator_engine in enumerate(powershell_contract_engines()):
        no_mode = subprocess.run(  # noqa: S603
            [
                coordinator_engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(heartbeat_helper),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        assert no_mode.returncode != 0
        assert "-TicketboxC07HeartbeatHelper" in no_mode.stderr
        profile_probe = tmp_path / f"heartbeat-dependency-profile-{index}.ps1"
        profile_probe.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(lifecycle_lock)}'
. '{_ps_literal(c07_lifecycle)}'
$fullFailure = ''
try {{ Assert-TicketboxC07Dependencies }}
catch {{ $fullFailure = $_.Exception.Message }}
if ($fullFailure -notlike '*full*Assert-TicketboxC07LiveHostConnection*') {{
    throw "full dependency profile did not fail closed: $fullFailure"
}}
. '{_ps_literal(c07_lifecycle)}' `
    -TicketboxC07DependencyProfile 'durable_heartbeat'
Assert-TicketboxC07Dependencies
Remove-Item `
    -LiteralPath Function:\\Read-TicketboxInstalledBuildManifest `
    -Force
$durableFailure = ''
try {{ Assert-TicketboxC07Dependencies }}
catch {{ $durableFailure = $_.Exception.Message }}
if (
    $durableFailure -notlike
        '*durable_heartbeat*Read-TicketboxInstalledBuildManifest*'
) {{
    throw "durable dependency profile did not fail closed: $durableFailure"
}}
"dependency_profiles_fail_closed"
""",
            encoding="utf-8-sig",
        )
        profile_result = subprocess.run(  # noqa: S603
            [
                coordinator_engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(profile_probe),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=15,
        )
        assert profile_result.returncode == 0, (
            profile_result.stdout + profile_result.stderr
        )
        assert "dependency_profiles_fail_closed" in profile_result.stdout
        harness = tmp_path / f"heartbeat-helper-environment-{index}.ps1"
        ambient_assignment = "\n".join(
            "[Environment]::SetEnvironmentVariable("
            f"'{name}', '{value.replace(chr(39), chr(39) * 2)}', "
            "[EnvironmentVariableTarget]::Process)"
            for name, value in ambient.items()
        )
        parent_checks = " -and\n        ".join(
            "[Environment]::GetEnvironmentVariable("
            f"'{name}', [EnvironmentVariableTarget]::Process) -ceq "
            f"'{value.replace(chr(39), chr(39) * 2)}'"
            for name, value in ambient.items()
        )
        harness.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(database_safety)}'
{ambient_assignment}
$childEnvironment = New-TicketboxC07HeartbeatHelperChildEnvironment
$helperExecutable = Get-TicketboxC07HeartbeatHelperExecutablePath
$result = Invoke-TicketboxBoundedNativeProcess `
    -FilePath $helperExecutable `
    -Arguments @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        '{_ps_literal(probe)}'
    ) `
    -TimeoutMilliseconds 15000 `
    -TerminationSettlementMilliseconds 1000 `
    -Label 'heartbeat helper environment probe' `
    -ChildEnvironment $childEnvironment
$parentEnvironmentUnchanged =
    {parent_checks}
[ordered]@{{
    helper_executable = $helperExecutable
    allowlist_names = @($childEnvironment.Keys | Sort-Object)
    parent_environment_unchanged = $parentEnvironmentUnchanged
    probe = $result.StandardOutput.Trim() | ConvertFrom-Json
}} | ConvertTo-Json -Depth 6 -Compress
""",
            encoding="utf-8-sig",
        )
        completed = subprocess.run(  # noqa: S603
            [
                coordinator_engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=45,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        evidence = json.loads(completed.stdout.strip().splitlines()[-1])
        assert evidence["helper_executable"].lower().endswith(
            "\\windowspowershell\\v1.0\\powershell.exe"
        )
        assert evidence["allowlist_names"] == [
            "ComSpec",
            "LOCALAPPDATA",
            "PATH",
            "PATHEXT",
            "PSModulePath",
            "SystemRoot",
            "TEMP",
            "TMP",
            "WINDIR",
        ]
        assert evidence["parent_environment_unchanged"] is True
        child = evidence["probe"]
        assert child["ps_major"] == 5
        assert child["github_pat_visible"] is False
        assert child["docker_auth_visible"] is False
        assert child["pgpassword_visible"] is False
        assert child["database_url_visible"] is False
        assert child["aws_access_key_visible"] is False
        assert child["arbitrary_visible"] is False
        assert child["ambient_module_path_visible"] is False
        assert child["system_root_exists"] is True
        assert child["windir_matches_system_root"] is True
        assert child["comspec_exists"] is True
        assert child["temp_exists"] is True
        assert child["local_app_data_exists"] is True
        assert child["tmp_matches_temp"] is True
        assert child["module_paths_exist"] is True
        assert len(child["module_paths"]) == 2
        normalized_module_paths = [
            path.replace("/", "\\").lower() for path in child["module_paths"]
        ]
        assert normalized_module_paths[0].endswith(
            "\\windowspowershell\\modules"
        )
        assert normalized_module_paths[1].endswith(
            "\\windowspowershell\\v1.0\\modules"
        )


def test_production_c07_heartbeat_operation_is_bounded_and_fully_reaped(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows C07 durable heartbeat contract")

    database_safety = PACKAGING / "windows_database_safety.ps1"
    heartbeat_helper = PACKAGING / "windows_c07_heartbeat_helper.ps1"
    recovery_generation = PACKAGING / "windows_c07_recovery_generation.ps1"
    tree_script = tmp_path / "production-heartbeat-tree.py"
    tree_script.write_text(
        """import os
import subprocess
import sys
import time

pid_path = sys.argv[1]
marker_path = sys.argv[2]
depth = int(sys.argv[3])
with open(pid_path, "a", encoding="ascii") as pid_file:
    pid_file.write(str(os.getpid()) + "\\n")
    pid_file.flush()
    os.fsync(pid_file.fileno())
if depth > 0:
    child = subprocess.Popen(
        [sys.executable, __file__, pid_path, marker_path, str(depth - 1)],
        close_fds=True,
    )
    child.wait()
else:
    while True:
        with open(marker_path, "a", encoding="ascii") as marker_file:
            marker_file.write("x")
            marker_file.flush()
            os.fsync(marker_file.fileno())
        time.sleep(0.01)
""",
        encoding="utf-8",
    )
    malformed_helper = tmp_path / "malformed-heartbeat-helper.ps1"
    malformed_helper.write_text(
        """param([switch]$TicketboxC07HeartbeatHelper)
[Console]::In.ReadToEnd() | Out-Null
[Console]::Out.WriteLine('not-json')
exit 0
""",
        encoding="utf-8-sig",
    )
    multiple_helper = tmp_path / "multiple-heartbeat-helper.ps1"
    multiple_helper.write_text(
        """param([switch]$TicketboxC07HeartbeatHelper)
[Console]::In.ReadToEnd() | Out-Null
[Console]::Out.WriteLine('{}')
[Console]::Out.WriteLine('{}')
exit 0
""",
        encoding="utf-8-sig",
    )
    missing_helper = tmp_path / "missing-heartbeat-helper.ps1"
    missing_helper.write_text(
        """param([switch]$TicketboxC07HeartbeatHelper)
[Console]::In.ReadToEnd() | Out-Null
exit 0
""",
        encoding="utf-8-sig",
    )
    for index, engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"production-heartbeat-{index}"
        prefix, data_root, _, _ = c07_lifecycle_support._common_harness(root)
        business_pids = root / "business-tree.pids"
        business_marker = root / "business-tree.marker"
        helper_pids = root / "helper-tree.pids"
        helper_marker = root / "helper-tree.marker"
        helper_host_pid = root / "helper-host.pid"
        alternate_lock_root = root / "alternate-lock-root"
        alternate_lock_root.mkdir()
        alternate_primary_lock = alternate_lock_root / "installer-lifecycle.lock"
        alternate_operation_lock = alternate_lock_root / "installer-operation.lock"
        alternate_primary_lock.write_bytes(b"not-held\n")
        alternate_operation_lock.write_bytes(b"not-held\n")
        blocking_helper = root / "blocking-heartbeat-helper.ps1"
        blocking_helper.write_text(
            f"""param([switch]$TicketboxC07HeartbeatHelper)
[Console]::In.ReadToEnd() | Out-Null
[IO.File]::WriteAllText(
    '{_ps_literal(helper_host_pid)}',
    [string]$PID,
    [Text.Encoding]::ASCII
)
& '{_ps_literal(sys.executable)}' `
    '{_ps_literal(tree_script)}' `
    '{_ps_literal(helper_pids)}' `
    '{_ps_literal(helper_marker)}' `
    '1'
exit $LASTEXITCODE
""",
            encoding="utf-8-sig",
        )
        harness = root / "production-heartbeat.ps1"
        harness.write_text(
            prefix
            + f"""
. '{_ps_literal(database_safety)}'
. '{_ps_literal(recovery_generation)}'
$lifecycleLock = Enter-TicketboxLifecycleLock `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock $lifecycleLock `
        -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_ps_literal(data_root)}'
    $context = [pscustomobject]@{{
        Authority = $authority
        LifecycleLock = $lifecycleLock
    }}
    $missingBudgetRejected = $false
    try {{
        Get-TicketboxC07RecoveryHeartbeatOperation $context | Out-Null
    }}
    catch {{
        $missingBudgetRejected =
            $_.Exception.Message -like '*active budget*'
    }}
    if (-not $missingBudgetRejected) {{
        throw 'typed heartbeat operation accepted a missing active budget'
    }}
    $script:TicketboxC07ActiveMaintenanceBudget =
        New-TicketboxC07MaintenanceBudget $authority
    $productionHeartbeat =
        Get-TicketboxC07RecoveryHeartbeatOperation $context
    function Get-TicketboxC07HeartbeatHelperScriptPath {{
        return '{_ps_literal(heartbeat_helper)}'
    }}
    $before = [int64](
        Read-TicketboxC07Heartbeat $authority
    ).Payload.sequence
    $returnedSequence = Invoke-TicketboxBoundedHeartbeatOperation `
        -Operation $productionHeartbeat `
        -TimeoutMilliseconds 15000 `
        -SettlementMilliseconds 1000 `
        -Label 'production C07 heartbeat operation smoke'
    $after = [int64](
        Read-TicketboxC07Heartbeat $authority
    ).Payload.sequence
    if ($after -le $before) {{
        throw 'typed heartbeat operation did not advance durable sequence'
    }}
    if ($returnedSequence -ne $after) {{
        throw 'helper result sequence differs from durable heartbeat'
    }}
    if ($null -eq (Get-Process -Id $PID -ErrorAction SilentlyContinue)) {{
        throw 'normal heartbeat error path terminated the coordinator'
    }}

    # The ordinary authority reader must retain the live database probe. The
    # helper's durable projection is the only credential-free exception.
    $liveDatabaseReader = (Get-Command `
        Get-TicketboxC07LiveDatabaseAuthority).ScriptBlock
    function Get-TicketboxC07LiveDatabaseAuthority {{
        throw 'injected ordinary live database probe'
    }}
    $ordinaryReaderRejected = $false
    try {{ Read-TicketboxC07Authority '{_ps_literal(data_root)}' | Out-Null }}
    catch {{
        $ordinaryReaderRejected =
            $_.Exception.Message -like '*ordinary live database probe*'
    }}
    Read-TicketboxC07DurableHeartbeatAuthority `
        '{_ps_literal(data_root)}' | Out-Null
    Set-Item `
        -LiteralPath Function:\\Get-TicketboxC07LiveDatabaseAuthority `
        -Value $liveDatabaseReader
    if (-not $ordinaryReaderRejected) {{
        throw 'ordinary authority reader bypassed the live database probe'
    }}

    function New-TestHeartbeatOperation {{
        param(
            [string]$OperationId = $productionHeartbeat.OperationId,
            [string]$DescriptorSha256 =
                $productionHeartbeat.DescriptorSha256,
            [string]$BindingSha256 =
                $productionHeartbeat.CoordinatorBindingSha256,
            [string]$AttemptId =
                $productionHeartbeat.MaintenanceAttemptId,
            [string]$AttemptSha256 =
                $productionHeartbeat.MaintenanceAttemptSha256,
            [int64]$AttemptSequence =
                $productionHeartbeat.MaintenanceAttemptSequence,
            [uint32]$StartedLow =
                $productionHeartbeat.CoordinatorStartedFileTimeLow,
            [string]$PrimaryLockPath =
                $productionHeartbeat.PrimaryLifecycleLockPath,
            [string]$OperationLockPath =
                $productionHeartbeat.OperationLifecycleLockPath,
            [object]$OperationLease = $lifecycleLock
        )
        return [TicketboxC07DurableHeartbeatOperation]::new(
            [string]$productionHeartbeat.DataRoot,
            $OperationLease,
            $OperationId,
            $DescriptorSha256,
            $BindingSha256,
            [int64]$productionHeartbeat.CoordinatorBindingSequence,
            $AttemptId,
            $AttemptSha256,
            $AttemptSequence,
            [int]$productionHeartbeat.CoordinatorProcessId,
            [uint32]$productionHeartbeat.CoordinatorStartedFileTimeHigh,
            $StartedLow,
            [DateTime]$productionHeartbeat.DeadlineUtc,
            [int64]$productionHeartbeat.GetRemainingCeilingMilliseconds(),
            [string[]]$productionHeartbeat.HostFullControlAccounts,
            [string]$productionHeartbeat.HostOwnerAccount,
            [string[]]$productionHeartbeat.InstallationIdentityAclAccounts,
            [string]$productionHeartbeat.InstallationIdentityOwnerAccount,
            $PrimaryLockPath,
            $OperationLockPath
        )
    }}
    $differentStartedLow = if (
        [uint32]$productionHeartbeat.CoordinatorStartedFileTimeLow -eq
            [uint32]::MaxValue
    ) {{
        [uint32](
            [uint32]$productionHeartbeat.CoordinatorStartedFileTimeLow - 1
        )
    }} else {{
        [uint32](
            [uint32]$productionHeartbeat.CoordinatorStartedFileTimeLow + 1
        )
    }}
    $tamperedOperations = @(
        (New-TestHeartbeatOperation `
            -OperationId '123e4567-e89b-42d3-a456-426614174099'),
        (New-TestHeartbeatOperation -DescriptorSha256 ('E' * 64)),
        (New-TestHeartbeatOperation -StartedLow $differentStartedLow),
        (New-TestHeartbeatOperation `
            -PrimaryLockPath '{_ps_literal(alternate_primary_lock)}' `
            -OperationLockPath '{_ps_literal(alternate_operation_lock)}'),
        (New-TestHeartbeatOperation `
            -OperationLease ([pscustomobject]@{{
                Primary = $null
                Operation = $null
                ExternalOwnerIdentity = $null
            }}))
    )
    foreach ($tampered in $tamperedOperations) {{
        $tamperRejected = $false
        try {{
            Invoke-TicketboxBoundedHeartbeatOperation `
                -Operation $tampered `
                -TimeoutMilliseconds 15000 `
                -SettlementMilliseconds 1000 `
                -Label 'tampered heartbeat descriptor' | Out-Null
        }}
        catch {{
            $tamperRejected =
                [string]$_.Exception.Data['TicketboxC07FailureCode'] -like
                    'heartbeat_helper_*'
        }}
        if (-not $tamperRejected) {{
            throw 'tampered heartbeat descriptor was accepted'
        }}
        if ($null -eq (Get-Process -Id $PID -ErrorAction SilentlyContinue)) {{
            throw 'tampered descriptor error terminated coordinator'
        }}
    }}

    foreach ($badHelper in @(
        '{_ps_literal(malformed_helper)}',
        '{_ps_literal(multiple_helper)}',
        '{_ps_literal(missing_helper)}'
    )) {{
        $script:testHeartbeatHelperPath = $badHelper
        function Get-TicketboxC07HeartbeatHelperScriptPath {{
            return [string]$script:testHeartbeatHelperPath
        }}
        $protocolRejected = $false
        try {{
            Invoke-TicketboxBoundedHeartbeatOperation `
                -Operation $productionHeartbeat `
                -TimeoutMilliseconds 15000 `
                -SettlementMilliseconds 1000 `
                -Label 'invalid heartbeat helper protocol' | Out-Null
        }}
        catch {{
            $protocolRejected =
                $_.Exception.Data['TicketboxC07FailureCode'] -ceq
                    'heartbeat_helper_protocol_invalid'
        }}
        if (-not $protocolRejected) {{
            throw 'missing/malformed/multiple helper result was accepted'
        }}
    }}

    $script:testHeartbeatHelperPath = '{_ps_literal(blocking_helper)}'
    function Get-TicketboxC07HeartbeatHelperScriptPath {{
        return [string]$script:testHeartbeatHelperPath
    }}
    $deadlineObserved = $false
    try {{
        Invoke-TicketboxBoundedNativeProcess `
            -FilePath '{_ps_literal(sys.executable)}' `
            -Arguments @(
                '{_ps_literal(tree_script)}',
                '{_ps_literal(business_pids)}',
                '{_ps_literal(business_marker)}',
                '2'
            ) `
            -TimeoutMilliseconds 3200 `
            -HeartbeatIntervalMilliseconds 1000 `
            -HeartbeatSettlementMilliseconds 1000 `
            -HeartbeatOperation $productionHeartbeat `
            -Label 'blocking production C07 heartbeat closure' | Out-Null
    }}
    catch {{
        $deadlineObserved =
            $_.Exception.Data['TicketboxC07FailureCode'] -ceq
                'heartbeat_helper_deadline_exceeded'
    }}
    if (-not $deadlineObserved) {{
        throw 'blocking production helper escaped its absolute deadline'
    }}
    $businessProcessIds = @(
        Get-Content -LiteralPath '{_ps_literal(business_pids)}' -Encoding UTF8 |
            ForEach-Object {{ [int]$_ }}
    )
    $helperProcessIds = @(
        [int](Get-Content `
            -LiteralPath '{_ps_literal(helper_host_pid)}' `
            -Encoding UTF8)
    )
    $helperProcessIds += @(
        Get-Content `
            -LiteralPath '{_ps_literal(helper_pids)}' `
            -Encoding UTF8 | ForEach-Object {{ [int]$_ }}
    )
    $allProcessIds = @($businessProcessIds) + @($helperProcessIds)
    $alive = @(
        $allProcessIds | Where-Object {{
            $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue)
        }}
    )
    if (
        $businessProcessIds.Count -ne 3 -or
        $helperProcessIds.Count -ne 3 -or
        $alive.Count -ne 0
    ) {{
        throw "heartbeat helper/native tree returned before settlement: pids=$($allProcessIds -join ',') alive=$($alive -join ',')"
    }}
    $sequenceAtReturn = [int64](
        Read-TicketboxC07Heartbeat $authority
    ).Payload.sequence
    $businessMarkerAtReturn = (
        Get-Item `
            -LiteralPath '{_ps_literal(business_marker)}' `
            -ErrorAction Stop
    ).Length
    $helperMarkerAtReturn = (
        Get-Item `
            -LiteralPath '{_ps_literal(helper_marker)}' `
            -ErrorAction Stop
    ).Length
    Start-Sleep -Milliseconds 300
    $sequenceAfterReturn = [int64](
        Read-TicketboxC07Heartbeat $authority
    ).Payload.sequence
    if ($sequenceAfterReturn -ne $sequenceAtReturn) {{
        throw 'durable heartbeat advanced after native wrapper returned'
    }}
    $businessMarkerAfterReturn = (
        Get-Item `
            -LiteralPath '{_ps_literal(business_marker)}' `
            -ErrorAction Stop
    ).Length
    $helperMarkerAfterReturn = (
        Get-Item `
            -LiteralPath '{_ps_literal(helper_marker)}' `
            -ErrorAction Stop
    ).Length
    if (
        $businessMarkerAfterReturn -ne $businessMarkerAtReturn -or
        $helperMarkerAfterReturn -ne $helperMarkerAtReturn
    ) {{
        throw 'business/helper descendant mutated after wrapper returned'
    }}
    if ($null -eq (Get-Process -Id $PID -ErrorAction SilentlyContinue)) {{
        throw 'bounded helper failure terminated coordinator'
    }}

    # The helper is an increment-only lease renewer: it cannot recreate a
    # deleted heartbeat artifact or establish a parallel authority.
    $script:testHeartbeatHelperPath = '{_ps_literal(heartbeat_helper)}'
    $heartbeatPath = Get-TicketboxC07HeartbeatPath (
        [string]$authority.Receipt.operation_id
    )
    Remove-Item -LiteralPath $heartbeatPath -Force
    $missingHeartbeatRejected = $false
    try {{
        Invoke-TicketboxBoundedHeartbeatOperation `
            -Operation $productionHeartbeat `
            -TimeoutMilliseconds 15000 `
            -SettlementMilliseconds 1000 `
            -Label 'missing durable heartbeat' | Out-Null
    }}
    catch {{
        $missingHeartbeatRejected =
            [string]$_.Exception.Data['TicketboxC07FailureCode'] -like
                'heartbeat_helper_*'
    }}
    if (
        -not $missingHeartbeatRejected -or
        (Get-TicketboxPathEntryKindNoFollow $heartbeatPath) -cne 'Missing'
    ) {{
        throw 'helper recreated a missing heartbeat authority artifact'
    }}
}}
finally {{
    $script:TicketboxC07ActiveMaintenanceBudget = $null
    Exit-TicketboxLifecycleLock $lifecycleLock
}}
""",
            encoding="utf-8-sig",
        )
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
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_c07_heartbeat_helper_preserves_external_primary_owner_binding(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows external lifecycle-owner contract")

    installation_safety = PACKAGING / "windows_installation_safety.ps1"
    lifecycle_lock = PACKAGING / "windows_lifecycle_lock.ps1"
    database_safety = PACKAGING / "windows_database_safety.ps1"
    recovery_generation = PACKAGING / "windows_c07_recovery_generation.ps1"
    identity_script = tmp_path / "python-owner-identity.ps1"
    identity_script.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(lifecycle_lock)}'
Get-TicketboxProcessIdentity -ProcessId {os.getpid()} |
    ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
    )
    identity_result = subprocess.run(  # noqa: S603
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(identity_script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    assert identity_result.returncode == 0, identity_result.stderr
    owner_identity = json.loads(identity_result.stdout.strip().splitlines()[-1])

    for index, coordinator_engine in enumerate(powershell_contract_engines()):
        root = tmp_path / f"external-heartbeat-{index}"
        prefix, data_root, _, _ = c07_lifecycle_support._common_harness(root)
        lock_root = root / "machine"
        validation_root = root / "holder-validation"
        root_validated_path = validation_root / "root-validated.ready"
        ready_path = lock_root / "holder.ready"
        release_path = lock_root / "holder.release"
        owner_path = lock_root / "installer-lifecycle.owner"
        holder = root / "primary-holder.ps1"
        holder.write_text(
            f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(lifecycle_lock)}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Initialize-TicketboxProtectedDirectoryAtomically `
    -Path '{_ps_literal(validation_root)}' `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount | Out-Null
$ownerIdentity = New-TicketboxProcessIdentityFromFileTimeParts `
    -ProcessId {os.getpid()} `
    -StartedFileTimeHigh {owner_identity['StartedFileTimeHigh']} `
    -StartedFileTimeLow {owner_identity['StartedFileTimeLow']}
$ownerHandle = Open-TicketboxVerifiedProcessIdentityHandle `
    -ProcessId {os.getpid()} `
    -ExpectedIdentity $ownerIdentity
try {{
    Wait-TicketboxExternalInstallerLifecycleLock `
        -LockDirectory '{_ps_literal(lock_root)}' `
        -RootValidatedPath '{_ps_literal(root_validated_path)}' `
        -ReadyPath '{_ps_literal(ready_path)}' `
        -ReleasePath '{_ps_literal(release_path)}' `
        -OwnerProcessId {os.getpid()} `
        -OwnerStartedFileTimeHigh {owner_identity['StartedFileTimeHigh']} `
        -OwnerStartedFileTimeLow {owner_identity['StartedFileTimeLow']} `
        -OwnerProcessHandleLease $ownerHandle `
        -FullControlAccounts @($currentAccount) `
        -OwnerAccount $currentAccount
}}
finally {{
    Close-TicketboxProcessIdentityHandle $ownerHandle
}}
""",
            encoding="utf-8-sig",
        )
        holder_process = subprocess.Popen(  # noqa: S603
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(holder),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 20
            while (
                not ready_path.is_file()
                and holder_process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not ready_path.is_file():
                stdout, stderr = holder_process.communicate(timeout=5)
                pytest.fail(f"primary holder did not become ready:\n{stdout}\n{stderr}")
            ready_fields = dict(
                line.split("=", 1)
                for line in ready_path.read_text(encoding="utf-8").splitlines()
            )
            assert ready_fields["OWNER_PID"] == str(os.getpid())
            assert owner_path.is_file()

            coordinator = root / "external-heartbeat-coordinator.ps1"
            coordinator.write_text(
                prefix
                + f"""
. '{_ps_literal(database_safety)}'
. '{_ps_literal(recovery_generation)}'
$lifecycle = Enter-TicketboxLifecycleLock `
    -ExternalOwnerProcessId {os.getpid()} `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
try {{
    New-TicketboxC07LifecycleOperation `
        -DataRoot '{_ps_literal(data_root)}' `
        -LifecycleLock $lifecycle `
        -SuperuserPassword $script:testPassword | Out-Null
    $authority = Read-TicketboxC07Authority '{_ps_literal(data_root)}'
    $script:TicketboxC07ActiveMaintenanceBudget =
        New-TicketboxC07MaintenanceBudget $authority
    $operation = Get-TicketboxC07RecoveryHeartbeatOperation (
        [pscustomobject]@{{
            Authority = $authority
            LifecycleLock = $lifecycle
        }}
    )
    $before = [int64](Read-TicketboxC07Heartbeat $authority).Payload.sequence
    $sequence = Invoke-TicketboxBoundedHeartbeatOperation `
        -Operation $operation `
        -TimeoutMilliseconds 15000 `
        -SettlementMilliseconds 1000 `
        -Label 'external primary owner heartbeat'
    $after = [int64](Read-TicketboxC07Heartbeat $authority).Payload.sequence
    if ($sequence -ne $after -or $after -le $before) {{
        throw 'external-owner helper did not durably advance heartbeat'
    }}
}}
finally {{
    $script:TicketboxC07ActiveMaintenanceBudget = $null
    Exit-TicketboxLifecycleLock $lifecycle
}}
""",
                encoding="utf-8-sig",
            )
            completed = subprocess.run(  # noqa: S603
                [
                    coordinator_engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(coordinator),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=45,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
        finally:
            if ready_path.is_file() and holder_process.poll() is None:
                ready_fields = dict(
                    line.split("=", 1)
                    for line in ready_path.read_text(encoding="utf-8").splitlines()
                )
                release_writer = root / "release-primary-holder.ps1"
                release_writer.write_text(
                    f"""
$ErrorActionPreference = 'Stop'
. '{_ps_literal(installation_safety)}'
. '{_ps_literal(lifecycle_lock)}'
$currentAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$text =
    "STATE=release$([Environment]::NewLine)" +
    "OWNER_PID={os.getpid()}$([Environment]::NewLine)" +
    "NONCE={ready_fields['NONCE']}$([Environment]::NewLine)"
Write-TicketboxLifecycleCoordinationArtifact `
    -Path '{_ps_literal(release_path)}' `
    -Text $text `
    -FullControlAccounts @($currentAccount) `
    -OwnerAccount $currentAccount
""",
                    encoding="utf-8-sig",
                )
                release_result = subprocess.run(  # noqa: S603
                    [
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(release_writer),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=15,
                )
                assert release_result.returncode == 0, release_result.stderr
            stdout, stderr = holder_process.communicate(timeout=15)
            assert holder_process.returncode == 0, stdout + stderr
            assert not owner_path.exists()


def test_bounded_native_process_uses_suspended_job_assignment_before_resume() -> None:
    database_safety = _read("windows_database_safety.ps1")
    heartbeat_helper = _read("windows_c07_heartbeat_helper.ps1")
    heartbeat_authority = _read("windows_c07_heartbeat_authority.ps1")
    c07_lifecycle = _read("windows_c07_lifecycle.ps1")
    recovery_generation = _read("windows_c07_recovery_generation.ps1")
    native_start = database_safety[
        database_safety.index("public static TicketboxBoundedNativeProcess Start(") :
        database_safety.index("private void AssertOpen()")
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
    assert native_start.index(
        "AssignProcessToJobObject(jobHandle, processHandle)"
    ) < native_start.index("ResumeThread(threadHandle)")
    assert "TerminateCreatedProcessAndConfirm(" in native_start
    assert "TerminateProcess(processHandle, 1)" in database_safety
    settlement = database_safety[
        database_safety.index("private static void WaitForTreeSettlement(") :
        database_safety.index("private static void TerminateCreatedProcessAndConfirm(")
    ]
    assert "rootSignaled = IsProcessSignaled(processHandle)" in settlement
    assert "activeProcesses = ReadActiveProcessCount(jobHandle)" in settlement
    assert "rootSignaled && activeProcesses == 0" in settlement
    assert "tree_termination_unconfirmed" in database_safety
    assert "heartbeat_helper_deadline_exceeded" in database_safety
    assert "ticketbox-c07-heartbeat-helper-request-v1" in database_safety
    assert "ticketbox-c07-heartbeat-helper-result-v1" in database_safety
    assert r'"WindowsPowerShell\v1.0\powershell.exe"' in database_safety
    assert "new UTF8Encoding(false, true)" in database_safety
    helper_environment = database_safety[
        database_safety.index(
            "function New-TicketboxC07HeartbeatHelperChildEnvironment"
        ) : database_safety.index("function New-TicketboxC07HeartbeatHelperNonce")
    ]
    assert "Get-ChildItem Env:" not in helper_environment
    assert "GetEnvironmentVariables" not in helper_environment
    assert '"SystemRoot" = $windowsDirectory' in helper_environment
    assert '"PSModulePath" = ' in helper_environment
    assert '"TEMP" = $temporaryDirectory' in helper_environment
    assert "[PowerShell]::Create()" not in database_safety
    assert "BeginStop(" not in database_safety
    assert "[Environment]::FailFast(" not in database_safety
    assert "DatabaseAuthorityCredential" not in database_safety
    assert "database_authority_credential" not in recovery_generation
    assert "database_authority_credential" not in heartbeat_helper
    assert "DATABASE_URL" not in heartbeat_helper
    assert "windows_c07_recovery_generation.ps1" not in heartbeat_helper
    assert "windows_database_safety.ps1" not in heartbeat_helper
    assert "windows_service_contract.ps1" not in heartbeat_helper
    assert "windows_service_lifecycle.ps1" not in heartbeat_helper
    assert "windows_bundled_database.ps1" not in heartbeat_helper
    assert "windows_c07_database.ps1" not in heartbeat_helper
    assert "windows_installation_safety.ps1" in heartbeat_helper
    assert "windows_lifecycle_lock.ps1" in heartbeat_helper
    assert "windows_c07_heartbeat_authority.ps1" in heartbeat_helper
    assert "windows_c07_lifecycle.ps1" not in heartbeat_helper
    assert '-TicketboxC07DependencyProfile "durable_heartbeat"' in heartbeat_helper
    assert "windows_c07_heartbeat_authority.ps1" in c07_lifecycle
    shared_authority_load = c07_lifecycle[
        c07_lifecycle.index("$ticketboxC07HeartbeatAuthorityPath = Join-Path") :
        c07_lifecycle.index(". $ticketboxC07HeartbeatAuthorityPath")
    ]
    assert '"Assert-NoTicketboxAncestorReparsePoints"' in shared_authority_load
    assert '"Get-TicketboxPathEntryKindNoFollow"' in shared_authority_load
    assert "Get-Command `" in shared_authority_load
    assert (
        "Assert-NoTicketboxAncestorReparsePoints "
        "$ticketboxC07HeartbeatAuthorityPath"
    ) in shared_authority_load
    assert (
        "Get-TicketboxPathEntryKindNoFollow `\n"
        "        $ticketboxC07HeartbeatAuthorityPath"
    ) in shared_authority_load
    assert '[ValidateSet("full", "durable_heartbeat")]' in heartbeat_authority
    assert '$TicketboxC07DependencyProfile = "full"' in heartbeat_authority
    assert "function Assert-TicketboxC07FullDependencies" in heartbeat_authority
    assert (
        "function Assert-TicketboxC07DurableHeartbeatDependencies"
        in heartbeat_authority
    )
    assert "function Write-TicketboxC07DurableHeartbeat" in heartbeat_authority
    assert "function Write-TicketboxC07DurableHeartbeat" not in c07_lifecycle
    for forbidden_definition in (
        "Assert-TicketboxC07LiveHostConnection",
        "Get-TicketboxC07DatabaseIdentity",
        "Get-TicketboxExpectedRuntimeProcessIds",
        "Get-TicketboxListeningProcessIds",
        "Get-TicketboxServiceProcessId",
        "Get-TicketboxServiceStartPolicy",
        "Get-TicketboxServiceState",
        "Invoke-TicketboxC07Sql",
        "Resolve-TicketboxC07DatabaseHostAuthority",
        "Disable-TicketboxOwnedServiceIfExists",
    ):
        assert f"function {forbidden_definition}" not in heartbeat_helper
    assert "Write-TicketboxC07DurableHeartbeat" in heartbeat_helper
    assert "function Write-TicketboxC07DurableHeartbeat" not in heartbeat_helper
    assert "TicketboxC07HeartbeatHelper" not in recovery_generation
    assert "Process.Start()" not in database_safety
    assert ".Kill()" not in database_safety
    assert "$process.WaitForExit()" not in database_safety


def test_c07_lifecycle_rejects_reparse_shared_authority_bootstrap(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows C07 shared authority bootstrap contract")

    real_root = tmp_path / "real-bootstrap"
    junction_root = tmp_path / "reparse-bootstrap"
    real_root.mkdir()
    for name in (
        "windows_c07_heartbeat_authority.ps1",
        "windows_c07_lifecycle.ps1",
    ):
        (real_root / name).write_bytes((PACKAGING / name).read_bytes())
    created = subprocess.run(  # noqa: S603
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction_root),
            str(real_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    try:
        for engine in powershell_contract_engines():
            completed = subprocess.run(  # noqa: S603
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    (
                        f". '{_ps_literal(PACKAGING / 'windows_installation_safety.ps1')}'; "
                        "try { "
                        f". '{_ps_literal(junction_root / 'windows_c07_lifecycle.ps1')}'; "
                        "throw 'reparse shared authority bootstrap was accepted' "
                        "} catch { "
                        "if ($_.Exception.Message -cnotmatch 'reparse') { throw }; "
                        "'reparse-rejected' "
                        "}"
                    ),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            assert "reparse-rejected" in completed.stdout
    finally:
        junction_root.rmdir()


def test_service_lifecycle_requires_exact_image_path_and_terminal_states() -> None:
    lifecycle = _read("windows_service_contract.ps1") + "\n" + _read(
        "windows_service_lifecycle.ps1"
    )

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
    assert "Assert-TicketboxServiceAccount" in lifecycle
    assert "Wait-TicketboxServiceSettledState" in lifecycle
    assert "New-TicketboxWaitDeadline" in lifecycle
    assert "Get-TicketboxWaitAttempts" not in lifecycle
    assert "New-TicketboxPgServiceImagePath" in lifecycle
    assert "New-TicketboxShawlServiceImagePath" in lifecycle
    assert "Get-TicketboxServiceDependencies" in lifecycle
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
    assert "& $scExecutable @ScArgs" in lifecycle
    assert "& sc.exe @ScArgs" not in lifecycle
    assert "Set-TicketboxOwnedServiceDemandStartIfExists" in lifecycle
    assert "Set-TicketboxOwnedServiceDelayedAutoStartIfExists" in lifecycle
    install = _read("install_bundled_services.ps1")
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
    validation = install[
        install.index("if ($ValidateInstalledServicesOnly)") : install.index("$operationLock =")
    ]
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
    stop_backend = install.index("Stop-ServiceIfExists", install.index("$hadExistingPgService"))
    isolate_acl = install.index("Set-TicketboxAcl", stop_backend)
    backup = install.index("Invoke-PreUpgradeBackupIfNeeded", isolate_acl)
    assert stop_backend < isolate_acl < backup
    assert "-IncludeBackendService $hadExistingBackendService" in install
    for runtime_contract in (install, prepare):
        assert "$ServiceBootstrapExposureRecoveryGuardPath" in runtime_contract
        assert (
            "Get-TicketboxRuntimeBootstrapRecoveryGuardPath $binding.RuntimeDataRoot"
            in runtime_contract
        )
    assert (
        "-BootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath"
        in install
    )
    assert (
        "-ExpectedBootstrapRecoveryGuardPath $ServiceBootstrapExposureRecoveryGuardPath"
        in prepare
    )
    acl_function = install[install.index("function Set-TicketboxAcl") : install.index("function Assert-PortAvailable")]
    assert acl_function.index("-Path $AppData") < acl_function.index(
        "Initialize-TicketboxInstallerStateDirectory $InstallerState"
    )
    assert '$markerReadAccounts += "NT SERVICE\\$BackendServiceName"' in acl_function
    marker_acl = acl_function.index("-Path (Get-TicketboxDataRootMarkerPath $DataRoot)")
    assert acl_function.index("-ReadExecuteAccounts $markerReadAccounts", marker_acl) > marker_acl
    operation = install[install.index("$operationLock =") :]
    assert operation.index("Initialize-TicketboxInstallerStateArtifacts") < operation.index(
        "Adopt-TicketboxOwnerBootstrapHandoff"
    )
    pg_registration = install[install.index("function Register-PgService") : install.index("function Register-BackendService")]
    backend_registration = install[
        install.index("function Register-BackendService") : install.index("function Invoke-IcaclsChecked")
    ]
    assert "Remove-ServiceIfExists" not in pg_registration
    assert "Remove-ServiceIfExists" not in backend_registration
    assert '"create", $PgServiceName' in pg_registration
    assert '"binPath=", $pgImagePath' in pg_registration
    assert '"obj=", "NT SERVICE\\$PgServiceName"' in pg_registration
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
    restart = backend_bootstrap[
        backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists") :
        backend_bootstrap.index("Wait-BackendHealth", backend_bootstrap.index("Restart-TicketboxOwnedServiceIfExists"))
    ]
    assert "-BackendPort $BackendPort" in restart
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in restart

    database = _read("windows_bundled_database.ps1")
    assert '"-tAc", $Sql' not in database
    assert '"--dbname", $ProtectedDatabaseUrl, "-tA"' in database
    assert "Invoke-TicketboxWithPgPassFile" in database
    assert "require_auth=scram-sha-256" in database
    assert "Invoke-TicketboxBoundedNativeProcess" in database
    assert '-StandardInputText ($Sql + "`n")' in database
    assert "$out = $Sql | & $psql @args 2>&1" not in database
    assert '：$Sql`n$out' not in database
    assert 'throw "psql 执行失败（db=$Database, exit=$($result.ExitCode)）。"' in database

    legacy_installer = _read("install_ticketbox.ps1")
    assert '"-tAc", $Sql' not in legacy_installer
    assert '"--dbname", $ProtectedDatabaseUrl, "-tA"' in legacy_installer
    assert "Invoke-TicketboxWithPgPassFile" in legacy_installer
    assert "require_auth=scram-sha-256" in legacy_installer
    assert "Invoke-TicketboxBoundedNativeProcess" in legacy_installer
    assert '-StandardInputText ($Sql + "`n")' in legacy_installer
    assert "$out = $Sql | & $Psql @psqlArgs 2>&1" not in legacy_installer
    assert '：$Sql"' not in legacy_installer


def test_pre_upgrade_backup_uses_old_tools_before_stopping_postgres() -> None:
    prepare = _read("prepare_bundled_upgrade.ps1")

    upgrade_try = prepare.index("try {", prepare.index("$backupRequired"))
    stop_backend = prepare.index("Disable-TicketboxOwnedServiceIfExists", upgrade_try)
    dump_database = prepare.index("Invoke-TicketboxPgDumpCustom")
    verify_dump = prepare.index("Invoke-TicketboxPgRestoreList")
    stop_postgres = prepare.index("Disable-TicketboxOwnedServiceIfExists", dump_database)
    assert stop_backend < dump_database < verify_dump < stop_postgres
    backend_prepare = prepare[
        prepare.index("if ($hasBackendService) {", upgrade_try) : prepare.index(
            "if ($usingRecoveryPgService)", upgrade_try
        )
    ]
    assert "Disable-TicketboxOwnedServiceIfExists" in backend_prepare
    assert "Set-TicketboxPreparedServiceDemandStart" not in backend_prepare
    assert '$PgBin = Join-Path $InstallDir "pg\\bin"' in prepare
    assert "Restore-PreviousServiceState" in prepare
    assert "旧程序保持不变" in prepare
    assert "Assert-TicketboxConnectedPostgresDataRoot" in prepare
    assert "Get-TicketboxLocalDatabaseConnection" in prepare
    assert "Assert-ExpectedServiceConfiguration" in prepare
    assert "Invoke-TicketboxBoundedNativeProcess" in prepare
    assert "& $PgCtl status -D $PgData" not in prepare
    assert 'Wait-TicketboxServiceSettledState -Name $PgServiceName' in prepare
    assert "InstalledReleaseConfigPath" in prepare
    assert "LifecycleReceiptPath" in prepare
    assert "Write-TicketboxLifecycleReceipt" in prepare
    assert "BackupCompleted $backupCompleted" in prepare
    assert "Assert-TicketboxReleaseIdentityCompatible" in prepare
    assert "ExpectedStopTimeoutMs = $InstalledStopTimeoutMs" in prepare
    assert "ExpectedRestartDelayMs = $InstalledRestartDelayMs" in prepare
    assert "Assert-TicketboxPgClusterStopped" in prepare
    assert "Repair-TicketboxPreflightInstallAcl" in prepare
    assert "Assert-TicketboxPortAvailableForMissingService" in prepare
    assert "-BackendPort $BackendPort" in prepare
    assert "Set-TicketboxPreparedServiceDemandStart" in prepare
    assert "files-may-have-been-replaced" in prepare
    disabled_pg = prepare.index('if ($hasPgService -and $pgStartPolicy -eq "disabled")')
    demand_start = prepare.index("Set-TicketboxPreparedServiceDemandStart", disabled_pg)
    start_pg = prepare.index("Start-TicketboxOwnedServiceIfExists", demand_start)
    assert disabled_pg < demand_start < start_pg
    assert "-ExpectedRuntimeExecutables @($BackendExe, $ShawlExe)" in prepare

    install = _read("install_bundled_services.ps1")
    installer = _read("ticketbox-installer-flow.isph")
    assert "PreviousReleaseConfigPath" not in install
    assert "SkipPreUpgradeBackup" not in installer
    assert "Read-TicketboxLifecycleReceipt" in install
    assert "-ExpectedStopTimeoutMs $PreviousStopTimeoutMs" in install
    assert "InstalledReleaseConfigSnapshotPath" not in installer
    assert "PreviousReleaseConfigPath" not in installer
    assert "LifecycleReceiptPath" in installer


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
    assert '@{ Name = $PgServiceName; Executable = $PgCtl; Value = $PgStartPolicy }' in restore
    assert (
        '@{ Name = $BackendServiceName; Executable = $ShawlExe; Value = $BackendStartPolicy }'
        in restore
    )
    assert '$PgStartPolicy -eq "disabled"' in restore
    assert '$BackendStartPolicy -eq "disabled"' in restore
    assert '"manual"' in restore
    assert "Get-TicketboxServiceStartPolicy" in lifecycle
    assert "Set-TicketboxOwnedServiceStartPolicyIfExists" in lifecycle


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell service contract")
def test_service_policy_and_sid_contract_in_powershell_5_and_7(tmp_path: Path) -> None:
    harness = tmp_path / "service-start-policy.ps1"
    lifecycle = str(PACKAGING / "windows_service_lifecycle.ps1").replace("'", "''")
    harness.write_text(
        f"""
$ErrorActionPreference = 'Stop'
. '{lifecycle}'
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
        fr"""
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
