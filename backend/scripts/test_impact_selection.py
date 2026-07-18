"""Deterministic backend test-impact selection with a fail-closed full fallback."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.test_impact_git_evidence import (
    GitChange,
    git_changes,
    historical_route_patterns,
)
from scripts.test_impact_python_graph import (
    SOURCE_PREFIXES,
    ImpactEvidenceError,
    reverse_closure,
    reverse_import_graph,
)
from scripts.test_impact_source_graph import (
    modules_declaring_path_dependencies,
    modules_referencing_routes,
    pytest_fixture_boundaries,
    route_paths,
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
_MAX_SELECTED_TEST_RATIO = 0.70


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


def _test_target(path: Path, backend_root: Path) -> str:
    return path.relative_to(backend_root).as_posix()


def _is_pytest_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def _full_fallback_reason(changes: Sequence[GitChange]) -> str | None:
    for change in changes:
        candidates = tuple(path for path in (change.old_path, change.path) if path)
        if change.status not in {"A", "M"}:
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
        source_path = _python_source_path(change.path)
        if source_path is None:
            return (), Selection(
                "full",
                (f"unclassified-repository-change:{change.path}",),
                (),
            )
        source_changes.append((change, source_path))
    if not source_changes:
        return (), Selection("full", ("repository-change-classification-empty",), ())
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
        and _is_pytest_file(path)
        and path.is_relative_to(tests_root)
    }


def _route_impacted_modules(
    *,
    affected: set[str],
    reverse: dict[str, set[str]],
    modules: dict[str, Path],
    historical_route_patterns: Iterable[str],
) -> tuple[set[str], int]:
    affected_routes = [
        path
        for module, path in modules.items()
        if module in affected and module.startswith("app.routes.")
    ]
    route_patterns = set(historical_route_patterns)
    for path in affected_routes:
        route_patterns.update(route_paths(path))
    route_consumers = reverse_closure(
        modules_referencing_routes(route_patterns, modules),
        reverse,
    )
    if affected_routes:
        route_consumers.update(reverse_closure({"app.main"}, reverse))
    return route_consumers, len(affected_routes)


def _declared_dependency_modules(
    changes: Sequence[GitChange],
    reverse: dict[str, set[str]],
    modules: dict[str, Path],
) -> set[str]:
    consumers = modules_declaring_path_dependencies(
        (
            path
            for change in changes
            for path in (change.path, change.old_path)
            if path is not None
        ),
        modules,
    )
    return reverse_closure(consumers, reverse)


def _changed_module_evidence(
    source_changes: Sequence[tuple[GitChange, str]],
    modules: dict[str, Path],
    backend_root: Path,
) -> tuple[set[str], set[str]]:
    modules_by_path = {path.resolve(): module for module, path in modules.items()}
    changed_modules: set[str] = set()
    changed_tests: set[str] = set()
    for change, source_path in source_changes:
        path = (backend_root / source_path).resolve()
        module = modules_by_path.get(path)
        if module is None:
            raise ImpactEvidenceError(f"unresolved-python-module:{change.path}")
        changed_modules.add(module)
        if _is_pytest_file(path) and path.is_relative_to(
            backend_root / "tests"
        ):
            changed_tests.add(_test_target(path, backend_root))
    return changed_modules, changed_tests


def _bounded_selection(
    *,
    selected: set[str],
    test_file_count: int,
    source_changes: Sequence[tuple[GitChange, str]],
    changed_module_count: int,
    affected_route_count: int,
) -> Selection:
    if not selected:
        changed = ",".join(sorted(change.path for change, _ in source_changes)[:3])
        return Selection("full", (f"no-test-dependency-proof:{changed}",), ())
    if len(selected) / max(test_file_count, 1) > _MAX_SELECTED_TEST_RATIO:
        return Selection(
            "full",
            (f"selection-too-broad:{len(selected)}/{test_file_count}",),
            (),
        )
    return Selection(
        "selected",
        (
            f"static-import-closure:{changed_module_count}-module(s)",
            f"route-literal-closure:{affected_route_count}-module(s)",
        ),
        tuple(sorted(selected)),
    )


def select_impacted_tests(
    backend_root: Path,
    changes: Sequence[GitChange],
    *,
    historical_route_patterns: Iterable[str] = (),
) -> Selection:
    relevant = tuple(changes)
    if not relevant:
        return Selection("none", ("no-repository-changes",), ())
    fallback = _full_fallback_reason(relevant)
    if fallback:
        return Selection("full", (fallback,), ())

    source_changes, classified = _classify_source_changes(relevant)
    if classified is not None:
        return classified

    try:
        reverse, modules = reverse_import_graph(backend_root)
    except ImpactEvidenceError as exc:
        return Selection("full", (f"python-import-impact-unproven:{exc}",), ())
    evidence_modules = _declared_dependency_modules(
        relevant,
        reverse,
        modules,
    )
    try:
        changed_modules, changed_tests = _changed_module_evidence(
            source_changes,
            modules,
            backend_root,
        )
    except ImpactEvidenceError as exc:
        return Selection("full", (str(exc),), ())
    affected = reverse_closure(changed_modules, reverse)
    evidence_modules.update(affected)

    try:
        route_modules, affected_route_count = _route_impacted_modules(
            affected=affected,
            reverse=reverse,
            modules=modules,
            historical_route_patterns=historical_route_patterns,
        )
        evidence_modules.update(route_modules)
    except ImpactEvidenceError as exc:
        return Selection("full", (f"route-impact-unproven:{exc}",), ())

    fixture_boundaries = pytest_fixture_boundaries(evidence_modules, modules)
    if fixture_boundaries:
        return Selection(
            "full",
            (f"pytest-fixture-closure-unproven:{fixture_boundaries[0]}",),
            (),
        )
    selected = set(changed_tests)
    selected.update(
        _test_targets_for_modules(
            evidence_modules,
            modules,
            backend_root,
        )
    )
    return _bounded_selection(
        selected=selected,
        test_file_count=sum(
            1
            for path in (backend_root / "tests").rglob("*.py")
            if _is_pytest_file(path)
        ),
        source_changes=source_changes,
        changed_module_count=len(changed_modules),
        affected_route_count=affected_route_count,
    )


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
            historical_route_patterns=historical_route_patterns(
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
            changed_paths=tuple(
                sorted(
                    {
                        path
                        for change in changes
                        for path in (change.old_path, change.path)
                        if path is not None
                    }
                )
            ),
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
