from __future__ import annotations

import json
import shutil
import subprocess
from functools import cache
from pathlib import Path

_PROBE = """
[ordered]@{
    edition = [string]$PSVersionTable.PSEdition
    major = [int]$PSVersionTable.PSVersion.Major
    minor = [int]$PSVersionTable.PSVersion.Minor
} | ConvertTo-Json -Compress
"""
# ``subprocess.run(timeout=...)`` also covers child communication, while
# process creation itself can exceed the requested interval on Windows. Keep
# the semantic identity checks exact but leave enough room for a cold hosted
# runner to start Windows PowerShell under transient CPU pressure.
_PROBE_TIMEOUT_SECONDS = 30


@cache
def _probe_contract_engines(
    contracts: tuple[tuple[str, str, int, int], ...],
) -> tuple[str, ...]:
    engines: list[str] = []
    identities: list[tuple[str, int, int]] = []
    for executable, edition, minimum_major, minimum_minor in contracts:
        command = Path(executable).name
        try:
            result = subprocess.run(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    _PROBE,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(f"PowerShell host probe timed out: {command}") from exc
        identity = json.loads(result.stdout.strip())
        actual = (
            str(identity["edition"]),
            int(identity["major"]),
            int(identity["minor"]),
        )
        assert actual[0] == edition, (
            f"{command} resolved to {actual[0]} instead of {edition}"
        )
        if edition == "Desktop":
            assert actual[1:] == (minimum_major, minimum_minor), (
                f"{command} resolved to PowerShell {actual[1]}.{actual[2]} instead of 5.1"
            )
        else:
            assert actual[1:] >= (minimum_major, minimum_minor), (
                f"{command} resolved to unsupported PowerShell {actual[1]}.{actual[2]}"
            )
        engines.append(str(Path(executable).resolve()))
        identities.append(actual)
    assert Path(engines[0]) != Path(engines[1]), "PowerShell hosts must be distinct"
    assert identities[0][0] != identities[1][0], "PowerShell editions must be distinct"
    return tuple(engines)


def powershell_contract_engines() -> tuple[str, ...]:
    contracts = (
        ("powershell", "Desktop", 5, 1),
        ("pwsh", "Core", 7, 0),
    )
    resolved: list[tuple[str, str, int, int]] = []
    for command, edition, minimum_major, minimum_minor in contracts:
        executable = shutil.which(command)
        assert executable is not None, f"required PowerShell host is missing: {command}"
        resolved.append(
            (
                str(Path(executable).resolve()),
                edition,
                minimum_major,
                minimum_minor,
            )
        )
    return _probe_contract_engines(tuple(resolved))
