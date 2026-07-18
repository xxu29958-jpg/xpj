"""Fail-closed Git access for ADR history and calibration ratchets."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADR_PATH_RE = re.compile(
    r"^docs/DECISIONS/(?P<id>\d{4})-(?:[a-z0-9]+(?:[.-][a-z0-9]+)*)\.md$"
)
CI_MARKERS = ("CI", "GITHUB_ACTIONS", "GITEA_ACTIONS", "GITHUB_SHA")
ZERO_OBJECT_ID_RE = re.compile(r"^0{40,64}$")


@dataclass(frozen=True)
class GitBase:
    ref: str
    commit: str


def select_ratchet_base(
    repo_root: Path, environ: dict[str, str]
) -> tuple[GitBase | None, str | None]:
    """Resolve an exact comparison base; never silently skip history checks."""

    explicit = environ.get("XPJ_AUDIT_BASE_REF", "").strip()
    if explicit:
        if ZERO_OBJECT_ID_RE.fullmatch(explicit):
            if environ.get("GITHUB_EVENT_NAME", "").strip() != "push":
                return None, "zero object ID is only valid for a new-branch push"
            return _select_default_divergence_base(
                repo_root,
                environ,
                reject_default_tip_at_head=True,
            )
        commit = git_text(repo_root, ["rev-parse", "--verify", f"{explicit}^{{commit}}"])
        if commit is None:
            return None, f"cannot resolve exact ADR ratchet base {explicit!r}"
        allow_dirty_head = (
            not has_auditable_ci_context(environ)
            and _local_dirty_head_is_trusted_default_tip(repo_root, environ, commit)
        )
        ancestry_error = _strict_ancestor_error(
            repo_root,
            commit,
            allow_dirty_head=allow_dirty_head,
        )
        if ancestry_error is not None:
            return None, ancestry_error
        event_name = environ.get("GITHUB_EVENT_NAME", "").strip()
        require_canonical = event_name == "workflow_dispatch" or (
            event_name == "push" and _is_non_default_branch_push(environ)
        )
        if require_canonical:
            canonical, canonical_error = _select_default_divergence_base(repo_root, environ)
            if canonical is None:
                return None, canonical_error
            if commit != canonical.commit:
                context = {
                    "workflow_dispatch": "manual",
                }.get(event_name, "work-branch push")
                return None, (
                    f"{context} ADR ratchet base must equal the canonical default-branch "
                    f"divergence base {canonical.commit}, got {commit}"
                )
        return GitBase(ref=explicit, commit=commit), None
    if environ.get("GITHUB_EVENT_NAME", "").strip() == "workflow_dispatch":
        return _select_default_divergence_base(repo_root, environ)
    if has_auditable_ci_context(environ):
        return None, "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit"

    return _select_default_divergence_base(repo_root, environ)


def has_auditable_ci_context(environ: dict[str, str]) -> bool:
    """Return whether environment presence makes an exact base mandatory."""

    return bool(
        environ.get("GITHUB_EVENT_NAME", "").strip()
        or environ.get("GITHUB_BASE_REF", "").strip()
        or any(environ.get(marker, "").strip() for marker in CI_MARKERS)
    )


def _is_non_default_branch_push(environ: dict[str, str]) -> bool:
    github_ref = environ.get("GITHUB_REF", "").strip()
    if not github_ref.startswith("refs/heads/"):
        return False
    default_ref = environ.get(
        "XPJ_AUDIT_DEFAULT_REF", "refs/remotes/origin/main"
    ).strip()
    default_branch = default_ref.rstrip("/").rsplit("/", 1)[-1]
    return github_ref != f"refs/heads/{default_branch}"


def _strict_ancestor_error(
    repo_root: Path,
    commit: str,
    *,
    allow_dirty_head: bool = False,
) -> str | None:
    head = git_text(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"])
    if head is None:
        return "cannot resolve current HEAD for ADR ratchet ancestry"
    if commit == head:
        if allow_dirty_head:
            dirty = git_text(repo_root, ["status", "--porcelain", "--untracked-files=all"])
            if dirty:
                return None
        return "ADR ratchet base resolves to current HEAD; self-comparison is forbidden"
    if not git_succeeds(repo_root, ["merge-base", "--is-ancestor", commit, head]):
        return f"ADR ratchet base {commit} is not an ancestor of current HEAD {head}"
    return None


def _default_ref_candidates(environ: dict[str, str]) -> tuple[str, ...]:
    candidates: list[str] = []
    configured = environ.get("XPJ_AUDIT_DEFAULT_REF", "").strip()
    if configured:
        candidates.append(configured)
    base_branch = environ.get("GITHUB_BASE_REF", "").strip()
    if base_branch:
        candidates.append(base_branch if "/" in base_branch else f"refs/remotes/origin/{base_branch}")
    candidates.extend(("refs/remotes/origin/main", "refs/heads/main"))
    return tuple(dict.fromkeys(candidates))


def _candidate_can_anchor_dirty_head(candidate: str, environ: dict[str, str]) -> bool:
    del environ
    return candidate.startswith("refs/remotes/")


def _worktree_is_dirty(repo_root: Path) -> bool:
    return bool(git_text(repo_root, ["status", "--porcelain", "--untracked-files=all"]))


def _local_dirty_head_is_trusted_default_tip(
    repo_root: Path,
    environ: dict[str, str],
    head: str,
) -> bool:
    if not _worktree_is_dirty(repo_root):
        return False
    for candidate in _default_ref_candidates(environ):
        tip = git_text(repo_root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
        if tip is None:
            continue
        return tip == head and _candidate_can_anchor_dirty_head(candidate, environ)
    return False


def _select_default_divergence_base(
    repo_root: Path,
    environ: dict[str, str],
    *,
    reject_default_tip_at_head: bool = False,
) -> tuple[GitBase | None, str | None]:
    head = git_text(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"])
    if head is None:
        return None, "cannot resolve current HEAD for ADR ratchet base selection"
    for candidate in _default_ref_candidates(environ):
        tip = git_text(repo_root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
        if tip is None:
            continue
        if tip == head:
            if reject_default_tip_at_head:
                return None, (
                    "zero-before push has no independent pre-push authority: "
                    f"trusted default ref {candidate!r} already resolves to current HEAD"
                )
            if (
                not has_auditable_ci_context(environ)
                and _candidate_can_anchor_dirty_head(candidate, environ)
                and _worktree_is_dirty(repo_root)
            ):
                return GitBase(ref="HEAD", commit=head), None
            if has_auditable_ci_context(environ):
                return None, (
                    "automated audit has no independent default-branch divergence base: "
                    f"trusted default ref {candidate!r} already resolves to current HEAD"
                )
            parent = git_text(repo_root, ["rev-parse", "--verify", "HEAD^1^{commit}"])
            if parent is not None:
                return GitBase(ref="HEAD^1", commit=parent), None
            continue
        merge_bases_text = git_text(repo_root, ["merge-base", "--all", head, tip])
        if merge_bases_text is None:
            continue
        merge_bases = tuple(line for line in merge_bases_text.splitlines() if line)
        if len(merge_bases) != 1:
            return None, (
                "canonical default-branch divergence base is not unique: "
                f"found {len(merge_bases)} merge bases"
            )
        base = merge_bases[0]
        ancestry_error = _strict_ancestor_error(repo_root, base)
        if ancestry_error is None:
            # Consumers pass ``ref`` directly to git show/ls-tree.  Keep the
            # provenance label out of that executable field and return the
            # already-resolved immutable commit itself.
            return GitBase(ref=base, commit=base), None
    return None, "cannot resolve a strict default-branch divergence base"


def git_text(repo_root: Path, arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_succeeds(repo_root: Path, arguments: list[str]) -> bool:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def git_bytes(repo_root: Path, arguments: list[str]) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_json(repo_root: Path, ref: str, path: str) -> dict[str, Any] | None:
    content = git_text(repo_root, ["show", f"{ref}:{path}"])
    if content is None:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ADR ratchet base file {path} is malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"ADR ratchet base file {path} root must be an object")
    return parsed


def commit_is_ancestor(repo_root: Path, commit: str) -> bool:
    return git_succeeds(repo_root, ["merge-base", "--is-ancestor", commit, "HEAD"])


def bootstrap_legacy_files(
    repo_root: Path, ref: str
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Return every non-v2 ADR blob that actually exists at the exact base."""

    listing = git_text(
        repo_root,
        ["ls-tree", "-r", "--name-only", ref, "--", "docs/DECISIONS"],
    )
    if listing is None:
        return {}, [f"cannot list ADRs at bootstrap base {ref!r}"]
    result: dict[str, tuple[str, str]] = {}
    errors: list[str] = []
    for path in listing.splitlines():
        match = ADR_PATH_RE.fullmatch(path)
        if match is None:
            continue
        content = git_bytes(repo_root, ["show", f"{ref}:{path}"])
        if content is None:
            errors.append(f"cannot read {path} at bootstrap base")
            continue
        if content.replace(b"\r\n", b"\n").startswith(b"+++\n"):
            continue
        adr_id = match.group("id")
        if adr_id in result:
            errors.append(f"bootstrap base repeats ADR-{adr_id}")
            continue
        result[adr_id] = (path, hashlib.sha256(content).hexdigest())
    return result, errors
