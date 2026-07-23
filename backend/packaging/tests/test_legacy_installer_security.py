from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]
INSTALLER = PACKAGING / "install_ticketbox.ps1"
VECTOR_SECRET = "ticketbox-bootstrap-vector-2026-07-10"
VECTOR_ADMIN_TOKEN = "tbx_f1cz5I0IKi0r6iUzmoexescoDH0xYOF7_-R39LpN7lY"
VECTOR_UPLOAD_KEY = "upl_I8Q7_d0BrxgzKxMlkZFUtd9eFF1xe40zM8dt2h1cyeU"
VECTOR_PAIRING_CODE = "05747978"


def _derive_bootstrap_credentials(secret: str) -> tuple[str, str, str]:
    def digest(context: str) -> bytes:
        return hmac.new(secret.encode(), context.encode("ascii"), hashlib.sha256).digest()

    admin = base64.urlsafe_b64encode(digest("ticketbox/bootstrap-owner/v1/admin-token")).decode().rstrip("=")
    upload = base64.urlsafe_b64encode(digest("ticketbox/bootstrap-owner/v1/upload-key")).decode().rstrip("=")
    pairing = int.from_bytes(digest("ticketbox/bootstrap-owner/v1/pairing-code"), "big") % 100_000_000
    return f"tbx_{admin}", f"upl_{upload}", f"{pairing:08d}"


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8-sig")


def _powershell_engines() -> list[str]:
    engines = [path for name in ("powershell.exe", "pwsh.exe") if (path := shutil.which(name))]
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    return engines


def _ps_literal(value: Path | str) -> str:
    return str(value).replace("'", "''")


def _function_loader(names: tuple[str, ...]) -> str:
    quoted_names = ", ".join(f"'{name}'" for name in names)
    return f"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{_ps_literal(INSTALLER)}',
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {{ throw 'installer parse failed' }}
$functionNames = @({quoted_names})
$definitions = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $functionNames -contains $node.Name
}}, $true))
foreach ($functionName in $functionNames) {{
    $matches = @($definitions | Where-Object {{ $_.Name -ceq $functionName }})
    if ($matches.Count -ne 1) {{ throw "missing function: $functionName" }}
    Invoke-Expression $matches[0].Extent.Text
}}
"""


def _run_harness(
    tmp_path: Path,
    name: str,
    body: str,
    *,
    arguments: tuple[str, ...] = (),
    extra_env: dict[str, str] | None = None,
    forbidden_output: tuple[str, ...] = (),
    timeout: int = 30,
) -> None:
    engines = _powershell_engines()
    assert len(engines) == 2, "Windows PowerShell 5.1 and PowerShell 7 are required"
    harness = tmp_path / f"{name}.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        + body,
        encoding="utf-8-sig",
    )
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    for engine in engines:
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                harness,
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        assert result.returncode == 0, f"{engine}:\n{result.stdout}\n{result.stderr}"
        combined_output = result.stdout + result.stderr
        for marker in forbidden_output:
            assert marker not in combined_output, f"{engine} leaked {marker!r}"


def test_plaintext_password_cli_is_removed_without_compatibility_aliases() -> None:
    script = _installer_text()

    assert re.search(r"\[string\]\$PostgresSuperPasswordFile\b", script)
    assert re.search(r"\[string\]\$PostgresRolePasswordFile\b", script)
    assert re.search(r"\[switch\]\$NonInteractive\b", script)
    assert not re.search(r"\[string\]\$SuperPassword\b", script)
    assert not re.search(r"\[string\]\$DbPassword\b", script)
    assert "Alias('SuperPassword')" not in script
    assert 'Alias("SuperPassword")' not in script
    assert "Alias('DbPassword')" not in script
    assert 'Alias("DbPassword")' not in script
    assert "Read-Host $Prompt -AsSecureString" in script
    assert "非交互模式必须通过 -PostgresSuperPasswordFile" in script

    param_block = script[script.index("param(") : script.index("\n)", script.index("param("))]
    parameter_names = re.findall(r"\$([A-Za-z][A-Za-z0-9]*)", param_block)
    for removed_name in ("SuperPassword", "DbPassword"):
        assert not any(name.casefold().startswith(removed_name.casefold()) for name in parameter_names)


def test_legacy_installer_reads_mutable_defaults_from_release_config() -> None:
    script = _installer_text()
    readme = (PACKAGING / "README.md").read_text(encoding="utf-8-sig")

    assert "$ReleaseConfig = Read-TicketboxWindowsReleaseConfig $ReleaseConfigPath" in script
    assert "$DbPort = [int]$ReleaseConfig.default_pg_port" in script
    assert "$Port = [int]$ReleaseConfig.default_backend_port" in script
    assert "$SecretByteCount = [int]$ReleaseConfig.secret_byte_count" in script
    assert "[ValidateRange(32, 1024)][int]$Length" in script
    assert "[ValidateRange(32, 1024)][int]$SecretLength" in script
    assert "New-StrongPassword -Length $SecretByteCount" in script
    assert "-SecretLength $SecretByteCount" in script
    assert '[string]$DbHost = "127.0.0.1"' in script
    assert "Enter-TicketboxLifecycleLock" in script
    assert "Exit-TicketboxLifecycleLock" in script
    assert script.index("Enter-TicketboxLifecycleLock") < script.index("$Psql = Find-Psql")
    assert "`windows_installation_safety.ps1`" in readme
    assert "`windows_lifecycle_lock.ps1`" in readme
    for duplicated_default in (
        '"MAX_UPLOAD_SIZE_MB=10"',
        '"GENERATE_THUMBNAIL=true"',
        '"OCR_PROVIDER=empty"',
        '"OCR_AUTO_RUN=false"',
        '"ENABLE_API_DOCS=false"',
        '"ALLOW_PUBLIC_ADMIN_API=false"',
        '"CLOUDFLARE_ACCESS_REQUIRED=false"',
    ):
        assert duplicated_default not in script


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parameter binding contract")
def test_removed_plaintext_switches_are_rejected_before_execution() -> None:
    for removed_switch in ("-SuperPassword", "-DbPassword"):
        for engine in _powershell_engines():
            result = subprocess.run(
                [engine, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", INSTALLER,
                 removed_switch, "test-only-not-a-secret"],
                check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            assert result.returncode != 0
            assert removed_switch.removeprefix("-") in result.stdout + result.stderr
    for engine in _powershell_engines():
        remote = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                INSTALLER,
                "-DbHost",
                "db.example.invalid",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert remote.returncode != 0
        assert "127.0.0.1" in remote.stdout + remote.stderr


def test_password_file_native_psql_and_bootstrap_contracts_are_fail_closed() -> None:
    script = _installer_text()

    assert "Assert-NoReparsePointInPath" in script
    assert "AreAccessRulesProtected" in script
    assert "S-1-5-18" in script
    assert "S-1-5-32-544" in script
    assert "FileShare]::None" in script
    assert "Remove-ProtectedPasswordFile $canonicalPath" in script
    assert "密码文件清理失败，拒绝继续" in script
    assert "Set-ProtectedOutputFileAcl $canonicalPath" in script
    assert '$canonicalPath.StartsWith("\\\\", [System.StringComparison]::Ordinal)' in script
    assert "Get-TicketboxFileSystemDriveType" in script
    assert "[System.IO.DriveType]::Network" in script
    assert "[System.IO.DriveType]::Unknown" in script
    assert "[System.IO.DriveType]::NoRootDirectory" in script
    assert "FileOptions]::WriteThrough" in script
    assert "$stream.Flush($true)" in script
    assert "TicketboxLegacyInstallerFileNativeMethods" in script
    assert "$replaceExistingAndWriteThrough = 0x1 -bor 0x8" in script
    assert "Move-SensitiveFileAtomically -Source $temporaryPath -Destination $canonicalPath" in script
    assert "Assert-SimpleSqlIdentifier $DbName" in script
    assert '@{ Value = $PublicBaseUrl; Name = "PublicBaseUrl" }' in script

    assert script.count("Invoke-TicketboxBoundedNativeProcess") >= 2
    assert "& $Psql @psqlArgs 2>&1" not in script
    assert '-StandardInputText ($Sql + "`n")' in script
    assert "$DatabaseToolTimeoutMs = [int]$ReleaseConfig.database_tool_timeout_ms" in script
    assert '"-X", "-w"' in script
    assert "exit=$($result.ExitCode)" in script
    assert "：$Sql" not in script

    assert "Get-NetTCPConnection -State Listen" in script
    assert ".OwningProcess" in script
    assert "Win32_Process" in script
    assert ".ExecutablePath" in script
    assert '"status"\\s*:\\s*"ok"' in script
    assert "[System.Text.Encoding]::UTF8.GetBytes($bodyJson)" in script
    assert '$request.ContentType = "application/json; charset=utf-8"' in script
    assert "$request.Proxy = $null" in script
    assert "$request.AllowAutoRedirect = $false" in script
    assert "Invoke-RestMethod" not in script
    assert "taskkill /IM ticketbox-backend.exe" not in script
    assert "Test-BootstrapAlreadyInitializedError" not in script
    assert "bootstrap_already_initialized" not in script
    assert "Get-LegacyRetainedBootstrapSecret" in script
    assert "Test-PersistentOwnerIdentity" in script
    assert "Resolve-LegacyBootstrapPlan" in script
    assert "持久 owner 身份保持不变，未调用 HTTP bootstrap" in script
    assert "bootstrap secret 可能已暴露" in script
    assert "catch [System.Security.SecurityException]" in script
    assert "Write-LegacyBootstrapExposureRecoveryIntent" in script
    assert "Resolve-LegacyBootstrapExposureRecovery" in script
    assert "TICKETBOX_MAINTENANCE_ACTION" in script
    security_catch = script[script.index("catch [System.Security.SecurityException]", script.index("$bootstrapExposureQuarantined")) :]
    assert security_catch.index("Write-LegacyBootstrapExposureRecoveryIntent") < security_catch.index(
        "Write-EnvNoBom -Path $EnvPath -Lines $baseEnv"
    )
    assert script.index("Resolve-LegacyBootstrapExposureRecovery `") < script.index(
        "$retainedBootstrapSecret = if"
    )
    assert "Set-TicketboxExactFileAcl `" in script[
        script.index("function Write-LegacyBootstrapExposureRecoveryIntent") :
        script.index("function Invoke-LegacyBootstrapExposureMaintenance")
    ]
    assert re.search(
        r"if \(\$bootstrapVerifiedAndPersisted\) \{\s*try \{\s*Write-EnvNoBom -Path \$EnvPath -Lines \$baseEnv",
        script,
    )
    assert "$bootstrapVerifiedAndPersisted = $true" in script
    assert "Assert-BootstrapResponse -Response $resp -Secret $bootstrapSecret" in script
    assert VECTOR_ADMIN_TOKEN in script
    assert VECTOR_UPLOAD_KEY in script
    assert VECTOR_PAIRING_CODE in script
    for parameter in (
        "BackendReadyTimeoutMs",
        "BackendHealthRequestTimeoutMs",
        "BackendReadyPollIntervalMs",
        "BootstrapRequestTimeoutMs",
    ):
        assert re.search(rf"\[ValidateRange\([^\]]+\)\]\s*\[int\]\${parameter}\b", script)
    assert "$request.Timeout = 15000" not in script
    assert "$request.ReadWriteTimeout = 15000" not in script
    request_function = script[
        script.index("function Invoke-OwnerBootstrapRequest") :
        script.index("function Get-BootstrapHmacDigest")
    ]
    assert request_function.count("Assert-BackendListenerOwnedByProcess") == 4
    atomic_writer = script[
        script.index("function Write-EnvNoBom") :
        script.index("function Get-BackendPortListeners")
    ]
    assert atomic_writer.index("Set-ProtectedOutputFileAcl $temporaryPath") < atomic_writer.index(
        "$stream.Write($bytes, 0, $bytes.Length)"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL behavior contract")
def test_protected_password_file_is_consumed_and_inherited_acl_is_rejected(tmp_path: Path) -> None:
    secret = "test-only-password-value"
    expected_hash = hashlib.sha256(secret.encode()).hexdigest().upper()
    body = _function_loader(
        (
            "Get-TicketboxFileSystemDriveType",
            "Get-CanonicalFileSystemPath",
            "Get-PathAclRecord",
            "Assert-NoReparsePointInPath",
            "Assert-ProtectedPasswordFile",
            "Test-ProtectedPasswordFile",
            "Set-ProtectedOutputFileAcl",
            "Remove-ProtectedPasswordFile",
            "Read-ProtectedPasswordFile",
            "Read-RetainedBootstrapSecret",
            "Initialize-LegacyInstallerFileNativeMethods",
            "Move-SensitiveFileAtomically",
            "Write-EnvNoBom",
        )
    )
    body += r"""
function Set-TestProtectedAcl([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($PSVersionTable.PSEdition -eq 'Core') {
        $acl = [System.IO.FileSystemAclExtensions]::GetAccessControl($item)
    }
    else {
        $acl = $item.GetAccessControl()
    }
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    ))) {
        $acl.RemoveAccessRuleSpecific($rule)
    }
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl.SetOwner($sid)
    $allow = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($allow)
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [System.IO.FileSystemAclExtensions]::SetAccessControl($item, $acl)
    }
    else {
        $item.SetAccessControl($acl)
    }
}
$securePath = Join-Path $args[0] ("secure-$PID.txt")
$emptyPath = Join-Path $args[0] ("empty-$PID.txt")
$insecurePath = Join-Path $args[0] ("insecure-$PID.txt")
[System.IO.File]::WriteAllText($securePath, $env:TEST_PASSWORD, [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($emptyPath, '', [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($insecurePath, 'not-consumed', [System.Text.Encoding]::UTF8)
Set-TestProtectedAcl $securePath
Set-TestProtectedAcl $emptyPath
$retryEnv = Join-Path $args[0] ("retry-$PID.env")
[System.IO.File]::WriteAllLines(
    $retryEnv,
    @('DATABASE_URL=test-only', 'ENABLE_HTTP_BOOTSTRAP=true', "HTTP_BOOTSTRAP_SECRET=$env:TEST_BOOTSTRAP_SECRET"),
    (New-Object System.Text.UTF8Encoding($false))
)
Set-TestProtectedAcl $retryEnv
$retainedSecret = Read-RetainedBootstrapSecret $retryEnv
if ($retainedSecret -cne $env:TEST_BOOTSTRAP_SECRET -or -not (Test-Path -LiteralPath $retryEnv)) {
    throw 'retained bootstrap secret was changed or consumed'
}
Remove-Item -LiteralPath $retryEnv -Force
$value = Read-ProtectedPasswordFile -Path $securePath -Purpose 'test'
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $hash = [System.BitConverter]::ToString(
        $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($value))
    ).Replace('-', '')
}
finally {
    $sha.Dispose()
}
if ($hash -cne $args[1]) { throw 'password content changed' }
if (Test-Path -LiteralPath $securePath) { throw 'protected password file survived consumption' }
$emptyValue = Read-ProtectedPasswordFile -Path $emptyPath -Purpose 'trust-test' -AllowEmpty
if ($emptyValue.Length -ne 0 -or (Test-Path -LiteralPath $emptyPath)) {
    throw 'empty trust password file was not consumed'
}
$rejected = $false
try {
    Read-ProtectedPasswordFile -Path $insecurePath -Purpose 'test' | Out-Null
}
catch {
    $rejected = $true
}
if (-not $rejected) { throw 'inherited ACL was accepted' }
if (-not (Test-Path -LiteralPath $insecurePath -PathType Leaf)) {
    throw 'untrusted file was deleted before validation'
}
Remove-Item -LiteralPath $insecurePath -Force
$junctionTarget = Join-Path $args[0] ("junction-target-$PID")
$junctionPath = Join-Path $args[0] ("junction-path-$PID")
New-Item -ItemType Directory -Path $junctionTarget | Out-Null
$junctionSecret = Join-Path $junctionTarget 'secret.txt'
[System.IO.File]::WriteAllText($junctionSecret, $env:TEST_PASSWORD, [System.Text.Encoding]::UTF8)
Set-TestProtectedAcl $junctionSecret
$junctionCreated = $false
try {
    New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget -ErrorAction Stop | Out-Null
    $junctionCreated = $true
}
catch {}
if ($junctionCreated) {
    $reparseRejected = $false
    try {
        Read-ProtectedPasswordFile -Path (Join-Path $junctionPath 'secret.txt') -Purpose 'junction-test' | Out-Null
    }
    catch {
        $reparseRejected = $true
    }
    if (-not $reparseRejected) { throw 'junction password path was accepted' }
    if (-not (Test-Path -LiteralPath $junctionSecret -PathType Leaf)) {
        throw 'junction target was consumed before reparse rejection'
    }
    [System.IO.Directory]::Delete($junctionPath)
}
Remove-Item -LiteralPath $junctionSecret -Force
Remove-Item -LiteralPath $junctionTarget -Force
$sensitiveOutput = Join-Path $args[0] ("sensitive-output-$PID.env")
Write-EnvNoBom -Path $sensitiveOutput -Lines @('DATABASE_URL=test-only')
Assert-ProtectedPasswordFile $sensitiveOutput
Write-EnvNoBom -Path $sensitiveOutput -Lines @('DATABASE_URL=replaced-atomically')
Assert-ProtectedPasswordFile $sensitiveOutput
$persistedText = [System.IO.File]::ReadAllText($sensitiveOutput, [System.Text.Encoding]::UTF8)
if ($persistedText -cne "DATABASE_URL=replaced-atomically$([Environment]::NewLine)") {
    throw 'sensitive output replacement did not persist exactly'
}
$orphanTemps = @(Get-ChildItem -LiteralPath $args[0] -Filter '.sensitive-output-*.tmp')
if ($orphanTemps.Count -ne 0) { throw 'atomic sensitive output left a temp file' }
$outputBytes = [System.IO.File]::ReadAllBytes($sensitiveOutput)
if (
    $outputBytes.Length -ge 3 -and
    $outputBytes[0] -eq 0xEF -and
    $outputBytes[1] -eq 0xBB -and
    $outputBytes[2] -eq 0xBF
) {
    throw 'sensitive output unexpectedly contains a BOM'
}
Remove-Item -LiteralPath $sensitiveOutput -Force
function Get-TicketboxFileSystemDriveType([string]$CanonicalPath) {
    return [System.IO.DriveType]::Network
}
$mappedDriveRejected = $false
try {
    Get-CanonicalFileSystemPath (Join-Path $args[0] 'mapped-drive-secret.txt') | Out-Null
}
catch {
    $mappedDriveRejected = $true
}
if (-not $mappedDriveRejected) { throw 'mapped network drive was accepted' }
"""
    _run_harness(
        tmp_path,
        "password-file-behavior",
        body,
        arguments=(str(tmp_path), expected_hash),
        extra_env={"TEST_PASSWORD": secret, "TEST_BOOTSTRAP_SECRET": VECTOR_SECRET},
        forbidden_output=(secret, VECTOR_SECRET),
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native-command behavior contract")
def test_native_psql_stderr_and_exit_code_are_sanitized_under_stop(tmp_path: Path) -> None:
    body = _function_loader(("Invoke-Sql", "Invoke-SqlFile"))
    body += f"""
. '{_ps_literal(PACKAGING / "windows_installation_safety.ps1")}'
. '{_ps_literal(PACKAGING / "windows_database_safety.ps1")}'
"""
    body += r"""
    $Psql = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $DbHost = '127.0.0.1'
    $DbPort = 5432
    $DatabaseToolTimeoutMs = 10000
    function Invoke-TicketboxBoundedNativeProcess {
        param(
            [string]$FilePath,
            [string[]]$Arguments,
            [int]$TimeoutMilliseconds,
            [string]$Label,
            [AllowEmptyString()][string]$StandardInputText
        )
        if (($Arguments -join ' ') -match 'password-secret-marker|sql-secret-marker|sql-file-secret-marker') {
            throw 'database secret reached native argv'
        }
        return [pscustomobject]@{
            ExitCode = 23
            StandardOutput = ''
            StandardError = 'native-secret-marker'
        }
    }
$env:PGPASSWORD = 'original-environment-value'
$env:PGPASSFILE = 'original-passfile-value'
$PSNativeCommandUseErrorActionPreference = $true
$caught = $false
try {
    Invoke-Sql -User 'postgres' -Password 'password-secret-marker' -Database 'postgres' -Sql 'sql-secret-marker' | Out-Null
}
catch {
    $caught = $true
    $message = $_.Exception.Message
    if ($message -notmatch 'exit=23') { throw 'native exit code was lost' }
    if ($message -match 'native-secret-marker|password-secret-marker|sql-secret-marker') {
        throw 'native or input secret leaked into the sanitized exception'
    }
}
if (-not $caught) { throw 'native psql failure was not raised' }
$sqlFile = Join-Path $args[0] ("input-$PID.sql")
[System.IO.File]::WriteAllText($sqlFile, 'sql-file-secret-marker', [System.Text.Encoding]::UTF8)
$fileCaught = $false
try {
    Invoke-SqlFile -User 'postgres' -Password 'password-secret-marker' -Database 'postgres' -Path $sqlFile
}
catch {
    $fileCaught = $true
    $message = $_.Exception.Message
    if ($message -notmatch 'exit=23') { throw 'native file exit code was lost' }
    if ($message -match 'native-secret-marker|password-secret-marker|sql-file-secret-marker') {
        throw 'native or file secret leaked into the sanitized exception'
    }
}
if (-not $fileCaught) { throw 'native psql file failure was not raised' }
if ($env:PGPASSWORD -cne 'original-environment-value') { throw 'PGPASSWORD was not restored' }
if ($env:PGPASSFILE -cne 'original-passfile-value') { throw 'PGPASSFILE was not restored' }
if (-not $PSNativeCommandUseErrorActionPreference) { throw 'native preference was not restored' }
    Remove-Item -LiteralPath $sqlFile -Force
"""
    _run_harness(
        tmp_path,
        "native-psql-behavior",
        body,
        arguments=(str(tmp_path),),
        forbidden_output=(
            "native-secret-marker",
            "password-secret-marker",
            "sql-secret-marker",
            "sql-file-secret-marker",
        ),
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap recovery behavior contract")
def test_successful_rerun_skips_bootstrap_from_persistent_identity(tmp_path: Path) -> None:
    body = _function_loader(
        (
            "Get-TicketboxFileSystemDriveType",
            "Get-CanonicalFileSystemPath",
            "Get-PathAclRecord",
            "Assert-NoReparsePointInPath",
            "Assert-ProtectedPasswordFile",
            "Test-ProtectedPasswordFile",
            "Set-ProtectedOutputFileAcl",
            "Read-RetainedBootstrapSecret",
            "Get-LegacyRetainedBootstrapSecret",
            "Protect-LegacyOwnerBootstrapFileIfPresent",
            "Initialize-LegacyInstallerFileNativeMethods",
            "Move-SensitiveFileAtomically",
            "Write-EnvNoBom",
            "Test-PersistentOwnerIdentity",
            "Resolve-LegacyBootstrapPlan",
        )
    )
    body += r"""
$script:generatedSecrets = 0
function Invoke-Sql {
    param($User, $Password, $Database, $Sql)
    if ($Sql -match 'revoked_at') { throw 'persistent identity query depends on active tokens' }
    if ($Sql -match 'pg_catalog.pg_class') { return '4' }
    if ($Sql -match 'FROM auth_tokens') { return '1' }
    throw 'unexpected identity query'
}
function New-StrongPassword {
    param([int]$Length)
    $script:generatedSecrets += 1
    return 'new-secret-that-must-not-be-used-for-rerun'
}
$identityExists = Test-PersistentOwnerIdentity `
    -User 'ticketbox' `
    -Password 'test-only-role-password' `
    -Database 'ticketbox'
if (-not $identityExists) { throw 'revoked historical tokens did not prove persistent identity' }
$legacyEnv = Join-Path $args[0] ("legacy-inherited-$PID.env")
[System.IO.File]::WriteAllLines(
    $legacyEnv,
    @(
        'DATABASE_URL=legacy',
        'ENABLE_HTTP_BOOTSTRAP=true',
        'HTTP_BOOTSTRAP_SECRET=untrusted-inherited-secret-must-not-be-read'
    ),
    (New-Object System.Text.UTF8Encoding($false))
)
$retained = Get-LegacyRetainedBootstrapSecret `
    -Path $legacyEnv `
    -PersistentOwnerIdentity $identityExists
if ($null -ne $retained) { throw 'inherited legacy env was trusted as a retained secret' }
$legacyCredentials = Join-Path $args[0] ("legacy-owner-$PID.txt")
[System.IO.File]::WriteAllText(
    $legacyCredentials,
    'historical-owner-credential-content',
    [System.Text.Encoding]::UTF8
)
Protect-LegacyOwnerBootstrapFileIfPresent $legacyCredentials
Assert-ProtectedPasswordFile $legacyCredentials
if ([System.IO.File]::ReadAllText($legacyCredentials, [System.Text.Encoding]::UTF8) -cne
    'historical-owner-credential-content') {
    throw 'legacy owner credential file content changed during ACL migration'
}
$rerun = Resolve-LegacyBootstrapPlan `
    -RetainedSecret $retained `
    -PersistentOwnerIdentity $identityExists `
    -SecretLength 32
if ($rerun.Required -or $null -ne $rerun.Secret -or $script:generatedSecrets -ne 0) {
    throw 'successful rerun generated a new secret or requested a second bootstrap'
}
Write-EnvNoBom -Path $legacyEnv -Lines @('DATABASE_URL=hardened-base-config')
Assert-ProtectedPasswordFile $legacyEnv
$rewritten = [System.IO.File]::ReadAllText($legacyEnv, [System.Text.Encoding]::UTF8)
if ($rewritten -match 'HTTP_BOOTSTRAP_SECRET|untrusted-inherited-secret') {
    throw 'legacy env was not replaced with hardened base config'
}
$recovery = Resolve-LegacyBootstrapPlan `
    -RetainedSecret 'retained-recovery-secret' `
    -PersistentOwnerIdentity $true `
    -SecretLength 32
if (-not $recovery.Required -or -not $recovery.IsRecovery -or
    $recovery.Secret -cne 'retained-recovery-secret' -or $script:generatedSecrets -ne 0) {
    throw 'retained failed-install secret did not take recovery priority'
}
$fresh = Resolve-LegacyBootstrapPlan `
    -RetainedSecret $null `
    -PersistentOwnerIdentity $false `
    -SecretLength 32
if (-not $fresh.Required -or $fresh.IsRecovery -or $script:generatedSecrets -ne 1) {
    throw 'fresh install did not generate exactly one bootstrap secret'
}
"""
    _run_harness(
        tmp_path,
        "persistent-identity-rerun",
        body,
        arguments=(str(tmp_path),),
        forbidden_output=(
            "test-only-role-password",
            "retained-recovery-secret",
            "new-secret-that-must-not-be-used-for-rerun",
            "untrusted-inherited-secret-must-not-be-read",
            "historical-owner-credential-content",
        ),
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows listener revalidation contract")
def test_bootstrap_http_exception_revalidates_listener_and_fails_closed(tmp_path: Path) -> None:
    body = _function_loader(("Invoke-OwnerBootstrapRequest",))
    body += r"""
$script:listenerChecks = 0
$script:listenerFailsAfterRequest = $false
function Assert-BackendListenerOwnedByProcess {
    param($ExpectedProcessId, $ExpectedExecutablePath, $ListenPort)
    $script:listenerChecks += 1
    if ($script:listenerFailsAfterRequest -and $script:listenerChecks -eq 3) {
        throw 'simulated listener replacement'
    }
}
function Invoke-DirectLoopbackHealthRequest {
    param($Url, $RequestTimeoutMs)
    return [pscustomobject]@{
        StatusCode = 200
        Headers = @{ 'Content-Type' = 'application/json' }
        Content = '{"status":"ok"}'
    }
}
function Assert-StrictBackendHealthResponse { param($Response) }
$payload = @{ account_name = 'test' }
$retryable = $false
try {
    Invoke-OwnerBootstrapRequest `
        -BaseUrl 'http://127.0.0.1:1' `
        -Secret 'listener-failure-secret-that-must-not-be-printed' `
        -Payload $payload `
        -ExpectedProcessId 123 `
        -ExpectedExecutablePath 'C:\Ticketbox\backend.exe' `
        -ListenPort 1 `
        -HealthRequestTimeoutMs 100 `
        -RequestTimeoutMs 1000 | Out-Null
}
catch {
    $retryable = $_.Exception -isnot [System.Security.SecurityException]
}
if (-not $retryable -or $script:listenerChecks -ne 3) {
    throw 'HTTP exception did not perform a retryable listener post-check'
}
$script:listenerChecks = 0
$script:listenerFailsAfterRequest = $true
$fatal = $false
try {
    Invoke-OwnerBootstrapRequest `
        -BaseUrl 'http://127.0.0.1:1' `
        -Secret 'listener-failure-secret-that-must-not-be-printed' `
        -Payload $payload `
        -ExpectedProcessId 123 `
        -ExpectedExecutablePath 'C:\Ticketbox\backend.exe' `
        -ListenPort 1 `
        -HealthRequestTimeoutMs 100 `
        -RequestTimeoutMs 1000 | Out-Null
}
catch [System.Security.SecurityException] {
    $fatal = $_.Exception.Message -match 'secret 可能已暴露'
}
if (-not $fatal -or $script:listenerChecks -ne 3) {
    throw 'listener post-check failure did not stop with an exposure warning'
}
"""
    _run_harness(
        tmp_path,
        "bootstrap-http-exception",
        body,
        forbidden_output=("listener-failure-secret-that-must-not-be-printed",),
    )


class _BootstrapHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[tuple[dict[str, str], bytes]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if self.path == "/oversized":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            chunk = b"x" * 65536
            try:
                for _ in range(17):
                    self.wfile.write(f"{len(chunk):X}\r\n".encode())
                    self.wfile.write(chunk + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        self._send_json({"status": "ok", "unexpected": True})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.requests.append((dict(self.headers.items()), body))
        payload = json.loads(body.decode())
        admin_token, upload_key, pairing_code = _derive_bootstrap_credentials(
            self.headers["X-Bootstrap-Secret"]
        )
        self._send_json(
            {
                "account_name": payload["account_name"],
                "ledger_name": payload["ledger_name"],
                "ledger_id": "owner",
                "device_name": payload["device_name"],
                "admin_token": admin_token,
                "upload_url_path": f"/u/{upload_key}",
                "upload_key": upload_key,
                "pairing_code": pairing_code,
                "pairing_expires_at": "2026-07-10T00:00:00Z",
            }
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows listener ownership behavior contract")
def test_bootstrap_requires_owned_listener_and_sends_utf8_json_bytes(tmp_path: Path) -> None:
    _BootstrapHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BootstrapHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        body = _function_loader(
            (
                "Get-BackendPortListeners",
                "Assert-BackendListenerOwnedByProcess",
                "Read-Utf8HttpResponseBody",
                "Invoke-DirectLoopbackHealthRequest",
                "Assert-StrictBackendHealthResponse",
                "Invoke-OwnerBootstrapRequest",
                "Get-BootstrapHmacDigest",
                "ConvertTo-Base64UrlWithoutPadding",
                "Get-DeterministicBootstrapCredentials",
                "Assert-BootstrapDerivationFixedVector",
                "Test-FixedTimeStringEquals",
                "Assert-BootstrapResponse",
            )
        )
        body += r"""
$expectedPid = [int]$args[0]
$expectedExe = [string](Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $expectedPid").ExecutablePath
$port = [int]$args[1]
$baseUrl = "http://127.0.0.1:$port"
Assert-BackendListenerOwnedByProcess -ExpectedProcessId $expectedPid -ExpectedExecutablePath $expectedExe -ListenPort $port
$wrongOwnerRejected = $false
try {
    Assert-BackendListenerOwnedByProcess -ExpectedProcessId ($expectedPid + 1) -ExpectedExecutablePath $expectedExe -ListenPort $port
}
catch {
    $wrongOwnerRejected = $true
}
if (-not $wrongOwnerRejected) { throw 'wrong listener owner was accepted' }
$wrongImageRejected = $false
try {
    Assert-BackendListenerOwnedByProcess -ExpectedProcessId $expectedPid -ExpectedExecutablePath (Join-Path $args[2] 'wrong.exe') -ListenPort $port
}
catch {
    $wrongImageRejected = $true
}
if (-not $wrongImageRejected) { throw 'wrong listener image was accepted' }
$health = Invoke-WebRequest -Uri "$baseUrl/api/health" -UseBasicParsing
Assert-StrictBackendHealthResponse $health
$invalidHealth = Invoke-WebRequest -Uri "$baseUrl/not-health" -UseBasicParsing
$invalidRejected = $false
try { Assert-StrictBackendHealthResponse $invalidHealth } catch { $invalidRejected = $true }
if (-not $invalidRejected) { throw 'non-minimal health JSON was accepted' }
$oversizedRequest = [System.Net.HttpWebRequest]::Create("$baseUrl/oversized")
$oversizedRequest.Proxy = $null
$oversizedRequest.AllowAutoRedirect = $false
$oversizedRequest.Timeout = 5000
$oversizedResponse = $null
$oversizedRejected = $false
try {
    $oversizedResponse = $oversizedRequest.GetResponse()
    Read-Utf8HttpResponseBody $oversizedResponse | Out-Null
}
catch {
    $oversizedRejected = $true
}
finally {
    if ($null -ne $oversizedResponse) { $oversizedResponse.Dispose() }
}
if (-not $oversizedRejected) { throw 'oversized chunked loopback response was accepted' }
$payload = @{
    account_name = '测试账户'
    ledger_name = '家庭账本'
    device_name = 'Windows 后端'
    default_timezone = 'Asia/Shanghai'
}
$response = Invoke-OwnerBootstrapRequest `
    -BaseUrl $baseUrl `
    -Secret $env:TEST_BOOTSTRAP_SECRET `
    -Payload $payload `
    -ExpectedProcessId $expectedPid `
    -ExpectedExecutablePath $expectedExe `
    -ListenPort $port `
    -HealthRequestTimeoutMs 2000 `
    -RequestTimeoutMs 15000
if ([string]$response.account_name -cne '测试账户') { throw 'bootstrap response decoding failed' }
Assert-BootstrapResponse -Response $response -Secret $env:TEST_BOOTSTRAP_SECRET
$response.admin_token = 'tbx_wrong'
$mismatchRejected = $false
try { Assert-BootstrapResponse -Response $response -Secret $env:TEST_BOOTSTRAP_SECRET } catch { $mismatchRejected = $true }
if (-not $mismatchRejected) { throw 'mismatched deterministic credentials were accepted' }
"""
        _run_harness(
            tmp_path,
            "bootstrap-behavior",
            body,
            arguments=(str(os.getpid()), str(port), str(tmp_path)),
            extra_env={"TEST_BOOTSTRAP_SECRET": VECTOR_SECRET},
            forbidden_output=(VECTOR_SECRET,),
            timeout=45,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    engines = _powershell_engines()
    assert len(_BootstrapHandler.requests) == len(engines)
    for headers, raw_body in _BootstrapHandler.requests:
        content_type = next(value for key, value in headers.items() if key.lower() == "content-type")
        assert content_type.lower() == "application/json; charset=utf-8"
        assert not raw_body.startswith(b"\xef\xbb\xbf")
        payload = json.loads(raw_body.decode("utf-8"))
        assert payload == {
            "account_name": "测试账户",
            "ledger_name": "家庭账本",
            "device_name": "Windows 后端",
            "default_timezone": "Asia/Shanghai",
        }
