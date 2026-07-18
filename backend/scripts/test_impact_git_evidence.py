"""Fail-closed Git evidence for backend test-impact planning."""

from __future__ import annotations

import io
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts.test_impact_source_graph import (
    ImpactEvidenceError,
    route_paths_from_source,
)


@dataclass(frozen=True)
class GitChange:
    status: str
    path: str
    old_path: str | None = None


def _normalize_repo_path(raw_path: str) -> str:
    normalized = PurePosixPath(raw_path.replace("\\", "/")).as_posix()
    if normalized == "." or normalized.startswith("../") or normalized.startswith("/"):
        raise ImpactEvidenceError(f"invalid repository path: {raw_path!r}")
    return normalized


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactEvidenceError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _resolve_commit(repo_root: Path, ref: str) -> str:
    return _git_bytes(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def parse_name_status(raw: bytes) -> tuple[GitChange, ...]:
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    changes: list[GitChange] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        kind = status[:1]
        if kind in {"R", "C"}:
            if index + 1 >= len(fields):
                raise ImpactEvidenceError("git emitted an incomplete rename/copy record")
            old_path = _normalize_repo_path(fields[index])
            new_path = _normalize_repo_path(fields[index + 1])
            index += 2
            changes.append(GitChange(status=kind, path=new_path, old_path=old_path))
            continue
        if index >= len(fields):
            raise ImpactEvidenceError("git emitted an incomplete change record")
        changes.append(GitChange(status=kind, path=_normalize_repo_path(fields[index])))
        index += 1
    return tuple(changes)


def git_changes(
    repo_root: Path,
    base_ref: str,
    head_ref: str,
    *,
    include_worktree: bool,
) -> tuple[str, str, str, str, tuple[GitChange, ...]]:
    base_commit = _resolve_commit(repo_root, base_ref)
    head_commit = _resolve_commit(repo_root, head_ref)
    checkout_commit = _resolve_commit(repo_root, "HEAD")
    if head_commit != checkout_commit:
        raise ImpactEvidenceError(
            f"requested head {head_commit} does not match checked-out HEAD {checkout_commit}"
        )
    dirty = _git_bytes(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if dirty and not include_worktree:
        raise ImpactEvidenceError("working tree changes are not represented by the requested head ref")
    merge_base = _git_bytes(repo_root, "merge-base", base_commit, head_commit).decode().strip()
    changes = parse_name_status(
        _git_bytes(
            repo_root,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            merge_base,
            *(("HEAD",) if not include_worktree else ()),
        )
    )
    if include_worktree:
        known_paths = {change.path for change in changes}
        untracked = _git_bytes(
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ).decode("utf-8", errors="surrogateescape")
        additions = tuple(
            GitChange("A", path)
            for raw_path in untracked.split("\0")
            if raw_path
            and (path := _normalize_repo_path(raw_path)) not in known_paths
        )
        changes = (*changes, *additions)
    return (
        base_commit,
        head_commit,
        merge_base,
        "worktree" if include_worktree else "commit",
        changes,
    )


def _decode_python_bytes(raw: bytes, *, label: str) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return raw.decode(encoding)
    except (SyntaxError, UnicodeError) as exc:
        raise ImpactEvidenceError(f"cannot decode Python source {label}: {exc}") from exc


def historical_route_patterns(
    repo_root: Path,
    merge_base: str,
    changes: tuple[GitChange, ...],
) -> tuple[str, ...]:
    patterns: set[str] = set()
    for change in changes:
        if not (
            change.status == "M"
            and change.path.startswith("backend/app/routes/")
            and change.path.endswith(".py")
        ):
            continue
        label = f"{merge_base}:{change.path}"
        source = _decode_python_bytes(
            _git_bytes(repo_root, "show", label),
            label=label,
        )
        try:
            patterns.update(route_paths_from_source(source, label=label))
        except SyntaxError as exc:
            raise ImpactEvidenceError(
                f"cannot parse historical route module {label}: {exc}"
            ) from exc
    return tuple(sorted(patterns))
