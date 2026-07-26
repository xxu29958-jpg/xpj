from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.report_qualification_sha import _checkout_parent_shas

_ROOT = Path(__file__).resolve().parents[2]
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
    audit_base: bool = False,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
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
    ]
    if audit_base:
        command.append("--audit-base")
    return subprocess.run(
        command,
        cwd=_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
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

    audit_environment = os.environ.copy()
    audit_environment.update(
        {
            "CI": "true",
            "GITHUB_EVENT_NAME": "repository_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "XPJ_AUDIT_DEFAULT_BRANCH": "main",
            "XPJ_AUDIT_DEFAULT_REF": "refs/remotes/origin/main",
        }
    )
    audit_environment.pop("XPJ_AUDIT_BASE_REF", None)
    audit_output = tmp_path / "audit-github-output"
    _run_reporter(
        audit_output,
        expected=expected,
        source=expected,
        check=True,
        audit_base=True,
        environment=audit_environment,
    )
    assert audit_output.read_text(encoding="utf-8") == (
        f"sha={expected}\nsource_sha={expected}\naudit_base_sha={parent}\n"
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
