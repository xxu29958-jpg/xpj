from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adr_contract_git import bootstrap_legacy_files, select_ratchet_base  # noqa: E402


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> str:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "adr@example.invalid")
    _git(root, "config", "user.name", "ADR Test")
    _git(root, "commit", "--allow-empty", "-qm", "base")
    return _git(root, "rev-parse", "HEAD")


def test_ci_requires_explicit_exact_base(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    selected, error = select_ratchet_base(tmp_path, {"CI": "1"})

    assert selected is None
    assert error == "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit"


def test_explicit_sha_and_local_main_resolve_without_remote_guessing(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-qb", "feature")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "feature")

    explicit, error = select_ratchet_base(
        tmp_path,
        {"CI": "1", "XPJ_AUDIT_BASE_REF": base},
    )
    local, local_error = select_ratchet_base(tmp_path, {})

    assert error is None
    assert explicit is not None and explicit.commit == base
    assert local_error is None
    assert local is not None and local.commit == base


def test_local_main_uses_parent_instead_of_comparing_head_with_itself(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    _git(tmp_path, "commit", "--allow-empty", "-qm", "current")

    selected, error = select_ratchet_base(tmp_path, {})

    assert error is None
    assert selected is not None
    assert selected.ref == "HEAD^1"
    assert selected.commit == base


def test_bootstrap_reads_only_legacy_blobs_from_exact_base(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    (decisions / "0001-legacy.md").write_text("# 0001 history\n", encoding="utf-8")
    (decisions / "0065-v2.md").write_text("+++\nschema_version = 2\n+++\n", encoding="utf-8")
    _git(tmp_path, "add", "docs/DECISIONS")
    _git(tmp_path, "commit", "-qm", "ADRs")
    base = _git(tmp_path, "rev-parse", "HEAD")

    files, errors = bootstrap_legacy_files(tmp_path, base)

    assert errors == []
    assert set(files) == {"0001"}
    assert files["0001"][0] == "docs/DECISIONS/0001-legacy.md"
