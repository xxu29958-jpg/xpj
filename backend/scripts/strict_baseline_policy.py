"""Literal-only parser for versioned PR-delta baseline policy."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class StrictBaselinePolicy:
    baseline: dict[str, int]
    ratchet_up: frozenset[str]
    ratchet_down: frozenset[str]
    ratchet_policy_present: bool


def _assignment_expression(tree: ast.Module, name: str) -> ast.expr | None:
    expressions: list[ast.expr] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and statement.value is not None
        ) or isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            expressions.append(statement.value)
    if len(expressions) > 1:
        raise ValueError(f"base gate defines {name} more than once")
    return None if not expressions else expressions[0]


def _literal_frozenset(expression: ast.expr, *, name: str) -> frozenset[str]:
    if (
        isinstance(expression, ast.Call)
        and isinstance(expression.func, ast.Name)
        and expression.func.id == "frozenset"
        and len(expression.args) <= 1
        and not expression.keywords
    ):
        if not expression.args:
            return frozenset()
        expression = expression.args[0]
    value = ast.literal_eval(expression)
    if not isinstance(value, (set, frozenset)) or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError(f"base gate {name} is not a string set")
    return frozenset(value)


def parse_strict_baseline_policy(content: str) -> StrictBaselinePolicy:
    tree = ast.parse(content)
    baseline_expression = _assignment_expression(tree, "STRICT_EQUALITY_BASELINE")
    if baseline_expression is None:
        return StrictBaselinePolicy({}, frozenset(), frozenset(), False)
    baseline = ast.literal_eval(baseline_expression)
    if (
        not isinstance(baseline, dict)
        or any(not isinstance(key, str) for key in baseline)
        or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in baseline.values()
        )
    ):
        raise ValueError(
            "base gate STRICT_EQUALITY_BASELINE is not a string-to-int mapping"
        )
    up_expression = _assignment_expression(tree, "BASELINE_RATCHET_UP")
    down_expression = _assignment_expression(tree, "BASELINE_RATCHET_DOWN")
    if up_expression is None and down_expression is None:
        return StrictBaselinePolicy(dict(baseline), frozenset(), frozenset(), False)
    if up_expression is None or down_expression is None:
        raise ValueError("base gate ratchet policy is incomplete")
    ratchet_up = _literal_frozenset(up_expression, name="BASELINE_RATCHET_UP")
    ratchet_down = _literal_frozenset(down_expression, name="BASELINE_RATCHET_DOWN")
    if ratchet_up & ratchet_down:
        raise ValueError("base gate ratchet policies overlap")
    if (ratchet_up | ratchet_down) - set(baseline):
        raise ValueError("base gate ratchet policy references unknown counters")
    return StrictBaselinePolicy(dict(baseline), ratchet_up, ratchet_down, True)
