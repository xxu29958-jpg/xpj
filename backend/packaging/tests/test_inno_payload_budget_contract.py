from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Inno arithmetic contract")
def test_installed_payload_allocation_budget_executes_checked_in_inno(tmp_path: Path) -> None:
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Inno Setup 6/ISCC.exe",
    )
    compiler = next((candidate for candidate in candidates if candidate.is_file()), None)
    assert compiler is not None, "Inno Setup 6 compiler is required"

    flow = (PACKAGING / "ticketbox-installer-flow.isph").read_text(encoding="utf-8-sig")
    budget_function = flow[
        flow.index("function TryGetInstalledPayloadAllocationBudget") : flow.index(
            "function AuthoritativePayloadSpaceError"
        )
    ]
    output_path = tmp_path / "installed-payload-allocation-budget.txt"
    source = tmp_path / "installed-payload-allocation-budget.iss"
    source.write_text(
        """
[Setup]
AppName=Ticketbox Installed Payload Allocation Budget Contract
AppVersion=1.0
DefaultDirName={tmp}\\TicketboxInstalledPayloadAllocationBudgetContract
PrivilegesRequired=lowest
Uninstallable=no
OutputDir=.
OutputBaseFilename=installed-payload-allocation-budget

[Code]
"""
        + budget_function
        + """
procedure AssertBudget(LogicalBytes, FileCount, AllocationUnitBytes,
  ExpectedBytes: Int64; ExpectedValid: Boolean);
var
  ActualBytes: Int64;
  ActualValid: Boolean;
begin
  ActualBytes := -1;
  ActualValid := TryGetInstalledPayloadAllocationBudget(
    LogicalBytes, FileCount, AllocationUnitBytes, ActualBytes);
  if ActualValid <> ExpectedValid then
    RaiseException('allocation budget validity drifted');
  if ActualValid and (ActualBytes <> ExpectedBytes) then
    RaiseException('allocation budget bytes drifted');
  if (not ActualValid) and (ActualBytes <> 0) then
    RaiseException('invalid allocation budget returned bytes');
end;

function InitializeSetup(): Boolean;
begin
  AssertBudget(10, 2, 4096, 8200, True);
  AssertBudget(1, 1, 1, 1, True);
  AssertBudget(0, 1, 4096, 0, False);
  AssertBudget(1, 0, 4096, 0, False);
  AssertBudget(1, 1, 0, 0, False);
  AssertBudget(9223372036854775800, 2, 4096, 0, False);
  if not SaveStringToFile(
    ExpandConstant('{param:OutputPath|}'), 'ok', False) then
    RaiseException('could not save allocation budget result');
  Result := False;
end;
""",
        encoding="utf-8-sig",
    )
    compile_result = subprocess.run(
        [compiler, source],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    run_result = subprocess.run(
        [
            tmp_path / "installed-payload-allocation-budget.exe",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            f"/OutputPath={output_path}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    assert output_path.is_file(), run_result.stdout + run_result.stderr
    assert output_path.read_text(encoding="utf-8-sig") == "ok"
