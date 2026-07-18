from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.test_impact_selection import create_impact_plan

pytestmark = pytest.mark.parallel_safe


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Codex Test",
        "-c",
        "user.email=codex-test@example.invalid",
        "commit",
        "-qm",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _route_repo(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    backend = repo / "backend"
    _write(
        backend,
        "app/routes/sample.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api/old')\n"
        "@router.get('')\n"
        "def sample():\n"
        "    return 1\n",
    )
    _write(
        backend,
        "tests/test_old.py",
        "def test_old(client):\n    client.get('/api/old')\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_other_{index}.py",
            f"def test_other_{index}():\n    pass\n",
        )
    _git(repo, "init", "-q")
    base = _commit(repo, "base")

    _write(
        backend,
        "app/routes/sample.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api/new')\n"
        "@router.get('')\n"
        "def sample():\n"
        "    return 2\n",
    )
    _write(
        backend,
        "tests/test_new.py",
        "def test_new(client):\n    client.get('/api/new')\n",
    )
    head = _commit(repo, "head")
    return repo, backend, base, head


def test_git_plan_unions_historical_and_current_route_contracts(
    tmp_path: Path,
) -> None:
    repo, backend, base, head = _route_repo(tmp_path)

    plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=base,
        head_ref=head,
    )

    assert plan.mode == "selected"
    assert plan.source_state == "commit"
    assert plan.selected_tests == ("tests/test_new.py", "tests/test_old.py")


def test_git_plan_rejects_a_head_other_than_the_checkout(tmp_path: Path) -> None:
    repo, backend, base, head = _route_repo(tmp_path)
    _git(repo, "checkout", "-q", base)

    plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=base,
        head_ref=head,
    )

    assert plan.mode == "full"
    assert "does not match checked-out HEAD" in plan.reasons[0]


def test_git_plan_requires_dirty_worktree_evidence_to_be_explicit(
    tmp_path: Path,
) -> None:
    repo, backend, base, head = _route_repo(tmp_path)
    _write(backend, "tests/test_new.py", "def test_new():\n    assert False\n")

    committed_plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=base,
        head_ref=head,
    )
    local_plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=base,
        head_ref=head,
        include_worktree=True,
    )

    assert committed_plan.mode == "full"
    assert "working tree changes" in committed_plan.reasons[0]
    assert local_plan.mode == "selected"
    assert local_plan.source_state == "worktree"


def test_git_plan_includes_untracked_tests_in_local_evidence(tmp_path: Path) -> None:
    repo, backend, base, head = _route_repo(tmp_path)
    _write(
        backend,
        "tests/test_untracked.py",
        "def test_untracked():\n    assert True\n",
    )

    plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=base,
        head_ref=head,
        include_worktree=True,
    )

    assert plan.mode == "selected"
    assert "tests/test_untracked.py" in plan.selected_tests


def test_git_plan_reports_both_sides_of_a_rename(tmp_path: Path) -> None:
    repo, backend, _base, head = _route_repo(tmp_path)
    _git(repo, "mv", "backend/tests/test_old.py", "backend/tests/test_renamed.py")
    renamed_head = _commit(repo, "rename test")

    plan = create_impact_plan(
        repo_root=repo,
        backend_root=backend,
        base_ref=head,
        head_ref=renamed_head,
    )

    assert plan.mode == "full"
    assert plan.changed_paths == (
        "backend/tests/test_old.py",
        "backend/tests/test_renamed.py",
    )
