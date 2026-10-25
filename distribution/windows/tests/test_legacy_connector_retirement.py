"""Installed services cannot be changed through the old source-support entrypoints."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHELL = shutil.which("powershell.exe") or shutil.which("pwsh")
ENTRYPOINTS = (
    "scripts/ensure_ticketbox_runtime.ps1", "scripts/install_windows_tasks.ps1",
    "scripts/uninstall_windows_tasks.ps1", "scripts/start_backend.ps1", "scripts/stop_backend.ps1",
    "scripts/restart_backend.ps1", "scripts/diagnose_ticketbox.ps1", "scripts/check_service_status.ps1",
    "scripts/show_server_status.ps1", "backend/scripts/start_backend.ps1", "backend/scripts/install_startup_task.ps1",
)


@pytest.mark.skipif(SHELL is None, reason="PowerShell is required for the legacy entrypoint boundary")
@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_installed_service_refuses_legacy_entrypoint_before_any_host_action(entrypoint):
    path = str(ROOT / entrypoint).replace("'", "''")
    script = """
$ErrorActionPreference='Stop'
function Get-Service { [CmdletBinding()]param([string[]]$Name); [pscustomobject]@{Name='TicketboxBackend'} }
foreach ($name in @('Start-Service','Stop-Service','Start-ScheduledTask','Stop-ScheduledTask',
    'Register-ScheduledTask','Unregister-ScheduledTask','Start-Process','Stop-Process','New-Item')) {
    Set-Item -Path "function:$name" -Value { throw 'UNEXPECTED_HOST_MUTATION' }
}
try {
    & '__ENTRYPOINT__'
    exit 31
} catch {
    if ($_.Exception.Message -like '*ticketbox_source_runtime_only*') { Write-Output 'REFUSED_BEFORE_HOST_ACTION'; exit 0 }
    Write-Output $_.Exception.Message
    exit 32
}
""".replace("__ENTRYPOINT__", path)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert b"REFUSED_BEFORE_HOST_ACTION" in result.stdout


def test_old_support_scripts_no_longer_produce_or_start_connector_tasks():
    installer = (ROOT / "scripts/install_windows_tasks.ps1").read_text("utf-8-sig")
    ensure = (ROOT / "scripts/ensure_ticketbox_runtime.ps1").read_text("utf-8-sig")
    assert "CloudflaredArguments" not in installer and "Resolve-Cloudflared" not in installer
    assert "Start-Service" not in installer + ensure
    assert "TunnelTaskName" not in installer + ensure
