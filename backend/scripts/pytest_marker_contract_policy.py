"""Literal reader for historical pytest marker contracts."""

from __future__ import annotations

import ast
from dataclasses import dataclass

if __package__:
    from .literal_source_contract import canonical_assignment_expressions
else:
    from literal_source_contract import canonical_assignment_expressions

_SCHEMA_VERSION = "PYTEST_MARKER_CONTRACT_SCHEMA_VERSION"
_STRING_FIELDS = (
    "BACKEND_PARALLEL_SAFE_MARKER",
    "BACKEND_REAL_DB_MARKER",
    "BACKEND_STATEFUL_MARKER",
    "BACKEND_CLUSTER_MARKER",
    "PACKAGING_PARALLEL_MARKER",
    "PACKAGING_SERIAL_MARKER",
)
_RESOURCE_FIELD = "PACKAGING_RESOURCE_MEMBERSHIP_MARKERS"


@dataclass(frozen=True)
class LiteralPytestMarkerContract:
    schema_version: int
    values: dict[str, str]
    packaging_resource_memberships: tuple[str, ...] | None


def _literal_value(expressions: dict[str, ast.expr], name: str) -> object:
    expression = expressions.get(name)
    if expression is None:
        raise ValueError(f"pytest marker contract is missing {name}")
    return ast.literal_eval(expression)


def _marker_name(expressions: dict[str, ast.expr], name: str) -> str:
    value = _literal_value(expressions, name)
    if not isinstance(value, str) or not value or not value.replace("_", "").isalnum():
        raise ValueError(f"pytest marker contract has invalid {name}")
    return value


def parse_pytest_marker_contract(content: str) -> LiteralPytestMarkerContract:
    names = (_SCHEMA_VERSION, *_STRING_FIELDS, _RESOURCE_FIELD)
    expressions = canonical_assignment_expressions(
        content,
        names,
        label="pytest marker contract",
    )
    schema_version = _literal_value(expressions, _SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version not in {1, 2}:
        raise ValueError("pytest marker contract schema is unsupported")
    values = {name: _marker_name(expressions, name) for name in _STRING_FIELDS}
    memberships: tuple[str, ...] | None = None
    if schema_version >= 2:
        raw_memberships = _literal_value(expressions, _RESOURCE_FIELD)
        if (
            not isinstance(raw_memberships, tuple)
            or not raw_memberships
            or len(raw_memberships) != len(set(raw_memberships))
            or any(
                not isinstance(marker, str) or not marker or not marker.replace("_", "").isalnum()
                for marker in raw_memberships
            )
        ):
            raise ValueError("pytest marker contract has invalid PACKAGING_RESOURCE_MEMBERSHIP_MARKERS")
        memberships = raw_memberships
    return LiteralPytestMarkerContract(schema_version, values, memberships)
