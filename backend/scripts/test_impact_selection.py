"""Deterministic backend test-impact selection with a fail-closed full fallback."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tokenize
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from scripts.test_impact_source_graph import (
    SOURCE_PREFIXES,
    ImpactEvidenceError,
    modules_declaring_path_dependencies,
    modules_referencing_routes,
    reverse_closure,
    reverse_import_graph,
    route_paths,
    route_paths_from_source,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PLAN_SCHEMA_VERSION = 1
_FULL_FALLBACK_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        ".gitea/workflows/windows-ci.yml",
        "backend/pyproject.toml",
        "backend/requirements.txt",
        "backend/requirements-dev.txt",
        "backend/tests/conftest.py",
        "backend/app/config.py",
        "backend/app/database.py",
        "backend/app/main.py",
        "backend/app/models/__init__.py",
        "backend/scripts/pytest_execution_contract.py",
        "backend/scripts/pytest_marker_contract.py",
        "backend/scripts/run_test_lanes.py",
        "backend/scripts/test_impact_selection.py",
        "backend/scripts/test_pg_contract.py",
    }
)
_FULL_FALLBACK_PREFIXES = (
    "backend/alembic/",
    "backend/app/database/",
    "backend/app/models/",
    "backend/scripts/",
    "backend/tests/_infra/",
)
_IGNORED_BACKEND_PREFIXES = ("backend/build/",)
_CROSS_REPO_BACKEND_CONTRACT_PREFIXES = ("android/", "desktop/", "scripts/")
_MAX_SELECTED_TEST_RATIO = 0.70


@dataclass(frozen=True)
class GitChange:
    status: str
    path: str
    old_path: str | None = None


@dataclass(frozen=True)
class ImpactPlan:
    schema_version: int
    source_state: str
    base_commit: str | None
    head_commit: str | None
    merge_base: str | None
    mode: str
    reasons: tuple[str, ...]
    changed_paths: tuple[str, ...]
    selected_tests: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class Selection:
    mode: str
    reasons: tuple[str, ...]
    selected_tests: tuple[str, ...]


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


def _parse_name_status(raw: bytes) -> tuple[GitChange, ...]:
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
    changes = _parse_name_status(
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
            if raw_path and (path := _normalize_repo_path(raw_path)) not in known_paths
        )
        changes = (*changes, *additions)
    return (
        base_commit,
        head_commit,
        merge_base,
        "worktree" if include_worktree else "commit",
        changes,
    )


def _test_target(path: Path, backend_root: Path) -> str:
    return path.relative_to(backend_root).as_posix()


def _full_fallback_reason(changes: Sequence[GitChange]) -> str | None:
    for change in changes:
        candidates = tuple(path for path in (change.old_path, change.path) if path)
        if change.status not in {"A", "M"} and any(_is_backend_relevant(path) for path in candidates):
            return f"destructive-or-relocated-path:{change.status}:{change.path}"
        for path in candidates:
            if path in _FULL_FALLBACK_PATHS or path.startswith(_FULL_FALLBACK_PREFIXES):
                return f"shared-test-contract:{path}"
            if path.startswith("backend/app/") and path.endswith("/__init__.py"):
                return f"package-facade:{path}"
            if path.startswith((".github/workflows/", ".gitea/workflows/")):
                return f"ci-contract:{path}"
            if path.startswith("backend/") and path.endswith((".toml", ".ini", ".cfg", ".lock")):
                return f"backend-config:{path}"
    return None


def _is_backend_relevant(path: str) -> bool:
    return path.startswith(
        (
            "backend/",
            *_CROSS_REPO_BACKEND_CONTRACT_PREFIXES,
            ".github/workflows/",
            ".gitea/workflows/",
        )
    )


def _relevant_changes(changes: Sequence[GitChange]) -> tuple[GitChange, ...]:
    return tuple(
        change
        for change in changes
        if any(_is_backend_relevant(path) for path in (change.path, change.old_path) if path)
    )


def _python_source_path(change_path: str) -> str | None:
    if not change_path.startswith("backend/") or not change_path.endswith(".py"):
        return None
    relative = change_path.removeprefix("backend/")
    return relative if relative.startswith(SOURCE_PREFIXES) else None


def _classify_source_changes(
    changes: Sequence[GitChange],
) -> tuple[tuple[tuple[GitChange, str], ...], Selection | None]:
    source_changes: list[tuple[GitChange, str]] = []
    for change in changes:
        if change.path.startswith(_IGNORED_BACKEND_PREFIXES):
            continue
        source_path = _python_source_path(change.path)
        if source_path is None:
            return (), Selection("full", (f"unclassified-backend-change:{change.path}",), ())
        source_changes.append((change, source_path))
    if not source_changes:
        return (), Selection("none", ("generated-backend-output-only",), ())
    return tuple(source_changes), None


def _test_targets_for_modules(
    module_names: Iterable[str],
    modules: dict[str, Path],
    backend_root: Path,
) -> set[str]:
    tests_root = backend_root / "tests"
    return {
        _test_target(path, backend_root)
        for module in module_names
        if (path := modules.get(module)) is not None
        and path.name.startswith("test_")
        and path.is_relative_to(tests_root)
    }


def select_impacted_tests(
    backend_root: Path,
    changes: Sequence[GitChange],
    *,
    historical_route_patterns: Iterable[str] = (),
) -> Selection:
    relevant = _relevant_changes(changes)
    if not relevant:
        return Selection("none", ("no-backend-test-impact",), ())
    fallback = _full_fallback_reason(relevant)
    if fallback:
        return Selection("full", (fallback,), ())

    source_changes, classified = _classify_source_changes(relevant)
    if classified is not None:
        return classified

    reverse, modules = reverse_import_graph(backend_root)
    modules_by_path = {path.resolve(): module for module, path in modules.items()}
    changed_modules: set[str] = set()
    selected: set[str] = set()
    declared_consumers = modules_declaring_path_dependencies(
        (
            path
            for change in relevant
            for path in (change.path, change.old_path)
            if path is not None
        ),
        modules,
    )
    selected.update(
        _test_targets_for_modules(declared_consumers, modules, backend_root)
    )
    for change, source_path in source_changes:
        path = (backend_root / source_path).resolve()
        module = modules_by_path.get(path)
        if module is None:
            return Selection("full", (f"unresolved-python-module:{change.path}",), ())
        changed_modules.add(module)
        if path.name.startswith("test_") and "tests" in path.relative_to(backend_root).parts[:1]:
            selected.add(_test_target(path, backend_root))

    affected = reverse_closure(changed_modules, reverse)
    test_files = tuple(sorted((backend_root / "tests").rglob("test_*.py")))
    selected.update(_test_targets_for_modules(affected, modules, backend_root))

    affected_routes = [
        path
        for module, path in modules.items()
        if module in affected and module.startswith("app.routes.")
    ]
    route_patterns = set(historical_route_patterns)
    try:
        for path in affected_routes:
            route_patterns.update(route_paths(path))
        route_consumers = reverse_closure(
            modules_referencing_routes(route_patterns, modules),
            reverse,
        )
        selected.update(
            _test_targets_for_modules(route_consumers, modules, backend_root)
        )
        if affected_routes:
            selected.update(
                _test_targets_for_modules(
                    reverse_closure({"app.main"}, reverse),
                    modules,
                    backend_root,
                )
            )
    except ImpactEvidenceError as exc:
        return Selection("full", (f"route-impact-unproven:{exc}",), ())

    if not selected:
        changed = ",".join(sorted(change.path for change, _ in source_changes)[:3])
        return Selection("full", (f"no-test-dependency-proof:{changed}",), ())
    if len(selected) / max(len(test_files), 1) > _MAX_SELECTED_TEST_RATIO:
        return Selection(
            "full",
            (f"selection-too-broad:{len(selected)}/{len(test_files)}",),
            (),
        )
    return Selection(
        "selected",
        (
            f"static-import-closure:{len(changed_modules)}-module(s)",
            f"route-literal-closure:{len(affected_routes)}-module(s)",
        ),
        tuple(sorted(selected)),
    )


def _decode_python_bytes(raw: bytes, *, label: str) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        return raw.decode(encoding)
    except (SyntaxError, UnicodeError) as exc:
        raise ImpactEvidenceError(f"cannot decode Python source {label}: {exc}") from exc


def _historical_route_patterns(
    repo_root: Path,
    merge_base: str,
    changes: Sequence[GitChange],
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
            raise ImpactEvidenceError(f"cannot parse historical route module {label}: {exc}") from exc
    return tuple(sorted(patterns))


def create_impact_plan(
    *,
    repo_root: Path = REPO_ROOT,
    backend_root: Path = BACKEND_ROOT,
    base_ref: str,
    head_ref: str,
    include_worktree: bool = False,
) -> ImpactPlan:
    try:
        base_commit, head_commit, merge_base, source_state, changes = git_changes(
            repo_root,
            base_ref,
            head_ref,
            include_worktree=include_worktree,
        )
        selection = select_impacted_tests(
            backend_root,
            changes,
            historical_route_patterns=_historical_route_patterns(
                repo_root,
                merge_base,
                changes,
            ),
        )
        return ImpactPlan(
            schema_version=PLAN_SCHEMA_VERSION,
            source_state=source_state,
            base_commit=base_commit,
            head_commit=head_commit,
            merge_base=merge_base,
            mode=selection.mode,
            reasons=selection.reasons,
            changed_paths=tuple(sorted({change.path for change in changes})),
            selected_tests=selection.selected_tests,
        )
    except ImpactEvidenceError as exc:
        return ImpactPlan(
            schema_version=PLAN_SCHEMA_VERSION,
            source_state="unverified",
            base_commit=None,
            head_commit=None,
            merge_base=None,
            mode="full",
            reasons=(f"impact-evidence-unavailable:{exc}",),
            changed_paths=(),
            selected_tests=(),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument(
        "--include-worktree",
        action="store_true",
        help="local-only: include staged, unstaged, and untracked changes",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    plan = create_impact_plan(
        base_ref=arguments.base_ref,
        head_ref=arguments.head_ref,
        include_worktree=arguments.include_worktree,
    )
    payload = plan.to_json()
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
