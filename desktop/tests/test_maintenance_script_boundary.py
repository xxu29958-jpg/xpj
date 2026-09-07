"""Execute the maintenance entry with a synthetic token and intercepted HTTP."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "maintenance_ticketbox.ps1"
_ALLOWED = (
    "http://127.0.0.1:8000",
    "https://localhost:8765/",
    "http://[::1]:8765",
)
_REJECTED = (
    "http://127.0.0.2:8000",
    "http://127.255.255.254:8765",
    "http://127.1:8765",
    "http://[0:0:0:0:0:0:0:1]:8765",
    "http://[::ffff:127.0.0.1]:8765",
    "https://maintenance.invalid",
    "http://192.0.2.1:8000",
    "http://localhost.maintenance.invalid",
    "ftp://127.0.0.1:8000",
    "/relative",
    "http://user@localhost:8000",
    "http://localhost:8000/?next=remote",
    "http://localhost:8000/#remote",
    "http://localhost:8000/proxy",
)
_HARNESS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
function Invoke-RestMethod {
    param($Method, $Uri, $Headers, $TimeoutSec, $MaximumRedirection)
    $global:maintenanceRequests.Add([pscustomobject]@{
        method = $Method
        uri = [string]$Uri
        authenticated = $Headers.Authorization -eq 'Bearer qualification-token'
        redirects = $MaximumRedirection
    })
    return @{ scanned = 0; deleted_images = 0; deleted_thumbnails = 0 }
}
$results = foreach ($serverUrl in $inputData.urls) {
    $global:maintenanceRequests = [System.Collections.Generic.List[object]]::new()
    $rejected = $false
    $errorId = $null
    $errorType = $null
    try {
        & $inputData.script -ServerUrl $serverUrl -AdminToken 'qualification-token' `
            -CleanupConfirmedImages -CleanupRejectedImages *> $null
    } catch {
        $rejected = $true
        $errorId = $_.FullyQualifiedErrorId
        $errorType = $_.Exception.GetType().FullName
    }
    [pscustomobject]@{
        url = $serverUrl; rejected = $rejected; errorId = $errorId; errorType = $errorType
        requests = @($global:maintenanceRequests)
    }
}
ConvertTo-Json -InputObject @($results) -Depth 5 -Compress
"""


@pytest.fixture(scope="module")
def maintenance_results() -> dict[str, dict[str, object]]:
    if sys.platform != "win32":
        pytest.skip("the maintenance entry is a Windows PowerShell consumer")
    powershell = shutil.which("powershell")
    assert powershell is not None, "Windows PowerShell must execute the maintenance entry"
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _HARNESS],
        input=json.dumps({"script": str(_SCRIPT), "urls": _ALLOWED + _REJECTED}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    return {result["url"]: result for result in json.loads(completed.stdout)}


@pytest.mark.parametrize("url", _REJECTED)
def test_maintenance_refuses_invalid_authority_before_sending_token(
    maintenance_results: dict[str, dict[str, object]], url: str,
) -> None:
    result = maintenance_results[url]
    assert result["rejected"] is True
    assert result["errorType"] == "System.ArgumentException"
    assert result["requests"] == []


@pytest.mark.parametrize("url", _ALLOWED)
def test_maintenance_uses_only_the_validated_local_authority(
    maintenance_results: dict[str, dict[str, object]], url: str,
) -> None:
    result = maintenance_results[url]
    assert result["rejected"] is False, result["errorId"]
    assert result["requests"] == [
        {
            "method": "Post",
            "uri": url.rstrip("/") + path,
            "authenticated": True,
            "redirects": 0,
        }
        for path in ("/api/maintenance/cleanup-images", "/api/maintenance/cleanup-rejected")
    ]
