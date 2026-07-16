"""Shared AST helpers for PostgreSQL resource classification."""

from __future__ import annotations

import ast
from collections.abc import Iterator


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def literal_text(node: ast.AST) -> str:
    return " ".join(
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    )


def static_text(node: ast.AST, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return f"{static_text(node.left, constants)} {static_text(node.right, constants)}"
    if isinstance(node, ast.JoinedStr):
        return " ".join(static_text(value, constants) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        return static_text(node.value, constants)
    if isinstance(node, ast.Call):
        return " ".join(
            (
                literal_text(node),
                *(static_text(argument, constants) for argument in node.args),
            )
        )
    return literal_text(node)


def executable_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    body = getattr(scope, "body", ())
    pending = list(reversed(body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def scope_string_constants(
    scope: ast.AST,
    inherited: dict[str, str],
) -> dict[str, str]:
    constants = dict(inherited)
    for node in executable_nodes(scope):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            rendered = static_text(value, constants)
            if rendered:
                previous = constants.get(target.id, "")
                constants[target.id] = f"{previous} {rendered}".strip()
    return constants
