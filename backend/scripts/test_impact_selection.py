"""Deterministic backend test-impact selection with a fail-closed full fallback."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import re
import subprocess
import tokenize
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PLAN_SCHEMA_VERSION = 1
_SOURCE_PREFIXES = ("app/", "scripts/", "tests/")
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
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
_IGNORED_BACKEND_PREFIXES = (
    "backend/build/",
    "backend/packaging/",
)
_MAX_SELECTED_TEST_RATIO = 0.70
_IMPORT_PROPAGATION_STOPS = frozenset({"app.database"})


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


class ImpactEvidenceError(RuntimeError):
    """Raised when Git or source evidence cannot support a partial selection."""


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


def _module_name(path: Path, backend_root: Path) -> str | None:
    try:
        relative = path.relative_to(backend_root)
    except ValueError:
        return None
    if relative.suffix != ".py" or relative.parts[0] not in {"app", "scripts", "tests"}:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _source_modules(backend_root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for prefix in _SOURCE_PREFIXES:
        source_root = backend_root / prefix.rstrip("/")
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.py"):
            module = _module_name(path, backend_root)
            if module:
                modules[module] = path
    return modules


def _read_python_source(path: Path) -> str:
    try:
        with tokenize.open(path) as stream:
            return stream.read()
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ImpactEvidenceError(f"cannot read Python source {path}: {exc}") from exc


def _import_base(node: ast.ImportFrom, *, importer: str, importer_path: Path) -> str | None:
    base = node.module or ""
    if not node.level:
        return base
    package = importer if importer_path.name == "__init__.py" else importer.rpartition(".")[0]
    try:
        return importlib.util.resolve_name("." * node.level + base, package)
    except (ImportError, ValueError):
        return None


def _package_exports(
    known_modules: Mapping[str, Path],
) -> dict[tuple[str, str], str]:
    exports: dict[tuple[str, str], str] = {}
    for package, path in known_modules.items():
        if path.name != "__init__.py":
            continue
        try:
            tree = ast.parse(_read_python_source(path), filename=str(path))
        except SyntaxError as exc:
            raise ImpactEvidenceError(f"cannot parse {path}: {exc}") from exc
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            base = _import_base(node, importer=package, importer_path=path)
            if not base:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                child_module = f"{base}.{alias.name}"
                target = child_module if child_module in known_modules else base
                if target in known_modules:
                    exports[(package, alias.asname or alias.name)] = target
    return exports


def _resolve_imported_modules(
    tree: ast.AST,
    *,
    importer: str,
    importer_path: Path,
    known_modules: Mapping[str, Path],
    package_exports: Mapping[tuple[str, str], str],
) -> set[str]:
    imported: set[str] = set()

    def add_candidate(candidate: str) -> None:
        if candidate in known_modules:
            imported.add(candidate)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add_candidate(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(node, importer=importer, importer_path=importer_path)
            if base is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    add_candidate(base)
                    continue
                exported_target = package_exports.get((base, alias.name))
                if exported_target is not None:
                    add_candidate(exported_target)
                    continue
                child_module = f"{base}.{alias.name}" if base else alias.name
                if child_module in known_modules:
                    add_candidate(child_module)
                else:
                    add_candidate(base)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            add_candidate(node.value)
    return imported


def _reverse_import_graph(backend_root: Path) -> tuple[dict[str, set[str]], dict[str, Path]]:
    modules = _source_modules(backend_root)
    package_exports = _package_exports(modules)
    reverse: dict[str, set[str]] = defaultdict(set)
    for importer, path in modules.items():
        try:
            tree = ast.parse(_read_python_source(path), filename=str(path))
        except SyntaxError as exc:
            raise ImpactEvidenceError(f"cannot parse {path}: {exc}") from exc
        for imported in _resolve_imported_modules(
            tree,
            importer=importer,
            importer_path=path,
            known_modules=modules,
            package_exports=package_exports,
        ):
            if importer == "app.main" and imported.startswith("app.routes."):
                continue
            reverse[imported].add(importer)
    return reverse, modules


def _reverse_closure(seeds: Iterable[str], reverse: Mapping[str, set[str]]) -> set[str]:
    affected = set(seeds)
    queue = deque(affected)
    while queue:
        affected_module = queue.popleft()
        if affected_module in _IMPORT_PROPAGATION_STOPS:
            continue
        for importer in reverse.get(affected_module, ()):
            if importer not in affected:
                affected.add(importer)
                queue.append(importer)
    return affected


def _literal_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def route_paths(path: Path) -> tuple[str, ...]:
    try:
        return route_paths_from_source(_read_python_source(path), label=str(path))
    except SyntaxError as exc:
        raise ImpactEvidenceError(f"cannot parse route module {path}: {exc}") from exc


def route_paths_from_source(source: str, *, label: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=label)
    prefixes: dict[str, str] = {}
    unresolved = False
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not (
            isinstance(value.func, ast.Name) and value.func.id == "APIRouter"
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        prefix_node = next((keyword.value for keyword in value.keywords if keyword.arg == "prefix"), None)
        prefix = _literal_string(prefix_node) if prefix_node is not None else ""
        if prefix is None:
            unresolved = True
            continue
        for name in names:
            prefixes[name] = prefix

    paths: set[str] = set()
    for node in ast.walk(tree):
        decorators = getattr(node, "decorator_list", ())
        for decorator in decorators:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            if decorator.func.attr not in _HTTP_METHODS or not isinstance(owner, ast.Name):
                continue
            if owner.id not in prefixes:
                unresolved = True
                continue
            path_node = decorator.args[0] if decorator.args else next(
                (keyword.value for keyword in decorator.keywords if keyword.arg in {"path", "url"}),
                None,
            )
            suffix = _literal_string(path_node)
            if suffix is None:
                unresolved = True
                continue
            paths.add(prefixes[owner.id] + suffix)
    if unresolved:
        raise ImpactEvidenceError(f"route paths in {label} are not all static literals")
    return tuple(sorted(paths))


def _test_target(path: Path, backend_root: Path) -> str:
    return path.relative_to(backend_root).as_posix()


def _modules_referencing_routes(
    route_patterns: Iterable[str],
    modules: Mapping[str, Path],
) -> set[str]:
    regexes = []
    for route_path in route_patterns:
        parts = re.split(r"\{[^}]+\}", route_path)
        regexes.append(re.compile(".+".join(re.escape(part) for part in parts)))
    selected: set[str] = set()
    for module, path in modules.items():
        if not module.startswith("tests."):
            continue
        text = _read_python_source(path)
        if any(regex.search(text) for regex in regexes):
            selected.add(module)
    return selected


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
    return path.startswith("backend/") or path.startswith((".github/workflows/", ".gitea/workflows/"))


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
    return relative if relative.startswith(_SOURCE_PREFIXES) else None


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
        return (), Selection("none", ("backend-packaging-only",), ())
    return tuple(source_changes), None


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

    reverse, modules = _reverse_import_graph(backend_root)
    modules_by_path = {path.resolve(): module for module, path in modules.items()}
    changed_modules: set[str] = set()
    selected: set[str] = set()
    for change, source_path in source_changes:
        path = (backend_root / source_path).resolve()
        module = modules_by_path.get(path)
        if module is None:
            return Selection("full", (f"unresolved-python-module:{change.path}",), ())
        changed_modules.add(module)
        if path.name.startswith("test_") and "tests" in path.relative_to(backend_root).parts[:1]:
            selected.add(_test_target(path, backend_root))

    affected = _reverse_closure(changed_modules, reverse)
    test_files = tuple(sorted((backend_root / "tests").rglob("test_*.py")))
    for module in affected:
        path = modules.get(module)
        if path is not None and path.name.startswith("test_") and path.is_relative_to(backend_root / "tests"):
            selected.add(_test_target(path, backend_root))

    affected_routes = [
        path
        for module, path in modules.items()
        if module in affected and module.startswith("app.routes.")
    ]
    route_patterns = set(historical_route_patterns)
    try:
        for path in affected_routes:
            route_patterns.update(route_paths(path))
        route_consumers = _reverse_closure(
            _modules_referencing_routes(route_patterns, modules),
            reverse,
        )
        for module in route_consumers:
            path = modules.get(module)
            if path is not None and path.name.startswith("test_") and path.is_relative_to(backend_root / "tests"):
                selected.add(_test_target(path, backend_root))
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
