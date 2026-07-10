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
        commit = git_text(repo_root, ["rev-parse", "--verify", f"{explicit}^{{commit}}"])
        if commit is None:
            return None, f"cannot resolve exact ADR ratchet base {explicit!r}"
        return GitBase(ref=explicit, commit=commit), None
    if any(environ.get(marker) for marker in CI_MARKERS):
        return None, "CI requires XPJ_AUDIT_BASE_REF with the exact pre-change commit"

    head = git_text(repo_root, ["rev-parse", "--verify", "HEAD^{commit}"])
    for candidate in ("refs/heads/main", "refs/remotes/origin/main"):
        commit = git_text(repo_root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
        if commit is None:
            continue
        if commit == head:
            parent = git_text(repo_root, ["rev-parse", "--verify", "HEAD^1^{commit}"])
            if parent is not None:
                return GitBase(ref="HEAD^1", commit=parent), None
        return GitBase(ref=candidate, commit=commit), None
    return None, "cannot resolve local ADR ratchet base from main or origin/main"


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
    return git_text(repo_root, ["merge-base", "--is-ancestor", commit, "HEAD"]) is not None


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
