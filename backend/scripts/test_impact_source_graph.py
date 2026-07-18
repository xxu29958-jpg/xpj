"""Static Python import and route evidence for test-impact selection."""

from __future__ import annotations

import ast
import importlib.util
import re
import tokenize
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from pathlib import Path

SOURCE_PREFIXES = ("app/", "scripts/", "tests/")
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_IMPORT_PROPAGATION_STOPS = frozenset({"app.database"})


class ImpactEvidenceError(RuntimeError):
    """Raised when source evidence cannot support a partial selection."""


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
    for prefix in SOURCE_PREFIXES:
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


def _import_base(
    node: ast.ImportFrom,
    *,
    importer: str,
    importer_path: Path,
) -> str | None:
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
                child_module = f"{base}.{alias.name}"
                target = child_module if child_module in known_modules else base
                if alias.name != "*" and target in known_modules:
                    exports[(package, alias.asname or alias.name)] = target
    return exports


def _from_import_targets(
    node: ast.ImportFrom,
    *,
    importer: str,
    importer_path: Path,
    known_modules: Mapping[str, Path],
    package_exports: Mapping[tuple[str, str], str],
) -> set[str]:
    base = _import_base(node, importer=importer, importer_path=importer_path)
    if base is None:
        return set()
    imported: set[str] = set()
    for alias in node.names:
        if alias.name == "*":
            if base in known_modules:
                imported.add(base)
            continue
        exported_target = package_exports.get((base, alias.name))
        child_module = f"{base}.{alias.name}" if base else alias.name
        candidate = exported_target or (
            child_module if child_module in known_modules else base
        )
        if candidate in known_modules:
            imported.add(candidate)
    return imported


def _resolve_imported_modules(
    tree: ast.AST,
    *,
    importer: str,
    importer_path: Path,
    known_modules: Mapping[str, Path],
    package_exports: Mapping[tuple[str, str], str],
) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(
                alias.name for alias in node.names if alias.name in known_modules
            )
        elif isinstance(node, ast.ImportFrom):
            imported.update(
                _from_import_targets(
                    node,
                    importer=importer,
                    importer_path=importer_path,
                    known_modules=known_modules,
                    package_exports=package_exports,
                )
            )
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in known_modules
        ):
            imported.add(node.value)
    return imported


def reverse_import_graph(
    backend_root: Path,
) -> tuple[dict[str, set[str]], dict[str, Path]]:
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
            if importer != "app.main" or not imported.startswith("app.routes."):
                reverse[imported].add(importer)
    return reverse, modules


def reverse_closure(
    seeds: Iterable[str],
    reverse: Mapping[str, set[str]],
) -> set[str]:
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
    prefixes, unresolved_prefix = _router_prefixes(tree)
    paths, unresolved_path = _decorated_route_paths(tree, prefixes)
    if unresolved_prefix or unresolved_path:
        raise ImpactEvidenceError(f"route paths in {label} are not all static literals")
    return tuple(sorted(paths))


def _router_prefixes(tree: ast.Module) -> tuple[dict[str, str], bool]:
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
        prefix_node = next(
            (keyword.value for keyword in value.keywords if keyword.arg == "prefix"),
            None,
        )
        prefix = _literal_string(prefix_node) if prefix_node is not None else ""
        if prefix is None:
            unresolved = True
            continue
        for name in names:
            prefixes[name] = prefix
    return prefixes, unresolved


def _decorated_route_paths(
    tree: ast.Module,
    prefixes: Mapping[str, str],
) -> tuple[set[str], bool]:
    paths: set[str] = set()
    unresolved = False
    for node in ast.walk(tree):
        for decorator in getattr(node, "decorator_list", ()):
            resolved = _decorator_route_path(decorator, prefixes)
            if resolved is False:
                unresolved = True
            elif isinstance(resolved, str):
                paths.add(resolved)
    return paths, unresolved


def _decorator_route_path(
    decorator: ast.AST,
    prefixes: Mapping[str, str],
) -> str | bool | None:
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    owner = decorator.func.value
    if decorator.func.attr not in _HTTP_METHODS or not isinstance(owner, ast.Name):
        return None
    if owner.id not in prefixes:
        return False
    path_node = decorator.args[0] if decorator.args else next(
        (
            keyword.value
            for keyword in decorator.keywords
            if keyword.arg in {"path", "url"}
        ),
        None,
    )
    suffix = _literal_string(path_node)
    return False if suffix is None else prefixes[owner.id] + suffix


def modules_referencing_routes(
    route_patterns: Iterable[str],
    modules: Mapping[str, Path],
) -> set[str]:
    regexes = []
    for route_path in route_patterns:
        parts = re.split(r"\{[^}]+\}", route_path)
        regexes.append(re.compile(".+".join(re.escape(part) for part in parts)))
    selected: set[str] = set()
    for module, path in modules.items():
        if module.startswith("tests."):
            text = _read_python_source(path)
            if any(regex.search(text) for regex in regexes):
                selected.add(module)
    return selected
