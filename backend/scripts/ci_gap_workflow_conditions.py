"""Evaluate workflow conditions for protected CI command discovery."""

from __future__ import annotations

import re


def _strip_expression_wrapper(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("${{") and stripped.endswith("}}"):
        return stripped[3:-2].strip()
    return stripped


def _strip_outer_condition_parentheses(value: str) -> str:
    stripped = value.strip()
    while stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    return stripped


def _condition_branch_is_proven(branch: str, event_name: str) -> bool:
    comparison = re.compile(
        r"github\.event_name\s*(==|!=)\s*(['\"])([^'\"]+)\2",
        re.IGNORECASE,
    )
    predicates = [
        _strip_outer_condition_parentheses(predicate)
        for predicate in re.split(r"&&", branch)
    ]
    if not predicates:
        return False
    for predicate in predicates:
        lowered = predicate.lower()
        if lowered in {"true", "success()", "always()", "!cancelled()"}:
            continue
        match = comparison.fullmatch(predicate)
        if match is None:
            return False
        equal = event_name == match.group(3)
        if (match.group(1) == "==" and not equal) or (
            match.group(1) == "!=" and equal
        ):
            return False
    return True


def _condition_is_proven_for_event(expression: str, event_name: str) -> bool:
    return any(
        _condition_branch_is_proven(branch, event_name)
        for branch in re.split(r"\|\|", expression)
    )


def condition_guarantees_after_needs(value: object, event_name: str) -> bool:
    if value is None or value is False:
        return False
    expression = _strip_expression_wrapper(str(value))
    normalized = re.sub(r"\s+", " ", expression).strip()
    return any(
        re.search(r"(?i)\balways\s*\(\s*\)", branch) is not None
        and _condition_branch_is_proven(branch, event_name)
        for branch in re.split(r"\|\|", normalized)
    )


def _condition_may_allow_event(normalized: str, event_name: str) -> bool:
    if "github.event_name" not in normalized:
        return True

    comparison = re.compile(
        r"github\.event_name\s*(==|!=)\s*(['\"])([^'\"]+)\2",
        re.IGNORECASE,
    )
    for branch in re.split(r"\|\|", normalized):
        matches = list(comparison.finditer(branch))
        if not matches:
            if "github.event_name" in branch:
                continue
            if not re.search(r"\bfalse\b|failure\(\)|cancelled\(\)", branch, re.IGNORECASE):
                return True
            continue
        if re.search(r"!\s*\([^)]*github\.event_name", branch, re.IGNORECASE):
            continue
        if re.search(r"\bfalse\b|failure\(\)|cancelled\(\)", branch, re.IGNORECASE):
            continue
        permits = True
        for match in matches:
            equal = event_name == match.group(3)
            if (match.group(1) == "==" and not equal) or (
                match.group(1) == "!=" and equal
            ):
                permits = False
                break
        if permits:
            return True
    return False


def condition_allows_event(
    value: object,
    event_name: str,
    *,
    require_proof: bool = False,
) -> bool:
    if value is None or value is True:
        return True
    if value is False:
        return False
    expression = _strip_expression_wrapper(str(value))
    normalized = re.sub(r"\s+", " ", expression).strip()
    if normalized.lower() in {"", "true", "success()", "always()"}:
        return True
    if normalized.lower() in {"false", "failure()", "cancelled()"}:
        return False
    if require_proof:
        return _condition_is_proven_for_event(normalized, event_name)
    return _condition_may_allow_event(normalized, event_name)


def allows_failure(value: object) -> bool:
    if value is None or value is False:
        return False
    if value is True:
        return True
    return _strip_expression_wrapper(str(value)).strip().lower() not in {"", "false"}
