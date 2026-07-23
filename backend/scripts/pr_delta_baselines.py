"""Data loading for PR-delta baselines.

Policy stays in ``codebase_audit_gate``. This module only loads the current
responsibility-owned count files and their exact-base counterparts.
"""

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
