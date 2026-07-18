from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import adr_contract_git as adr_git  # noqa: E402
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


def _init_feature_repo(root: Path) -> tuple[str, str]:
    stale = _init_repo(root)
    _git(root, "commit", "--allow-empty", "-qm", "default tip")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-qb", "feature")
    _git(root, "commit", "--allow-empty", "-qm", "feature")
    return stale, base


def test_ci_requires_explicit_exact_base(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    for environment in (
        {"CI": "1"},
        {"CI": "false"},
        {"GITHUB_BASE_REF": "main"},
    ):
        selected, error = select_ratchet_base(tmp_path, environment)

        assert selected is None
        assert error == "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit"


def test_explicit_sha_and_local_main_resolve_without_remote_guessing(tmp_path: Path) -> None:
    _, base = _init_feature_repo(tmp_path)

    explicit, error = select_ratchet_base(
        tmp_path,
        {"CI": "1", "XPJ_AUDIT_BASE_REF": base},
    )
    local, local_error = select_ratchet_base(tmp_path, {})

    assert error is None
    assert explicit is not None and explicit.commit == base
    assert local_error is None
    assert local is not None and local.commit == base


def _assert_pull_request_base_selection(tmp_path: Path, stale: str, base: str) -> None:
    stale_pr, stale_pr_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_BASE_REF": "main",
            "XPJ_AUDIT_BASE_REF": stale,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert stale_pr is None
    assert stale_pr_error is not None and "pull-request ADR ratchet base" in stale_pr_error

    exact_pr, exact_pr_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_BASE_REF": "main",
            "XPJ_AUDIT_BASE_REF": base,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert exact_pr_error is None
    assert exact_pr is not None and exact_pr.commit == base


def _create_synthetic_pr_merge(tmp_path: Path) -> tuple[str, str]:
    # actions/checkout's pull_request default is the synthetic merge ref. When
    # main advances after the feature branch was created, the event base SHA is
    # therefore both an ancestor of HEAD and the canonical divergence base.
    _git(tmp_path, "checkout", "-q", "main")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "advanced target tip")
    advanced_base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", "feature")
    previous_feature_head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "merge", "--no-ff", "-qm", "synthetic PR merge", "main")
    return advanced_base, previous_feature_head


def _assert_synthetic_merge_and_push_bases(
    tmp_path: Path,
    advanced_base: str,
    previous_feature_head: str,
) -> None:
    merge_checkout, merge_checkout_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_BASE_REF": "main",
            "XPJ_AUDIT_BASE_REF": advanced_base,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert merge_checkout_error is None
    assert merge_checkout is not None and merge_checkout.commit == advanced_base

    incremental_push, incremental_push_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/feature",
            "XPJ_AUDIT_BASE_REF": previous_feature_head,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert incremental_push is None
    assert incremental_push_error is not None
    assert "work-branch push ADR ratchet base" in incremental_push_error

    canonical_push, canonical_push_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/feature",
            "XPJ_AUDIT_BASE_REF": advanced_base,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert canonical_push_error is None
    assert canonical_push is not None and canonical_push.commit == advanced_base


def _assert_github_pr_checkout_contract() -> None:
    repo_root = SCRIPTS.parents[1]
    github_workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    gitea_workflow = (
        repo_root / ".gitea" / "workflows" / "windows-ci.yml"
    ).read_text(encoding="utf-8")
    assert "fetch-depth: 0" in github_workflow
    assert "github.event.pull_request.base.sha" in github_workflow
    assert "adr_base_ref" not in github_workflow
    assert "adr_base_ref" not in gitea_workflow
    checkout_step = github_workflow[
        github_workflow.index("      - name: Checkout\n") : github_workflow.index(
            "      - name: Check PowerShell scripts\n"
        )
    ]
    assert "ref:" not in checkout_step


def test_pull_request_requires_canonical_divergence_base(tmp_path: Path) -> None:
    stale, base = _init_feature_repo(tmp_path)
    _assert_pull_request_base_selection(tmp_path, stale, base)
    advanced_base, previous_feature_head = _create_synthetic_pr_merge(tmp_path)
    _assert_synthetic_merge_and_push_bases(
        tmp_path,
        advanced_base,
        previous_feature_head,
    )
    _assert_github_pr_checkout_contract()


def test_new_branch_push_uses_canonical_default_merge_base(tmp_path: Path) -> None:
    _, base = _init_feature_repo(tmp_path)

    branch_creation, branch_creation_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "push",
            "XPJ_AUDIT_BASE_REF": "0" * 40,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert branch_creation_error is None
    assert branch_creation is not None and branch_creation.commit == base
    assert branch_creation.ref == base
    assert _git(tmp_path, "rev-parse", f"{branch_creation.ref}^{{commit}}") == base
    _, bootstrap_errors = bootstrap_legacy_files(tmp_path, branch_creation.ref)
    assert bootstrap_errors == []


def test_manual_and_recreated_default_reject_noncanonical_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stale, base = _init_feature_repo(tmp_path)

    derived, derived_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert derived_error is None
    assert derived is not None and derived.commit == base

    manual, manual_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "XPJ_AUDIT_BASE_REF": stale,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert manual is None
    assert manual_error is not None and "canonical default-branch divergence base" in manual_error

    _git(tmp_path, "update-ref", "refs/heads/main", "HEAD")
    manual_main, manual_main_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "XPJ_AUDIT_BASE_REF": base,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert manual_main is None
    assert manual_main_error is not None and "no independent" in manual_main_error

    recreated_default, recreated_default_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "push",
            "XPJ_AUDIT_BASE_REF": "0" * 40,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert recreated_default is None
    assert recreated_default_error is not None
    assert "no independent pre-push authority" in recreated_default_error
    _git(tmp_path, "update-ref", "refs/heads/main", base)

    real_git_text = adr_git.git_text

    def multiple_merge_bases(repo_root: Path, arguments: list[str]) -> str | None:
        if arguments[:2] == ["merge-base", "--all"]:
            return "a" * 40 + "\n" + "b" * 40
        return real_git_text(repo_root, arguments)

    monkeypatch.setattr(adr_git, "git_text", multiple_merge_bases)
    selected, selection_error = adr_git._select_default_divergence_base(
        tmp_path,
        {"XPJ_AUDIT_DEFAULT_REF": "refs/heads/main"},
    )
    assert selected is None
    assert selection_error is not None and "not unique" in selection_error


def test_local_main_uses_parent_instead_of_comparing_head_with_itself(tmp_path: Path) -> None:
    base = _init_repo(tmp_path)
    _git(tmp_path, "commit", "--allow-empty", "-qm", "current")
    current = _git(tmp_path, "rev-parse", "HEAD")

    selected, error = select_ratchet_base(tmp_path, {})

    assert error is None
    assert selected is not None
    assert selected.ref == "HEAD^1"
    assert selected.commit == base

    _git(tmp_path, "update-ref", "refs/remotes/origin/main", current)
    (tmp_path / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    dirty_selected, dirty_error = select_ratchet_base(tmp_path, {})
    assert dirty_error is None
    assert dirty_selected is not None
    assert dirty_selected.ref == "HEAD"
    assert dirty_selected.commit == current

    _git(tmp_path, "commit", "--allow-empty", "-qm", "committed feature change")
    committed_head = _git(tmp_path, "rev-parse", "HEAD")
    committed_dirty_selected, committed_dirty_error = select_ratchet_base(tmp_path, {})
    assert committed_dirty_error is None
    assert committed_dirty_selected is not None
    assert committed_dirty_selected.ref == current
    assert committed_dirty_selected.commit == current

    configured_local, configured_local_error = select_ratchet_base(
        tmp_path,
        {"XPJ_AUDIT_DEFAULT_REF": "refs/heads/main"},
    )
    assert configured_local_error is None
    assert configured_local is not None
    assert configured_local.ref == "HEAD^1"
    assert configured_local.commit == current

    local_self, local_self_error = select_ratchet_base(
        tmp_path,
        {
            "XPJ_AUDIT_BASE_REF": committed_head,
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert local_self is None
    assert local_self_error is not None and "self-comparison is forbidden" in local_self_error

    self_base, self_error = select_ratchet_base(
        tmp_path,
        {
            "CI": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "XPJ_AUDIT_BASE_REF": "HEAD",
            "XPJ_AUDIT_DEFAULT_REF": "refs/heads/main",
        },
    )
    assert self_base is None
    assert self_error is not None and "self-comparison is forbidden" in self_error


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
