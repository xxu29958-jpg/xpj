"""Literal-only parser for versioned PR-delta baseline policy."""

from __future__ import annotations

import ast
from dataclasses import dataclass

if __package__:
    from .literal_source_contract import canonical_assignment_expressions
else:
    from literal_source_contract import canonical_assignment_expressions


@dataclass(frozen=True)
class StrictBaselinePolicy:
    baseline: dict[str, int]
    ratchet_up: frozenset[str]
    ratchet_down: frozenset[str]
    ratchet_policy_present: bool


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
    if not isinstance(value, (set, frozenset)) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"base gate {name} is not a string set")
    return frozenset(value)


def parse_strict_baseline_policy(content: str) -> StrictBaselinePolicy:
    names = (
        "STRICT_EQUALITY_BASELINE",
        "BASELINE_RATCHET_UP",
        "BASELINE_RATCHET_DOWN",
    )
    expressions = canonical_assignment_expressions(
        content,
        names,
        label="base gate",
    )
    baseline_expression = expressions.get("STRICT_EQUALITY_BASELINE")
    if baseline_expression is None:
        return StrictBaselinePolicy({}, frozenset(), frozenset(), False)
    baseline = ast.literal_eval(baseline_expression)
    if (
        not isinstance(baseline, dict)
        or any(not isinstance(key, str) for key in baseline)
        or any(not isinstance(value, int) or isinstance(value, bool) for value in baseline.values())
    ):
        raise ValueError("base gate STRICT_EQUALITY_BASELINE is not a string-to-int mapping")
    up_expression = expressions.get("BASELINE_RATCHET_UP")
    down_expression = expressions.get("BASELINE_RATCHET_DOWN")
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
