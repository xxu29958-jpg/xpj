"""Fail-closed evidence for Python runtime import APIs."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from pathlib import Path

_DYNAMIC_IMPORT_ARGUMENTS = {
    "__import__": 0,
    "importlib.import_module": 0,
    "importlib.util.spec_from_file_location": 1,
}


class DynamicImportEvidenceError(RuntimeError):
    """Raised when a runtime import has no bounded source dependency."""


def _qualified_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value, aliases)
        return f"{owner}.{node.attr}" if owner is not None else None
    return None


def _dynamic_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for imported in node.names:
                aliases[imported.asname or imported.name] = imported.name
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "importlib",
            "importlib.util",
        }:
            for imported in node.names:
                aliases[imported.asname or imported.name] = (
                    f"{node.module}.{imported.name}"
                )
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        qualified = _qualified_name(value, aliases) if value is not None else None
        if qualified not in _DYNAMIC_IMPORT_ARGUMENTS:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id] = qualified
    return aliases


def _module_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                bindings[target.id] = node.value
    return bindings


def _static_string(
    node: ast.AST,
    bindings: Mapping[str, ast.AST],
    *,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _static_string(bindings[node.id], bindings, seen=seen | {node.id})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left, bindings, seen=seen)
        right = _static_string(node.right, bindings, seen=seen)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def _expression_module_targets(
    node: ast.AST,
    *,
    bindings: Mapping[str, ast.AST],
    resolve_reference: Callable[[str], str | None],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _expression_module_targets(
            bindings[node.id],
            bindings=bindings,
            resolve_reference=resolve_reference,
            seen=seen | {node.id},
        )
    targets: set[str] = set()
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Constant) or not isinstance(
            candidate.value,
            str,
        ):
            continue
        resolved = resolve_reference(candidate.value)
        if resolved is not None:
            targets.add(resolved)
    return targets


def _declares_source_dependency_contract(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(target, ast.Name)
            and target.id == "TEST_IMPACT_SOURCE_PREFIXES"
            for target in targets
        ):
            return True
    return False


def dynamic_import_targets(
    tree: ast.Module,
    *,
    importer_path: Path,
    resolve_reference: Callable[[str], str | None],
) -> set[str]:
    aliases = _dynamic_import_aliases(tree)
    bindings = _module_bindings(tree)
    declared = _declares_source_dependency_contract(tree)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified_name(node.func, aliases)
        argument_index = _DYNAMIC_IMPORT_ARGUMENTS.get(qualified or "")
        if argument_index is None:
            continue
        if len(node.args) <= argument_index:
            if declared:
                continue
            raise DynamicImportEvidenceError(
                f"dynamic import in {importer_path} has no static target"
            )
        target_expression = node.args[argument_index]
        static_target = _static_string(target_expression, bindings)
        if static_target is not None:
            resolved = resolve_reference(static_target)
            if resolved is not None:
                imported.add(resolved)
            continue
        expression_targets = _expression_module_targets(
            target_expression,
            bindings=bindings,
            resolve_reference=resolve_reference,
        )
        if expression_targets:
            imported.update(expression_targets)
            continue
        if not declared:
            raise DynamicImportEvidenceError(
                f"dynamic import in {importer_path} requires "
                "TEST_IMPACT_SOURCE_PREFIXES"
            )
    return imported
