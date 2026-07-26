from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import report_qualification_sha as reporter

_ROOT = Path(__file__).resolve().parents[2]
_REPORTER = _ROOT / "backend" / "scripts" / "report_qualification_sha.py"


def _git_revision(revision: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", revision],
        cwd=_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=root,
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
    return subprocess.run(
        command,
        cwd=_ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_qualification_sha_reporter_uses_actual_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = _git_revision("HEAD")
    output = tmp_path / "github-output"
    completed = _run_reporter(output, expected=expected, source=expected, check=True)
    assert completed.stdout.strip() == (
        f"Qualification checkout SHA: {expected}; source SHA: {expected}"
    )
    assert output.read_text(encoding="utf-8") == (
        f"sha={expected}\nsource_sha={expected}\n"
    )

    parents = reporter._checkout_parent_shas()
    assert parents
    parent = parents[0]
    parent_output = tmp_path / "parent-github-output"
    _run_reporter(parent_output, expected=expected, source=parent, check=True)
    assert parent_output.read_text(encoding="utf-8") == (
        f"sha={expected}\nsource_sha={parent}\n"
    )

    audit_repo = tmp_path / "audit-repo"
    audit_repo.mkdir()
    _git(audit_repo, "init", "-q", "-b", "main")
    _git(audit_repo, "config", "user.email", "ci@example.invalid")
    _git(audit_repo, "config", "user.name", "CI Test")
    _git(audit_repo, "commit", "--allow-empty", "-qm", "base")
    audit_base = _git(audit_repo, "rev-parse", "HEAD")
    _git(audit_repo, "commit", "--allow-empty", "-qm", "qualification")
    audit_head = _git(audit_repo, "rev-parse", "HEAD")

    monkeypatch.setattr(reporter, "_REPOSITORY_ROOT", audit_repo)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "repository_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("XPJ_AUDIT_DEFAULT_BRANCH", "main")
    monkeypatch.setenv("XPJ_AUDIT_DEFAULT_REF", "refs/heads/main")
    monkeypatch.delenv("XPJ_AUDIT_BASE_REF", raising=False)
    audit_output = tmp_path / "audit-github-output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_REPORTER),
            "--expected",
            audit_head,
            "--source",
            audit_head,
            "--output",
            str(audit_output),
            "--audit-base",
        ],
    )
    assert reporter.main() == 0
    assert audit_output.read_text(encoding="utf-8") == (
        f"sha={audit_head}\n"
        f"source_sha={audit_head}\n"
        f"audit_base_sha={audit_base}\n"
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
