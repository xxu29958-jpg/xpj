"""Fail-closed extraction of canonical top-level source assignments."""

from __future__ import annotations

import ast
from collections.abc import Iterable


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
            and isinstance(node.ctx, ast.Store)
            and node.id in protected
            and id(node) not in canonical_targets
        ):
            raise ValueError(f"{label} has noncanonical protected assignment to {node.id}")
    return expressions
