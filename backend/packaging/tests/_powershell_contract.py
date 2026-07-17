from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_PROBE = """
[ordered]@{
    edition = [string]$PSVersionTable.PSEdition
    major = [int]$PSVersionTable.PSVersion.Major
    minor = [int]$PSVersionTable.PSVersion.Minor
} | ConvertTo-Json -Compress
"""
_PROBE_TIMEOUT_SECONDS = 10
_CONTRACTS = (
    ("powershell", "Desktop", 5, 1),
    ("pwsh", "Core", 7, 0),
)


@lru_cache(maxsize=1)
def _powershell_contract_engine_paths() -> tuple[str, ...]:
    engines: list[str] = []
    for command, _edition, _minimum_major, _minimum_minor in _CONTRACTS:
        executable = shutil.which(command)
        assert executable is not None, f"required PowerShell host is missing: {command}"
        engines.append(str(Path(executable).resolve()))
    assert Path(engines[0]) != Path(engines[1]), "PowerShell hosts must be distinct"
    return tuple(engines)


@lru_cache(maxsize=1)
def _validated_powershell_contract_engines() -> tuple[str, ...]:
    engines = _powershell_contract_engine_paths()
    identities: list[tuple[str, int, int]] = []
    for (command, edition, minimum_major, minimum_minor), executable in zip(
        _CONTRACTS,
        engines,
        strict=True,
    ):
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
        identities.append(actual)
    assert identities[0][0] != identities[1][0], "PowerShell editions must be distinct"
    return engines


def powershell_contract_engine_paths() -> list[str]:
    return list(_powershell_contract_engine_paths())


def powershell_contract_engines() -> list[str]:
    return list(_validated_powershell_contract_engines())
