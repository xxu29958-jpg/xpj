from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _powershell_contract import powershell_contract_engines

from scripts.test_pg_contract import (
    test_postgres_consumer_lease as consumer_lease,
)
from scripts.test_pg_protected_file import ensure_protected_directory

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESS_CONTRACT = PROJECT_ROOT / "backend" / "scripts" / "test_pg_process_contract.ps1"
CLUSTER_CONTRACT = PROJECT_ROOT / "backend" / "scripts" / "test_pg_cluster_contract.ps1"


def _free_local_port() -> int:
    while True:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        if port not in {5432, 5433}:
            return port


def _windows_process_is_running(process_id: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, process_id)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process identity")
def test_uncommitted_process_uses_handle_identity_and_complete_pid_publication(
    tmp_path: Path,
) -> None:
    child = tmp_path / "delayed-pid-child.ps1"
    child.write_text(
        "param($PidPath,$ReleasePath)\n"
        "[IO.File]::WriteAllText($PidPath,'')\n"
        "Start-Sleep -Milliseconds 250\n"
        "[IO.File]::WriteAllText($PidPath,[string]$PID)\n"
        "while (-not (Test-Path -LiteralPath $ReleasePath)) {\n"
        "    Start-Sleep -Milliseconds 50\n"
        "}\n",
        encoding="ascii",
    )
    parent = tmp_path / "commit-delayed-child.ps1"
    parent.write_text(
        "param($Contract,$Target,$Child,$PidPath,$ReleasePath,$ReadyPath,"
        "$StdoutPath,$StderrPath)\n"
        ". $Contract\n"
        "$transaction = Start-XpjTestPostgresUncommittedProcess "
        "-FilePath $Target -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive',"
        "'-ExecutionPolicy','Bypass','-File',$Child,'-PidPath',$PidPath,"
        "'-ReleasePath',$ReleasePath) "
        "-TargetPidSourcePath $PidPath -TargetStdoutPath $StdoutPath "
        "-TargetStderrPath $StderrPath -TimeoutSeconds 10\n"
        "Complete-XpjTestPostgresUncommittedProcess $transaction\n"
        "[IO.File]::WriteAllText($ReadyPath,[string]$transaction.TargetProcessId)\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        pid_path = tmp_path / f"child-{index}.pid"
        release_path = tmp_path / f"child-{index}.release"
        ready_path = tmp_path / f"child-{index}.ready"
        stdout_path = tmp_path / f"child-{index}.stdout"
        stderr_path = tmp_path / f"child-{index}.stderr"
        child_pid: int | None = None
        try:
            completed = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(parent),
                    "-Contract",
                    str(PROCESS_CONTRACT),
                    "-Target",
                    engine,
                    "-Child",
                    str(child),
                    "-PidPath",
                    str(pid_path),
                    "-ReleasePath",
                    str(release_path),
                    "-ReadyPath",
                    str(ready_path),
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
            output = completed.stdout + completed.stderr
            assert completed.returncode == 0, output
            child_pid = int(ready_path.read_text(encoding="ascii"))
            assert _windows_process_is_running(child_pid)
        finally:
            release_path.write_text("release", encoding="ascii")
            if child_pid is not None:
                deadline = time.monotonic() + 10
                while _windows_process_is_running(child_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if _windows_process_is_running(child_pid):
                    os.kill(child_pid, 15)
            assert child_pid is None or not _windows_process_is_running(child_pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows lease authority")
def test_python_and_powershell_share_the_cluster_generation_lease_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_root = tmp_path / "tmp-root"
    temp_root = tmp_path / "temp-root"
    tmpdir_root = tmp_path / "tmpdir-root"
    for root in (tmp_root, temp_root, tmpdir_root):
        root.mkdir()
    monkeypatch.setenv("TMP", str(tmp_root))
    monkeypatch.setenv("TEMP", str(temp_root))
    monkeypatch.setenv("TMPDIR", str(tmpdir_root))
    setup = tmp_path / "setup-lease-authority.ps1"
    setup.write_text(
        "param($Contract,$DataDirectory,$Port,$SystemIdentifier)\n"
        ". $Contract\n"
        "[void][IO.Directory]::CreateDirectory($DataDirectory)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n"
        "$payload = [ordered]@{\n"
        "  schema_version = 3; kind = 'xiaopiaojia-test-postgres';\n"
        "  purpose = 'local'; port = [int]$Port; instance_id = ('a' * 32);\n"
        "  system_identifier = $SystemIdentifier; authentication = 'scram-sha-256'\n"
        "} | ConvertTo-Json -Compress\n"
        "Write-XpjTestPostgresProtectedUtf8File "
        "-Path (Join-Path $DataDirectory '.xpj-test-cluster.json') "
        "-Content ($payload + [Environment]::NewLine)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n",
        encoding="ascii",
    )
    contender = tmp_path / "contend-lifecycle.ps1"
    contender.write_text(
        "param($Contract,$Port,$DataDirectory)\n"
        ". $Contract\n"
        "Invoke-XpjTestPostgresLifecycleLocked "
        "-Port $Port -DataDirectory $DataDirectory "
        "-TimeoutSeconds 1 -Operation {}\n",
        encoding="ascii",
    )
    port = _free_local_port()
    instance_id = "a" * 32
    system_identifier = "1234567890123456789"

    for index, engine in enumerate(powershell_contract_engines()):
        data_directory = tmp_path / f"cluster-{index}"
        prepared = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(setup),
                "-Contract",
                str(CLUSTER_CONTRACT),
                "-DataDirectory",
                str(data_directory),
                "-Port",
                str(port),
                "-SystemIdentifier",
                system_identifier,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        environment = os.environ.copy() | {
            "XPJ_TEST_CLUSTER_AUTHORITY": "owned-marker",
            "XPJ_TEST_CLUSTER_INSTANCE_ID": instance_id,
            "XPJ_TEST_CLUSTER_MARKER_PATH": str(
                data_directory / ".xpj-test-cluster.json"
            ),
            "XPJ_TEST_CLUSTER_SYSTEM_IDENTIFIER": system_identifier,
        }
        command = [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(contender),
            "-Contract",
            str(CLUSTER_CONTRACT),
            "-Port",
            str(port),
            "-DataDirectory",
            str(data_directory),
        ]
        with monkeypatch.context() as wrong_generation:
            for name, value in environment.items():
                wrong_generation.setenv(name, value)
            wrong_generation.setenv("XPJ_TEST_CLUSTER_INSTANCE_ID", "f" * 32)
            with (
                pytest.raises(RuntimeError, match="generation"),
                consumer_lease(
                    f"postgresql+psycopg://postgres@127.0.0.1:{port}/xpj_test",
                    timeout_ms=5000,
                ),
            ):
                pass
        with monkeypatch.context() as lease_environment:
            for name, value in environment.items():
                lease_environment.setenv(name, value)
            lease = consumer_lease(
                f"postgresql+psycopg://postgres@127.0.0.1:{port}/xpj_test",
                timeout_ms=5000,
            )
            with lease:
                blocked = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    timeout=10,
                )
                assert blocked.returncode != 0
                assert "consumer lease" in (blocked.stdout + blocked.stderr)
        unblocked = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=10,
        )
        assert unblocked.returncode == 0, unblocked.stdout + unblocked.stderr
        assert not (
            data_directory / ".xpj-test-postgres-consumers"
        ).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL authority")
def test_test_cluster_acl_removes_untrusted_write_authority(tmp_path: Path) -> None:
    data_dir = tmp_path / "cluster"
    data_dir.mkdir()
    (data_dir / "child.txt").write_text("proof", encoding="ascii")
    probe = tmp_path / "acl-contract.ps1"
    probe.write_text(
        "param($Contract,$DataDirectory)\n"
        ". $Contract\n"
        "& (Join-Path $env:SystemRoot 'System32\\icacls.exe') "
        "$DataDirectory /grant '*S-1-1-0:(OI)(CI)M' /T /Q | Out-Null\n"
        "if ($LASTEXITCODE -ne 0) { throw 'could not create ACL mutation' }\n"
        "if (Test-XpjTestPostgresTrustedAcl $DataDirectory) { "
        "throw 'mutation was not observable' }\n"
        "$refused = $false\n"
        "try { Assert-XpjTestPostgresDirectoryTreeAcl $DataDirectory } "
        "catch { $refused = $true }\n"
        "if (-not $refused) { throw 'untrusted ACL was not rejected' }\n"
        "$worldBeforeRepair = $false\n"
        "$rootAcl = Get-XpjTestPostgresAcl (Get-Item -LiteralPath $DataDirectory)\n"
        "foreach ($rule in @($rootAcl.GetAccessRules($true,$true,"
        "[Security.Principal.SecurityIdentifier]))) {\n"
        "  if ($rule.IdentityReference.Value -eq 'S-1-1-0') { "
        "$worldBeforeRepair = $true }\n"
        "}\n"
        "if (-not $worldBeforeRepair) { throw 'validation mutated the ACL before refusing' }\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n"
        "if (-not (Test-XpjTestPostgresTrustedAcl $DataDirectory)) { "
        "throw 'root ACL was not normalized' }\n"
        "$expectedOwner = [Security.Principal.WindowsIdentity]::GetCurrent().Owner.Value\n"
        "$actualOwner = (Get-XpjTestPostgresAcl "
        "(Get-Item -LiteralPath $DataDirectory)).GetOwner("
        "[Security.Principal.SecurityIdentifier]).Value\n"
        "if ($actualOwner -cne $expectedOwner) { "
        "throw 'root owner does not match the current token owner' }\n"
        "$world = 'S-1-1-0'\n"
        "foreach ($item in @(Get-ChildItem -LiteralPath $DataDirectory -Force)) {\n"
        "  $acl = Get-XpjTestPostgresAcl $item\n"
        "  foreach ($rule in @($acl.GetAccessRules($true,$false,"
        "[Security.Principal.SecurityIdentifier]))) {\n"
        "    if ($rule.IdentityReference.Value -eq $world) { "
        "throw 'untrusted child ACL survived' }\n"
        "  }\n"
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
                str(CLUSTER_CONTRACT),
                "-DataDirectory",
                str(data_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        ensure_protected_directory(
            data_dir.resolve(),
            label="PowerShell-normalized PostgreSQL test directory",
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL authority")
def test_test_cluster_authority_files_require_protected_acl_and_exact_credentials(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "authority-files.ps1"
    probe.write_text(
        "param($Contract,$Root)\n"
        ". $Contract\n"
        "function Add-UntrustedAcl($Path) {\n"
        "  & (Join-Path $env:SystemRoot 'System32\\icacls.exe') "
        "$Path /grant '*S-1-1-0:M' /Q | Out-Null\n"
        "  if ($LASTEXITCODE -ne 0) { throw 'could not mutate authority ACL' }\n"
        "}\n"
        "function Assert-ReadRefused($Operation,$Label) {\n"
        "  $refused = $false\n"
        "  try { & $Operation } catch { $refused = $true }\n"
        "  if (-not $refused) { throw \"$Label accepted an untrusted ACL\" }\n"
        "}\n"
        "[void][IO.Directory]::CreateDirectory($Root)\n"
        "$collision = Join-Path $Root 'preexisting-authority.txt'\n"
        "[IO.File]::WriteAllText($collision, 'original')\n"
        "$collisionRefused = $false\n"
        "try { Write-XpjTestPostgresProtectedUtf8File "
        "-Path $collision -Content 'replacement' } catch { $collisionRefused = $true }\n"
        "if (-not $collisionRefused) { throw 'protected writer accepted collision' }\n"
        "if (-not (Test-Path -LiteralPath $collision -PathType Leaf)) { "
        "throw 'protected writer deleted pre-existing collision' }\n"
        "if ([IO.File]::ReadAllText($collision) -cne 'original') { "
        "throw 'protected writer changed pre-existing collision' }\n"
        "$staging = Join-Path $Root '.final.xpj-init-authority'\n"
        "[void][IO.Directory]::CreateDirectory($staging)\n"
        "$handle = [XpjTestDirectoryMoveHandle]::OpenIdentity($staging)\n"
        "try {\n"
        "  $stagingReceipt = \"$staging.receipt.json\"\n"
        "  New-XpjTestPostgresStagingReceipt -ReceiptPath $stagingReceipt "
        "-StagingDirectory $staging -FinalDataDirectory (Join-Path $Root 'final') "
        "-Purpose local -Port 5438 -InstanceId ('a' * 32) "
        "-DirectoryIdentity $handle.Identity\n"
        "} finally { $handle.Dispose() }\n"
        "if (-not (Test-XpjTestPostgresTrustedAcl $stagingReceipt -RequireProtected)) { "
        "throw 'staging receipt was not protected at creation' }\n"
        "Add-UntrustedAcl $stagingReceipt\n"
        "Assert-ReadRefused { Read-XpjTestPostgresStagingReceipt "
        "-ReceiptPath $stagingReceipt -FinalDataDirectory (Join-Path $Root 'final') "
        "-Purpose local -Port 5438 } 'staging receipt'\n"
        "$final = Join-Path $Root 'delete-target'\n"
        "$deleteReceipt = Get-XpjTestPostgresDeletionReceiptPath $final\n"
        "$deletePayload = [ordered]@{\n"
        "  Kind='xiaopiaojia-test-postgres-deletion'; DataDirectory=$final; "
        "TombstoneDirectory=(Join-Path $Root ('.delete-target.xpj-delete-' + ('b' * 32))); "
        "Phase='source'; Purpose='local'; Port=5438; InstanceId=('c' * 32); "
        "SystemIdentifier='1234567890123456789'; "
        "DirectoryIdentity='00000001:00000002:00000003'; "
        "OwnerProcessId=$PID; OwnerStartedAtUtc=(Get-Date).ToUniversalTime().ToString('O')\n"
        "} | ConvertTo-Json -Compress\n"
        "Write-XpjTestPostgresProtectedUtf8File -Path $deleteReceipt -Content $deletePayload\n"
        "$delete = Read-XpjTestPostgresDeletionReceipt -ReceiptPath $deleteReceipt "
        "-DataDirectory $final -Purpose local -Port 5438\n"
        "Set-XpjTestPostgresDeletionReceiptPhase -Receipt $delete "
        "-ReceiptPath $deleteReceipt -Phase tombstone\n"
        "if (-not (Test-XpjTestPostgresTrustedAcl $deleteReceipt -RequireProtected)) { "
        "throw 'deletion receipt replacement lost its ACL' }\n"
        "Add-UntrustedAcl $deleteReceipt\n"
        "Assert-ReadRefused { Read-XpjTestPostgresDeletionReceipt "
        "-ReceiptPath $deleteReceipt -DataDirectory $final -Purpose local -Port 5438 "
        "} 'deletion receipt'\n"
        "$credentialDirectory = Join-Path $Root 'credential'\n"
        "[void][IO.Directory]::CreateDirectory($credentialDirectory)\n"
        "Protect-XpjTestPostgresDirectoryTree $credentialDirectory\n"
        "$credentialPath = Get-XpjTestPostgresCredentialPath $credentialDirectory\n"
        "Write-XpjTestPostgresProtectedUtf8File -Path $credentialPath "
        "-Content (('d' * 43) + [Environment]::NewLine + [Environment]::NewLine)\n"
        "$invalidCredentialRefused = $false\n"
        "try { [void](Read-XpjTestPostgresCredential $credentialDirectory) } "
        "catch { $invalidCredentialRefused = $true }\n"
        "if (-not $invalidCredentialRefused) { throw 'credential accepted extra records' }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
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
                str(CLUSTER_CONTRACT),
                "-Root",
                str(tmp_path / f"authority-files-{index}"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path authority")
def test_test_cluster_path_lease_blocks_ancestor_retarget(tmp_path: Path) -> None:
    parent = tmp_path / "authority-parent"
    target = parent / "cluster"
    replacement = tmp_path / "authority-replaced"
    target.mkdir(parents=True)
    probe = tmp_path / "path-lease.ps1"
    probe.write_text(
        "param($Contract,$Parent,$Target,$Replacement)\n"
        ". $Contract\n"
        "$lease = [XpjTestDirectoryPathLease]::OpenPath($Target)\n"
        "try {\n"
        "  $blocked = $false\n"
        "  try { [IO.Directory]::Move($Parent, $Replacement) } "
        "catch { $blocked = $true }\n"
        "  if (-not $blocked) { throw 'ancestor retarget was not blocked' }\n"
        "}\n"
        "finally { $lease.Dispose() }\n"
        "[IO.Directory]::Move($Parent, $Replacement)\n",
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
                str(CLUSTER_CONTRACT),
                "-Parent",
                str(parent),
                "-Target",
                str(target),
                "-Replacement",
                str(replacement),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        replacement.rename(parent)
