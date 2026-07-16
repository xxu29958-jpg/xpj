"""Source-backed PostgreSQL resource classification for pytest."""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

_CLUSTER_DDL = re.compile(
    r"\b(?:CREATE|DROP|ALTER)\s+(?:DATABASE|ROLE)\b"
    r"|\b(?:GRANT|REVOKE)\b[^;]*\b(?:TO|FROM)\b"
    r"|\bpg_terminate_backend\s*\(",
    re.IGNORECASE | re.DOTALL,
)
_ALEMBIC_ACTIONS = frozenset({"downgrade", "stamp", "upgrade"})


@dataclass(frozen=True)
class _FunctionFacts:
    local_calls: frozenset[str]
    requires_cluster: bool
    requires_stateful: bool


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _literal_text(node: ast.AST) -> str:
    return " ".join(
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


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
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    alembic_aliases: Collection[str],
) -> _FunctionFacts:
    local_calls: set[str] = set()
    requires_cluster = False
    requires_stateful = False
    local_alembic_aliases = set(alembic_aliases) | set(_alembic_command_aliases(function))
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            call_name = _dotted_name(node.func)
            if isinstance(node.func, ast.Name):
                local_calls.add(node.func.id)
            if call_name and call_name.endswith(".execute") and node.args:
                requires_cluster = requires_cluster or bool(
                    _CLUSTER_DDL.search(_literal_text(node.args[0]))
                )
        if isinstance(node, ast.Attribute):
            owner = _dotted_name(node.value)
            if owner in local_alembic_aliases and node.attr in _ALEMBIC_ACTIONS:
                requires_stateful = True
    return _FunctionFacts(
        local_calls=frozenset(local_calls),
        requires_cluster=requires_cluster,
        requires_stateful=requires_stateful,
    )


def required_postgres_marker_for_source(
    source: str,
    *,
    root_names: Iterable[str],
) -> str | None:
    """Return the strongest marker required by reachable test source."""

    tree = ast.parse(source)
    alembic_aliases = _alembic_command_aliases(tree)
    functions = {
        node.name: _function_facts(node, alembic_aliases=alembic_aliases)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    pending = list(root_names)
    visited: set[str] = set()
    requires_stateful = False
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        facts = functions.get(name)
        if facts is None:
            continue
        if facts.requires_cluster:
            return "cluster_serial"
        requires_stateful = requires_stateful or facts.requires_stateful
        pending.extend(facts.local_calls - visited)
    return "stateful_serial" if requires_stateful else None


@cache
def _module_source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def _item_root_names(item: pytest.Item) -> set[str]:
    roots = {getattr(item.obj, "__name__", item.name.split("[", 1)[0])}
    fixture_info = getattr(item, "_fixtureinfo", None)
    fixture_defs = getattr(fixture_info, "name2fixturedefs", {}) or {}
    item_path = Path(str(item.path)).resolve()
    for definitions in fixture_defs.values():
        for definition in definitions or ():
            function = getattr(definition, "func", None)
            source_path = inspect.getsourcefile(function) if function is not None else None
            if source_path and Path(source_path).resolve() == item_path:
                roots.add(function.__name__)
    return roots


def postgres_source_marker_contract_violation(
    item: pytest.Item,
    marker_names: Collection[str],
) -> str | None:
    """Require resource markers from executable SQL/migration evidence."""

    required = required_postgres_marker_for_source(
        _module_source(str(Path(str(item.path)).resolve())),
        root_names=_item_root_names(item),
    )
    if required is None or required in marker_names:
        return None
    return (
        f"{item.nodeid}: executable PostgreSQL resource usage requires an explicit "
        f"{required} marker."
    )
