"""Source-backed PostgreSQL resource classification for pytest."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TypeVar

import pytest

from tests._infra.postgres_resource_ast import (
    dotted_name as _dotted_name,
)
from tests._infra.postgres_resource_ast import (
    executable_nodes as _executable_nodes,
)
from tests._infra.postgres_resource_ast import (
    literal_text as _literal_text,
)
from tests._infra.postgres_resource_ast import (
    scope_string_constants as _scope_string_constants,
)
from tests._infra.postgres_resource_ast import (
    static_text as _static_text,
)

_CLUSTER_DDL = re.compile(
    r"\b(?:CREATE|DROP|ALTER)\s+(?:DATABASE|ROLE)\b"
    r"|\b(?:GRANT|REVOKE)\b[^;]*\b(?:TO|FROM)\b"
    r"|\bpg_terminate_backend\s*\(",
    re.IGNORECASE | re.DOTALL,
)
_ALEMBIC_ACTIONS = frozenset({"downgrade", "stamp", "upgrade"})
_EXECUTION_METHODS = frozenset({"execute", "exec_driver_sql"})
_WORKER_BOUNDARY_ATTRIBUTE = "__xpj_postgres_worker_isolation_boundary__"
_WORKER_BOUNDARY_CALLS = {
    "_isolation_schema": frozenset({"worker_database_lifecycle", "reset_db_state"}),
    "_db_isolation": frozenset({"reset_db_state", "transactional_isolation"}),
}
_MARKER_RANK = {None: 0, "stateful_serial": 1, "cluster_serial": 2}
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _TESTS_ROOT.parent
_ANALYZED_ROOTS = (_TESTS_ROOT, _BACKEND_ROOT / "scripts")
_Callable = TypeVar("_Callable", bound=Callable[..., object])


@dataclass(frozen=True)
class _FunctionFacts:
    local_calls: frozenset[str]
    requires_cluster: bool
    requires_stateful: bool


@dataclass(frozen=True)
class _RuntimeFacts:
    marker: str | None
    callees: tuple[Callable[..., object], ...]


def postgres_worker_isolation_boundary(function: _Callable) -> _Callable:
    """Mark one identity-checked pytest fixture as worker-isolation plumbing."""

    setattr(function, _WORKER_BOUNDARY_ATTRIBUTE, True)
    return function


def _stronger_marker(current: str | None, candidate: str | None) -> str | None:
    return candidate if _MARKER_RANK[candidate] > _MARKER_RANK[current] else current


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    return _scope_string_constants(tree, {})


def _alembic_command_aliases(tree: ast.AST) -> frozenset[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "alembic":
            continue
        for imported in node.names:
            if imported.name == "command":
                aliases.add(imported.asname or imported.name)
    return frozenset(aliases)


def _function_facts(
    scope: ast.AST,
    *,
    alembic_aliases: Collection[str],
    constants: dict[str, str],
) -> _FunctionFacts:
    local_calls: set[str] = set()
    requires_cluster = False
    requires_stateful = False
    local_constants = _scope_string_constants(scope, constants)
    local_alembic_aliases = set(alembic_aliases) | set(_alembic_command_aliases(scope))
    for node in _executable_nodes(scope):
        if isinstance(node, ast.Call):
            call_name = _dotted_name(node.func)
            if call_name:
                local_calls.add(call_name)
                local_calls.add(call_name.rsplit(".", 1)[-1])
            if (
                call_name
                and call_name.rsplit(".", 1)[-1] in _EXECUTION_METHODS
                and node.args
                and _CLUSTER_DDL.search(_static_text(node.args[0], local_constants))
            ):
                requires_cluster = True
        if isinstance(node, ast.Attribute):
            owner = _dotted_name(node.value)
            if owner in local_alembic_aliases and node.attr in _ALEMBIC_ACTIONS:
                requires_stateful = True
    return _FunctionFacts(
        local_calls=frozenset(local_calls),
        requires_cluster=requires_cluster,
        requires_stateful=requires_stateful,
    )


def _source_function_facts(tree: ast.Module) -> dict[str, tuple[_FunctionFacts, ...]]:
    aliases = _alembic_command_aliases(tree)
    constants = _module_string_constants(tree)
    collected: dict[str, list[_FunctionFacts]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        collected.setdefault(node.name, []).append(
            _function_facts(node, alembic_aliases=aliases, constants=constants)
        )
    collected["__module__"] = [
        _function_facts(tree, alembic_aliases=aliases, constants=constants)
    ]
    return {name: tuple(facts) for name, facts in collected.items()}


@cache
def _source_function_facts_for_source(
    source: str,
) -> dict[str, tuple[_FunctionFacts, ...]]:
    return _source_function_facts(ast.parse(source))


def required_postgres_marker_for_source(
    source: str,
    *,
    root_names: Iterable[str],
) -> str | None:
    """Return the strongest marker required by reachable source."""

    functions = _source_function_facts_for_source(source)
    pending = list(root_names)
    visited: set[str] = set()
    required: str | None = None
    while pending:
        name = pending.pop()
        short_name = name.rsplit(".", 1)[-1]
        if short_name in visited:
            continue
        visited.add(short_name)
        for facts in functions.get(short_name, ()):
            if facts.requires_cluster:
                return "cluster_serial"
            if facts.requires_stateful:
                required = _stronger_marker(required, "stateful_serial")
            pending.extend(facts.local_calls - visited)
    return required


def _normalize_callable(value: object) -> Callable[..., object] | None:
    if inspect.ismethod(value):
        value = value.__func__
    if not inspect.isfunction(value):
        return None
    return inspect.unwrap(value)


def _callable_source_path(function: Callable[..., object]) -> Path | None:
    source_path = inspect.getsourcefile(function)
    if not source_path:
        return None
    try:
        return Path(source_path).resolve()
    except OSError:
        return None


def _is_analyzed_callable(function: Callable[..., object]) -> bool:
    source_path = _callable_source_path(function)
    return source_path is not None and any(
        source_path.is_relative_to(root) for root in _ANALYZED_ROOTS
    )


def _is_analyzed_type(value: object) -> bool:
    candidate = value if inspect.isclass(value) else type(value)
    try:
        source_path = inspect.getsourcefile(candidate)
    except TypeError:
        return False
    if not source_path:
        return False
    try:
        resolved = Path(source_path).resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in _ANALYZED_ROOTS)


def _class_callables(value: object) -> tuple[Callable[..., object], ...]:
    candidate = value if inspect.isclass(value) else type(value)
    if not _is_analyzed_type(candidate):
        return ()
    methods: list[Callable[..., object]] = []
    for member in vars(candidate).values():
        if isinstance(member, (staticmethod, classmethod)):
            member = member.__func__
        normalized = _normalize_callable(member)
        if normalized is not None:
            methods.append(normalized)
    return tuple(dict.fromkeys(methods))


def _owner_class(function: Callable[..., object]) -> type[object] | None:
    parts = function.__qualname__.split(".")
    if "<locals>" in parts or len(parts) < 2:
        return None
    owner: object = function.__globals__.get(parts[0])
    for part in parts[1:-1]:
        if owner is None:
            return None
        owner = getattr(owner, part, None)
    return owner if isinstance(owner, type) else None


def _callable_environment(function: Callable[..., object]) -> dict[str, object]:
    environment = dict(function.__globals__)
    try:
        closure = inspect.getclosurevars(function)
    except TypeError:
        closure = None
    if closure is not None:
        environment.update(closure.globals)
        environment.update(closure.nonlocals)
        environment.update(closure.builtins)
    owner = _owner_class(function)
    if owner is not None:
        environment["self"] = owner
        environment["cls"] = owner
    return environment


def _resolve_runtime_value(node: ast.AST, environment: dict[str, object]) -> object | None:
    if isinstance(node, ast.Name):
        return environment.get(node.id)
    if isinstance(node, ast.Attribute):
        parent = _resolve_runtime_value(node.value, environment)
        if parent is None:
            return None
        try:
            return getattr(parent, node.attr)
        except (AttributeError, RuntimeError):
            return None
    return None


def _runtime_text(
    node: ast.AST,
    environment: dict[str, object],
    constants: dict[str, str],
) -> str:
    if isinstance(node, ast.Name | ast.Attribute):
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        value = _resolve_runtime_value(node, environment)
        if isinstance(value, str):
            return value
        module_name = type(value).__module__ if value is not None else ""
        if module_name.startswith(("psycopg.sql", "sqlalchemy.sql")):
            return str(value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (
            f"{_runtime_text(node.left, environment, constants)} "
            f"{_runtime_text(node.right, environment, constants)}"
        )
    if isinstance(node, ast.JoinedStr):
        return " ".join(
            _runtime_text(value, environment, constants) for value in node.values
        )
    if isinstance(node, ast.FormattedValue):
        return _runtime_text(node.value, environment, constants)
    if isinstance(node, ast.Call):
        return " ".join(
            (
                _literal_text(node),
                *(
                    _runtime_text(argument, environment, constants)
                    for argument in node.args
                ),
            )
        )
    return _literal_text(node)


def _is_alembic_action(target: object, node: ast.Call) -> bool:
    name = getattr(target, "__name__", None)
    module_name = getattr(target, "__module__", None)
    if name in _ALEMBIC_ACTIONS and module_name == "alembic.command":
        return True
    call_name = _dotted_name(node.func)
    return bool(
        call_name
        and call_name.startswith("command.")
        and call_name.rsplit(".", 1)[-1] in _ALEMBIC_ACTIONS
    )


def _assert_worker_isolation_boundary(
    function: Callable[..., object],
    tree: ast.Module,
) -> bool:
    if not getattr(function, _WORKER_BOUNDARY_ATTRIBUTE, False):
        return False
    source_path = _callable_source_path(function)
    expected_calls = _WORKER_BOUNDARY_CALLS.get(function.__name__)
    if source_path != (_TESTS_ROOT / "conftest.py").resolve() or expected_calls is None:
        raise RuntimeError(
            "PostgreSQL worker-isolation boundary is restricted to the audited "
            "pytest lifecycle fixtures."
        )
    actual_calls = {
        call_name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (call_name := _dotted_name(node.func)) is not None
    }
    missing = sorted(expected_calls - actual_calls)
    if missing:
        raise RuntimeError(
            f"{function.__name__} no longer establishes its worker-isolation "
            f"contract; missing call(s): {', '.join(missing)}."
        )
    return True


@cache
def _runtime_callable_facts(function: Callable[..., object]) -> _RuntimeFacts:
    if not _is_analyzed_callable(function):
        return _RuntimeFacts(marker=None, callees=())
    try:
        source = textwrap.dedent(inspect.getsource(function))
    except (OSError, TypeError) as exc:
        raise RuntimeError(
            "Cannot inspect project-local PostgreSQL resource helper "
            f"{function.__module__}.{function.__qualname__}; add explicit "
            "@postgres_resource_contract metadata."
        ) from exc
    tree = ast.parse(source)
    if _assert_worker_isolation_boundary(function, tree):
        return _RuntimeFacts(marker=None, callees=())
    environment = _callable_environment(function)
    constants = _scope_string_constants(tree, {})
    required = required_postgres_marker_for_source(
        source,
        root_names=(function.__name__,),
    )
    callees: list[Callable[..., object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _dotted_name(node.func)
        if (
            call_name
            and call_name.rsplit(".", 1)[-1] in _EXECUTION_METHODS
            and node.args
            and _CLUSTER_DDL.search(
                _runtime_text(node.args[0], environment, constants)
            )
        ):
            required = "cluster_serial"
        target = _resolve_runtime_value(node.func, environment)
        if _is_alembic_action(target, node):
            required = _stronger_marker(required, "stateful_serial")
        callee = _normalize_callable(target)
        if callee is not None and _is_analyzed_callable(callee):
            callees.append(callee)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)):
            continue
        value = node.value
        if value is None:
            continue
        target = (
            _resolve_runtime_value(value.func, environment)
            if isinstance(value, ast.Call)
            else _resolve_runtime_value(value, environment)
        )
        callees.extend(_class_callables(target))
    return _RuntimeFacts(marker=required, callees=tuple(callees))


def required_postgres_marker_for_callables(
    callables: Iterable[Callable[..., object]],
) -> str | None:
    """Classify a finite project-local callable graph."""

    pending = [function for value in callables if (function := _normalize_callable(value))]
    visited: set[Callable[..., object]] = set()
    required: str | None = None
    while pending:
        function = pending.pop()
        if function in visited:
            continue
        visited.add(function)
        facts = _runtime_callable_facts(function)
        required = _stronger_marker(required, facts.marker)
        if required == "cluster_serial":
            return required
        pending.extend(callee for callee in facts.callees if callee not in visited)
    return required


@cache
def _module_source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def _item_root_names(item: pytest.Item) -> set[str]:
    roots = {"__module__", getattr(item.obj, "__name__", item.name.split("[", 1)[0])}
    fixture_info = getattr(item, "_fixtureinfo", None)
    fixture_defs = getattr(fixture_info, "name2fixturedefs", {}) or {}
    for definitions in fixture_defs.values():
        for definition in definitions or ():
            function = getattr(definition, "func", None)
            if function is not None:
                roots.add(getattr(function, "__name__", ""))
    return {root for root in roots if root}


def _item_root_callables(item: pytest.Item) -> tuple[Callable[..., object], ...]:
    roots: list[Callable[..., object]] = []
    item_callable = _normalize_callable(getattr(item, "obj", None))
    if item_callable is not None:
        roots.append(item_callable)
    fixture_info = getattr(item, "_fixtureinfo", None)
    fixture_defs = getattr(fixture_info, "name2fixturedefs", {}) or {}
    for definitions in fixture_defs.values():
        for definition in definitions or ():
            fixture_callable = _normalize_callable(getattr(definition, "func", None))
            if fixture_callable is not None:
                roots.append(fixture_callable)
    return tuple(dict.fromkeys(roots))


def _required_postgres_marker_for_item(item: pytest.Item) -> str | None:
    item_path = Path(str(item.path)).resolve()
    required = required_postgres_marker_for_source(
        _module_source(str(item_path)),
        root_names=_item_root_names(item),
    )
    runtime_required = required_postgres_marker_for_callables(
        _item_root_callables(item)
    )
    return _stronger_marker(required, runtime_required)


def postgres_source_marker_contract_violation(
    item: pytest.Item,
    marker_names: Collection[str],
) -> str | None:
    """Require resource markers from executable SQL/migration evidence."""

    try:
        required = _required_postgres_marker_for_item(item)
    except (OSError, RuntimeError, SyntaxError) as exc:
        return f"{item.nodeid}: PostgreSQL resource classification failed closed: {exc}"
    if required is None or required in marker_names:
        return None
    return (
        f"{item.nodeid}: executable PostgreSQL resource usage requires an explicit "
        f"{required} marker."
    )
