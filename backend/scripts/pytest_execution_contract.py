"""Hermetic pytest collection and execution-identity contracts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from scripts.test_pg_contract import sanitized_libpq_test_environment

PYTEST_EXPECTED_COUNT_ENV = "XPJ_PYTEST_EXECUTION_EXPECTED_COUNT"
PYTEST_EXPECTED_DIGEST_ENV = "XPJ_PYTEST_EXECUTION_EXPECTED_DIGEST"
PYTEST_HANDSHAKE_PATH_ENV = "XPJ_PYTEST_EXECUTION_HANDSHAKE_PATH"
PYTEST_HANDSHAKE_TOKEN_ENV = "XPJ_PYTEST_EXECUTION_HANDSHAKE_TOKEN"
_PYTEST_NO_TESTS_COLLECTED = 5


@dataclass(frozen=True)
class PytestCollectionSnapshot:
    nodeids: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.nodeids)

    @property
    def digest(self) -> str:
        return pytest_nodeid_digest(self.nodeids)


def pytest_nodeid_digest(nodeids: Sequence[str]) -> str:
    canonical = "".join(f"{nodeid}\n" for nodeid in sorted(nodeids))
    return sha256(canonical.encode("utf-8")).hexdigest()


def pytest_execution_environment(
    environment: Mapping[str, str] | None = None,
    *,
    remove_keys: Iterable[str] = (),
) -> dict[str, str]:
    sanitized = sanitized_libpq_test_environment(
        os.environ if environment is None else environment
    )
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONOPTIMIZE",
        "PYTHONPATH",
        *remove_keys,
    ):
        sanitized.pop(key, None)
    for key in tuple(sanitized):
        if (
            key.startswith("PYTEST_XDIST_")
            or key.startswith("XPJ_TEST_RUNNER_")
            or key.startswith("XPJ_PYTEST_EXECUTION_")
        ):
            sanitized.pop(key)
    sanitized["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return sanitized


def pytest_collection_command(
    target: str,
    mark_expression: str | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        target,
        "--collect-only",
        "-q",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
    ]
    if mark_expression is not None:
        command.extend(["-m", mark_expression])
    command.extend(["-o", "addopts="])
    return command


def parse_pytest_collection(
    target: str,
    result: subprocess.CompletedProcess[str],
    *,
    allow_empty: bool,
) -> PytestCollectionSnapshot:
    if result.returncode == _PYTEST_NO_TESTS_COLLECTED and allow_empty:
        return PytestCollectionSnapshot(())
    if result.returncode != 0:
        raise RuntimeError(
            f"`pytest {target} --collect-only` failed (exit={result.returncode}).\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    count: int | None = None
    for line in reversed(result.stdout.splitlines()):
        match = re.search(r"(?:(\d+)/)?(\d+)\s+tests?\s+collected", line)
        if match:
            count = int(match.group(1) or match.group(2))
            break
    if count is None:
        raise RuntimeError(
            f"could not parse `pytest {target} --collect-only` output.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    nodeid_prefix = f"{target.rstrip('/')}/"
    nodeids = tuple(
        line.strip() for line in result.stdout.splitlines() if line.startswith(nodeid_prefix) and "::" in line
    )
    if len(nodeids) != count:
        raise RuntimeError(
            f"pytest reported {count} selected tests for {target!r}, but the collector emitted {len(nodeids)} node ids."
        )
    return PytestCollectionSnapshot(nodeids)


def collect_pytest_snapshot(
    target: str,
    *,
    mark_expression: str | None = None,
    backend_root: Path,
    allow_empty: bool = False,
    remove_environment: Iterable[str] = (),
) -> PytestCollectionSnapshot:
    result = subprocess.run(
        pytest_collection_command(target, mark_expression),
        cwd=backend_root,
        env=pytest_execution_environment(remove_keys=remove_environment),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    return parse_pytest_collection(target, result, allow_empty=allow_empty)


def pytest_execution_membership_violation(
    *,
    label: str,
    selected_nodeids: Sequence[str],
    expected_count: str | None,
    expected_digest: str | None,
    allow_empty: bool = False,
) -> str | None:
    try:
        count = int(expected_count or "")
    except ValueError:
        return f"Managed {label} pytest execution is missing its expected count."
    if (
        count < 0
        or (count == 0 and not allow_empty)
        or not expected_digest
        or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
    ):
        return f"Managed {label} pytest execution has an invalid collection proof."
    actual = tuple(selected_nodeids)
    if len(actual) == count and pytest_nodeid_digest(actual) == expected_digest:
        return None
    duplicates = sorted(nodeid for nodeid, amount in Counter(actual).items() if amount > 1)
    duplicate_summary = ", ".join(duplicates[:3]) or "none"
    return (
        f"Managed {label} pytest execution drifted from its independent collection: "
        f"expected_count={count}, actual_count={len(actual)}, "
        f"duplicate_nodeids=[{duplicate_summary}]."
    )


def pytest_execution_handshake_payload(
    label: str,
    token: str,
    count: int,
    digest: str,
) -> str:
    return f"{label}:{token}:{count}:{digest}\n"
