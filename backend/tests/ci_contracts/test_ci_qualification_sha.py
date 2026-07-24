from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.report_qualification_sha import _checkout_parent_shas
from tests._infra.paths import REPOSITORY_ROOT as _ROOT

_REPORTER = _ROOT / "backend" / "scripts" / "report_qualification_sha.py"


def _git_revision(revision: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", revision],
        cwd=_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _run_reporter(
    output: Path,
    *,
    expected: str,
    source: str,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-E",
            "-S",
            str(_REPORTER),
            "--expected",
            expected,
            "--source",
            source,
            "--output",
            str(output),
        ],
        cwd=_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_qualification_sha_reporter_uses_actual_checkout(tmp_path: Path) -> None:
    expected = _git_revision("HEAD")
    output = tmp_path / "github-output"
    completed = _run_reporter(output, expected=expected, source=expected, check=True)
    assert completed.stdout.strip() == (
        f"Qualification checkout SHA: {expected}; source SHA: {expected}"
    )
    assert output.read_text(encoding="utf-8") == (
        f"sha={expected}\nsource_sha={expected}\n"
    )

    parents = _checkout_parent_shas()
    assert parents
    parent = parents[0]
    parent_output = tmp_path / "parent-github-output"
    _run_reporter(parent_output, expected=expected, source=parent, check=True)
    assert parent_output.read_text(encoding="utf-8") == (
        f"sha={expected}\nsource_sha={parent}\n"
    )

    rejected_output = tmp_path / "rejected-github-output"
    rejected = _run_reporter(
        rejected_output,
        expected="0" * 40,
        source=expected,
        check=False,
    )
    assert rejected.returncode != 0
    assert "qualification checkout mismatch" in rejected.stderr
    assert not rejected_output.exists()
