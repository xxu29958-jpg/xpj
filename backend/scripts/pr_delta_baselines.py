"""Responsibility-owned PR-delta baselines and their comparison policy."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

DebtCounts = dict[str, int]

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_COUNT_BASELINES = {
    "backend_pytest_count": Path("backend/audit/test_count_baseline.txt"),
    "installer_pytest_count": Path("backend/packaging/audit/test_count_baseline.txt"),
}

# Previously admitted installer harness retirements retain their exact base and
# original minimum floor. These are historical cuts, not a general waiver.
_INSTALLER_TEST_RETIREMENTS = (
    ("051464999fc1f71d9072bb5c9cfc012b521181cd", 387, 379),  # portable installer
    ("9d74b04f318362d5e222d897787db074bb5ca8ab", 379, 282),  # Generation Owner
    ("ce9a5aa413f20e5455fe0572d9416187038135b0", 283, 260),  # superuser capability
    ("6557125826d7c76a06568164814b4e5cb9e08f88", 369, 76),  # Windows vNext owner
)
_OWNER_RECYCLE_CARRIER_RETIREMENT = ("5436e40dddf437614ec01bf5703a5d5ce8197be3", 106, 105)
# Only the deleted Owner business restore route leaves the carrier inventory.
# The existing Web/API restore owner retains OCC. This exact hop cannot allow
# another endpoint to lose its token or a later count cycle to repeat the cut.


def baseline_retirement_allowed(key: str, base_commit: str | None, base: int, current: int) -> bool:
    if key == "mutate_token_carriers":
        return (base_commit, base, current) == _OWNER_RECYCLE_CARRIER_RETIREMENT
    if key == "installer_pytest_count":
        return any(
            base_commit == source and base == old_count and current >= floor
            for source, old_count, floor in _INSTALLER_TEST_RETIREMENTS
        )
    return False


def parse_count_baseline(text: str, *, source: str) -> int:
    value = text.strip()
    if not value.isascii() or not value.isdecimal():
        raise RuntimeError(f"invalid test-count baseline: {source}")
    return int(value)


def load_current_test_count_baselines() -> DebtCounts:
    return {
        key: parse_count_baseline(
            (REPO_ROOT / path).read_text(encoding="utf-8"),
            source=path.as_posix(),
        )
        for key, path in TEST_COUNT_BASELINES.items()
    }


def baseline_policy_mismatches(
    counts: DebtCounts,
    baseline: DebtCounts,
) -> list[tuple[str, int, int]]:
    """Keep test totals above their floors and structural counters exact."""
    return [
        (key, counts[key], baseline[key])
        for key in sorted(baseline)
        if key in counts
        and (
            counts[key] < baseline[key]
            if key in TEST_COUNT_BASELINES
            else counts[key] != baseline[key]
        )
    ]


def strict_baseline_literal(source: str) -> DebtCounts | None:
    tree = ast.parse(source)
    for statement in tree.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        if statement.target.id != "STRICT_EQUALITY_BASELINE" or statement.value is None:
            continue
        value = ast.literal_eval(statement.value)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(count, int)
            for key, count in value.items()
        ):
            return None
        return value
    return None


def git_show_text(git_ref: str, path: str, *, cwd: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "show", f"{git_ref}:{path}"],
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
