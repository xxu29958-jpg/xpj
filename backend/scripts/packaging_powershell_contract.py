"""Validate the two PowerShell runtimes used by Windows packaging tests."""

from __future__ import annotations

import json
import os
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
POWERSHELL_CONTRACT_PROOF_ENV = "XPJ_PYTEST_EXECUTION_POWERSHELL_CONTRACT"


@lru_cache(maxsize=1)
def _powershell_contract_engine_paths() -> tuple[str, ...]:
    engines: list[str] = []
    for command, _edition, _minimum_major, _minimum_minor in _CONTRACTS:
        executable = shutil.which(command)
        assert executable is not None, f"required PowerShell host is missing: {command}"
        engines.append(str(Path(executable).resolve()))
    assert Path(engines[0]) != Path(engines[1]), "PowerShell hosts must be distinct"
    return tuple(engines)


def _assert_identity(
    *,
    command: str,
    edition: str,
    minimum_major: int,
    minimum_minor: int,
    actual: tuple[str, int, int],
) -> None:
    assert actual[0] == edition, f"{command} resolved to {actual[0]} instead of {edition}"
    if edition == "Desktop":
        assert actual[1:] == (minimum_major, minimum_minor), (
            f"{command} resolved to PowerShell {actual[1]}.{actual[2]} instead of 5.1"
        )
    else:
        assert actual[1:] >= (minimum_major, minimum_minor), (
            f"{command} resolved to unsupported PowerShell {actual[1]}.{actual[2]}"
        )


@lru_cache(maxsize=1)
def _probed_powershell_contract() -> tuple[tuple[str, str, int, int], ...]:
    engines = _powershell_contract_engine_paths()
    records: list[tuple[str, str, int, int]] = []
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
        _assert_identity(
            command=command,
            edition=edition,
            minimum_major=minimum_major,
            minimum_minor=minimum_minor,
            actual=actual,
        )
        records.append((executable, *actual))
    assert records[0][1] != records[1][1], "PowerShell editions must be distinct"
    return tuple(records)


def _engines_from_proof(raw_proof: str) -> tuple[str, ...]:
    try:
        records = json.loads(raw_proof)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError("PowerShell contract proof is malformed") from exc
    assert isinstance(records, list) and len(records) == len(_CONTRACTS), (
        "PowerShell contract proof has the wrong engine count"
    )
    discovered = _powershell_contract_engine_paths()
    engines: list[str] = []
    identities: list[tuple[str, int, int]] = []
    for contract, expected_path, record in zip(
        _CONTRACTS,
        discovered,
        records,
        strict=True,
    ):
        command, edition, minimum_major, minimum_minor = contract
        assert isinstance(record, list) and len(record) == 4, (
            "PowerShell contract proof has an invalid engine record"
        )
        actual_path = str(Path(str(record[0])).resolve())
        assert Path(actual_path) == Path(expected_path), (
            f"PowerShell contract proof path changed for {command}"
        )
        actual = (str(record[1]), int(record[2]), int(record[3]))
        _assert_identity(
            command=command,
            edition=edition,
            minimum_major=minimum_major,
            minimum_minor=minimum_minor,
            actual=actual,
        )
        engines.append(actual_path)
        identities.append(actual)
    assert identities[0][0] != identities[1][0], "PowerShell editions must be distinct"
    return tuple(engines)


@lru_cache(maxsize=1)
def _validated_powershell_contract_engines() -> tuple[str, ...]:
    proof = os.environ.get(POWERSHELL_CONTRACT_PROOF_ENV)
    if proof is not None:
        return _engines_from_proof(proof)
    return tuple(record[0] for record in _probed_powershell_contract())


def powershell_contract_preflight_proof() -> str:
    return json.dumps(_probed_powershell_contract(), separators=(",", ":"))


def powershell_contract_engine_paths() -> list[str]:
    return list(_powershell_contract_engine_paths())


def powershell_contract_engines() -> list[str]:
    return list(_validated_powershell_contract_engines())
