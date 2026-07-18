"""Static Python import and route evidence for test-impact selection."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from scripts.test_impact_python_graph import ImpactEvidenceError, read_python_source

_ROUTE_DECORATOR_METHODS = frozenset(
    {
        "api_route",
        "delete",
        "get",
        "head",
        "options",
        "patch",
        "post",
        "put",
        "websocket",
        "websocket_route",
    }
)
_DIRECT_ROUTE_REGISTRATION_METHODS = frozenset(
    {
        "add_api_route",
        "add_api_websocket_route",
        "add_route",
        "add_websocket_route",
    }
)
_UNMODELED_ROUTE_REGISTRATION_METHODS = frozenset({"include_router", "mount"})
_UNMODELED_ROUTE_CONSTRUCTORS = frozenset({"Mount", "Route", "WebSocketRoute"})


def modules_declaring_path_dependencies(
    changed_paths: Iterable[str],
    modules: Mapping[str, Path],
) -> set[str]:
    changed = tuple(changed_paths)
    selected: set[str] = set()
    for module, path in modules.items():
        try:
            tree = ast.parse(read_python_source(path), filename=str(path))
        except SyntaxError as exc:
            raise ImpactEvidenceError(f"cannot parse {path}: {exc}") from exc
        prefixes = _declared_path_dependencies(tree)
        if any(path.startswith(prefix) for path in changed for prefix in prefixes):
            selected.add(module)
    return selected


def _declared_path_dependencies(tree: ast.Module) -> tuple[str, ...]:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name)
            and target.id == "TEST_IMPACT_SOURCE_PREFIXES"
            for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            raise ImpactEvidenceError(
                "TEST_IMPACT_SOURCE_PREFIXES must be a literal tuple or list"
            )
        prefixes = tuple(_literal_string(item) for item in value.elts)
        if any(prefix is None or not prefix for prefix in prefixes):
            raise ImpactEvidenceError(
                "TEST_IMPACT_SOURCE_PREFIXES must contain non-empty string literals"
            )
        return tuple(prefix for prefix in prefixes if prefix is not None)
    return ()


def _literal_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def route_paths(path: Path) -> tuple[str, ...]:
    try:
        return route_paths_from_source(read_python_source(path), label=str(path))
    except SyntaxError as exc:
        raise ImpactEvidenceError(f"cannot parse route module {path}: {exc}") from exc


def route_paths_from_source(source: str, *, label: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=label)
    if _has_unmodeled_route_registration(tree):
        raise ImpactEvidenceError(
            f"route topology in {label} uses an unsupported registration form"
        )
    prefixes, unresolved_prefix = _router_prefixes(tree)
    decorated, unresolved_decorator = _decorated_route_paths(tree, prefixes)
    registered, unresolved_registration = _registered_route_paths(tree, prefixes)
    if unresolved_prefix or unresolved_decorator or unresolved_registration:
        raise ImpactEvidenceError(f"route paths in {label} are not all static literals")
    return tuple(sorted(decorated | registered))


def _has_unmodeled_route_registration(tree: ast.Module) -> bool:
    constructor_names = set(_UNMODELED_ROUTE_CONSTRUCTORS)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module not in {
            "fastapi.routing",
            "starlette.routing",
        }:
            continue
        constructor_names.update(
            alias.asname or alias.name
            for alias in node.names
            if alias.name in _UNMODELED_ROUTE_CONSTRUCTORS
        )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _UNMODELED_ROUTE_REGISTRATION_METHODS
        ):
            return True
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in constructor_names
        ):
            return True
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _UNMODELED_ROUTE_CONSTRUCTORS
        ):
            return True
    return False


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
    if not isinstance(owner, ast.Name):
        return None
    if owner.id in prefixes and decorator.func.attr not in _ROUTE_DECORATOR_METHODS:
        return False
    if decorator.func.attr not in _ROUTE_DECORATOR_METHODS:
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


def _registered_route_paths(
    tree: ast.Module,
    prefixes: Mapping[str, str],
) -> tuple[set[str], bool]:
    paths: set[str] = set()
    unresolved = False
    for node in ast.walk(tree):
        resolved = _registered_route_path(node, prefixes)
        if resolved is False:
            unresolved = True
        elif isinstance(resolved, str):
            paths.add(resolved)
    return paths, unresolved


def _registered_route_path(
    node: ast.AST,
    prefixes: Mapping[str, str],
) -> str | bool | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in _DIRECT_ROUTE_REGISTRATION_METHODS:
        return None
    owner = node.func.value
    if not isinstance(owner, ast.Name) or owner.id not in prefixes:
        return False
    path_node = node.args[0] if node.args else next(
        (
            keyword.value
            for keyword in node.keywords
            if keyword.arg in {"path", "url"}
        ),
        None,
    )
    suffix = _literal_string(path_node)
    return False if suffix is None else prefixes[owner.id] + suffix


def pytest_fixture_boundaries(
    modules: Iterable[str],
    module_paths: Mapping[str, Path],
) -> tuple[str, ...]:
    boundaries: list[str] = []
    for module in sorted(set(modules)):
        path = module_paths.get(module)
        if path is None or not module.startswith("tests."):
            continue
        if path.name == "conftest.py":
            boundaries.append(module)
    return tuple(boundaries)


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
            text = read_python_source(path)
            if any(regex.search(text) for regex in regexes):
                selected.add(module)
    return selected
