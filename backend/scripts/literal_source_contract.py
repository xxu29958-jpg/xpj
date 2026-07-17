"""Fail-closed extraction of canonical top-level source assignments."""

from __future__ import annotations

import ast
from collections.abc import Iterable


def _root_name(expression: ast.expr) -> str | None:
    while isinstance(expression, (ast.Attribute, ast.Subscript)):
        expression = expression.value
    return expression.id if isinstance(expression, ast.Name) else None


def _direct_alias_source(node: ast.AST) -> str | None:
    value: ast.expr | None = None
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        value = node.value
    return value.id if isinstance(value, ast.Name) else None


def canonical_assignment_expressions(
    content: str,
    names: Iterable[str],
    *,
    label: str,
) -> dict[str, ast.expr]:
    """Return one direct assignment per protected name without executing source."""

    tree = ast.parse(content)
    protected = frozenset(names)
    expressions: dict[str, ast.expr] = {}
    canonical_targets: set[int] = set()
    for statement in tree.body:
        target: ast.Name | None = None
        value: ast.expr | None = None
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            target = statement.target
            value = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target = statement.targets[0]
            value = statement.value
        if target is None or target.id not in protected or value is None:
            continue
        if target.id in expressions:
            raise ValueError(f"{label} defines protected assignment {target.id} more than once")
        expressions[target.id] = value
        canonical_targets.add(id(target))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and node.id in protected
            and id(node) not in canonical_targets
        ):
            raise ValueError(f"{label} has noncanonical protected assignment to {node.id}")
        alias_source = _direct_alias_source(node)
        if alias_source in protected:
            raise ValueError(f"{label} creates a noncanonical alias for {alias_source}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _root_name(node.func.value) in protected
        ):
            raise ValueError(
                f"{label} has noncanonical protected mutation through "
                f"{_root_name(node.func.value)}.{node.func.attr}()"
            )
        if (
            isinstance(node, (ast.Attribute, ast.Subscript))
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and (root := _root_name(node)) in protected
        ):
            raise ValueError(f"{label} has noncanonical protected mutation through {root}")
    return expressions
