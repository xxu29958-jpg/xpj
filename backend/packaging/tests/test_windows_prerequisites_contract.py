from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _powershell_contract import powershell_contract_engines

ROOT = Path(__file__).resolve().parents[3]
PACKAGING = ROOT / "backend" / "packaging"
PREREQUISITE = PACKAGING / "install_windows_prerequisites.ps1"


def _read(name: str, *, sig: bool = False) -> str:
    return (PACKAGING / name).read_text(encoding="utf-8-sig" if sig else "utf-8")


def _ps_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def test_visual_cpp_runtime_is_an_official_pinned_central_prerequisite() -> None:
    toolchain = json.loads(_read("windows-build-toolchain.json"))
    source = toolchain["installer_vendor_sources"]["visual_cpp_runtime"]
    vendor = _read("prepare_windows_installer_vendor.ps1", sig=True)
    build = _read("build_inno_installer.ps1", sig=True)
    setup = _read("ticketbox-installer.iss")
    windows = _read("ticketbox-installer-windows.isph")
    flow = _read("ticketbox-installer-flow.isph")
    uninstall = _read("uninstall_bundled_services.ps1", sig=True)

    assert source == {
        "version": "14.44.35211.0",
        "archive_name": "vc_redist.x64.exe",
        "url": (
            "https://download.visualstudio.microsoft.com/download/pr/"
            "9b0d1fa5-c16d-4ee8-97f0-c2734086ece8/"
            "CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B/"
            "VC_redist.x64.exe"
        ),
        "sha256": "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b",
        "architecture": "x64",
        "file_version": "14.44.35211.0",
        "product_version": "14.44.35211.0",
        "original_filename": "VC_redist.x64.exe",
        "company_name": "Microsoft Corporation",
        "signer_subject": (
            "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, "
            "S=Washington, C=US"
        ),
        "signer_thumbprint": "8F985BE8FD256085C90A95D3C74580511A1DB975",
        "runtime_file": "VCRUNTIME140.dll",
    }
    assert "Get-AuthenticodeSignature -LiteralPath $Path" in vendor
    assert "Get-AuthenticodeSignature -LiteralPath $ExecutablePath" in build
    assert '"/DVisualCppRuntimeSha256=$($visualCppRuntimeProvenance.executable.sha256)"' in build
    assert '"/DVisualCppRuntimeVersion=$($visualCppRuntimeProvenance.version)"' in build
    assert 'Source: "vendor\\vc-runtime\\vc_redist.x64.exe";' in setup
    assert 'DestDir: "{app}"' not in next(
        line for line in setup.splitlines() if "vc_redist.x64.exe" in line
    )
    assert "Flags: dontcopy noencryption" in next(
        line for line in setup.splitlines() if "vc_redist.x64.exe" in line
    )
    assert "StageLifecycleLockBootstrapFile(\n    'vc_redist.x64.exe'" in windows
    assert "ValidateLifecycleLockBootstrapFile(\n      'vc_redist.x64.exe'" in windows
    prepare = flow[
        flow.index("function PrepareToInstall") : flow.index(
            "function AuthoritativePayloadReplacementPrepared"
        )
    ]
    prerequisite_call = prepare.index("'Ticketbox Windows prerequisite installation'")
    normal_install_gate = prepare.index(
        "if not StartManagerMaintenanceGate()", prerequisite_call
    )
    assert prerequisite_call < prepare.index("AuthoritativePayloadSpaceError()")
    assert prerequisite_call < normal_install_gate
    assert prepare.index("CheckBackendVersionFloorForDataRoot") < prerequisite_call
    assert prepare.index("Result := FreshInstallPortError();") < prerequisite_call
    assert "vc_redist" not in uninstall.lower()


def test_prerequisite_uses_native_registry_and_official_quiet_exit_semantics() -> None:
    script = PREREQUISITE.read_text(encoding="utf-8-sig")
    windows = _read("ticketbox-installer-windows.isph")

    assert "[Microsoft.Win32.RegistryView]::Registry64" in script
    assert "SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" in script
    assert "System32\\VCRUNTIME140.dll" in script
    for argument in ("'/install'", "'/repair'", "'/quiet'", "'/norestart'", "'/log'"):
        assert argument in script
    assert "$nativeExitCode -in @(1641, 3010)" in script
    assert "$nativeExitCode -eq 1638 -and $after.Satisfied" in script
    assert "newer machine-wide VC runtime" in script
    assert "TBX_PREREQ_SCHEMA=ticketbox-windows-prerequisite-v1" in script
    assert "TBX-INSTALL-PREREQ-RESTART" in windows
    assert "TBX-INSTALL-PREREQ" in windows
    assert "LastPowerShellRestartRequired" in windows


def test_visual_cpp_runtime_version_contract_matches_on_powershell_51_and_7() -> None:
    cases = (
        ("v14.44.35211.00", "14.44.35211.0", 0),
        ("14.50", "14.44.35211.0", 1),
        ("14.30.1", "14.44.35211.0", -1),
    )
    for engine in powershell_contract_engines():
        for left, right, expected in cases:
            result = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    PREREQUISITE,
                    "-VersionContractProbe",
                    left,
                    "-OtherVersionContractProbe",
                    right,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                timeout=30,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            evidence = json.loads(result.stdout.strip())
            assert evidence["comparison"] == expected
        rejected = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                PREREQUISITE,
                "-VersionContractProbe",
                "14.latest",
                "-OtherVersionContractProbe",
                "14.44.35211.0",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert rejected.returncode != 0


def test_initdb_native_status_is_preserved_as_unsigned_and_hex_on_both_hosts() -> None:
    database = PACKAGING / "windows_bundled_database.ps1"
    service_install = _read("install_bundled_services.ps1", sig=True)
    assert "[int]$snapshot.ServiceSpecificExitCode" not in service_install
    assert "[uint64]([uint32]$snapshot.ServiceSpecificExitCode)" in service_install

    command = f"""
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    '{_ps_literal(database)}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ throw ($errors -join '; ') }}
foreach ($name in @(
    'Get-TicketboxNativeExitCodeEvidence',
    'New-TicketboxInitdbFailure'
)) {{
    $node = $ast.Find({{
        param($candidate)
        $candidate -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $candidate.Name -ceq $name
    }}, $true)
    if ($null -eq $node) {{ throw "missing function: $name" }}
    Invoke-Expression $node.Extent.Text
}}
$unsignedFailure = New-TicketboxInitdbFailure `
    -FailureKind 'service_process_failed' `
    -ExitCode ([uint32]3221225781)
$signedFailure = New-TicketboxInitdbFailure `
    -FailureKind 'native_process_failed' `
    -ExitCode ([int32]-1073741515)
[ordered]@{{
    unsigned = [uint64]$unsignedFailure.Data['TicketboxNativeExitCodeUnsigned']
    signed = [int64]$unsignedFailure.Data['TicketboxNativeExitCodeSigned']
    hex = [string]$unsignedFailure.Data['TicketboxNativeExitCodeHex']
    unsigned_message = $unsignedFailure.Message
    signed_hex = [string]$signedFailure.Data['TicketboxNativeExitCodeHex']
    signed_unsigned = [uint64]$signedFailure.Data['TicketboxNativeExitCodeUnsigned']
}} | ConvertTo-Json -Compress
"""
    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = json.loads(result.stdout.strip())
        assert evidence == {
            "unsigned": 3221225781,
            "signed": -1073741515,
            "hex": "0xC0000135",
            "unsigned_message": (
                "initdb 未完成（kind=service_process_failed, "
                "exit=3221225781 (0xC0000135; signed=-1073741515)）。"
            ),
            "signed_hex": "0xC0000135",
            "signed_unsigned": 3221225781,
        }
