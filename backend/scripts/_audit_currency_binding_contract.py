"""ADR-0061 C02 installation-currency OCC contract audit.

The generic mutate-token lane owns row OCC. This lane owns the separate
installation binding OCC dimension so ``expected_binding_revision`` can never
be mistaken for ``expected_row_version`` merely to satisfy an audit counter.
"""

from __future__ import annotations

import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _audit_mutate_token_coverage import (  # noqa: E402
    TOKEN_FIELD_NAMES,
    _iter_routes,
    _load_openapi_app_schema,
    _resolve_ref,
)
from _mutate_token_ledger import SPECIALIZED_OCC_ROUTES  # noqa: E402

_BINDING_REVISION_FIELD = "expected_binding_revision"
_REQUIRED_ADOPTION_FIELDS = frozenset(
    {
        _BINDING_REVISION_FIELD,
        "currency_contract_version",
        "expected_evidence_sha256",
        "expected_state",
        "home_currency_code",
        "reason",
    }
)


def _request_schema(spec: dict, operation: dict) -> dict:
    content = operation.get("requestBody", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    if "$ref" in schema:
        return _resolve_ref(spec, schema["$ref"])
    return schema


def _required_header(operation: dict, name: str) -> dict | None:
    for parameter in operation.get("parameters", []):
        if parameter.get("in") == "header" and parameter.get("name") == name:
            return parameter if parameter.get("required") is True else None
    return None


def main() -> int:
    spec = _load_openapi_app_schema()
    routes = {f"{method} {path}": operation for method, path, operation in _iter_routes(spec)}
    failures: list[str] = []

    if _BINDING_REVISION_FIELD in TOKEN_FIELD_NAMES:
        failures.append("binding revision was folded into the row-OCC token set")

    for key in sorted(SPECIALIZED_OCC_ROUTES):
        operation = routes.get(key)
        if operation is None:
            failures.append(f"registered binding-OCC route is missing: {key}")
            continue
        schema = _request_schema(spec, operation)
        properties = set(schema.get("properties", {}))
        required = set(schema.get("required", []))
        missing_properties = sorted(_REQUIRED_ADOPTION_FIELDS - properties)
        missing_required = sorted(_REQUIRED_ADOPTION_FIELDS - required)
        if missing_properties:
            failures.append(f"{key} missing request fields: {missing_properties}")
        if missing_required:
            failures.append(f"{key} has optional concurrency/evidence fields: {missing_required}")
        row_tokens = sorted(TOKEN_FIELD_NAMES & properties)
        if row_tokens:
            failures.append(f"{key} falsely declares row-OCC tokens: {row_tokens}")
        header = _required_header(operation, "Idempotency-Key")
        if header is None:
            failures.append(f"{key} requires no Idempotency-Key header")
        elif header.get("schema", {}).get("format") != "uuid":
            failures.append(f"{key} Idempotency-Key is not an OpenAPI UUID")

    for key, operation in routes.items():
        schema = _request_schema(spec, operation)
        if _BINDING_REVISION_FIELD in schema.get("properties", {}) and key not in SPECIALIZED_OCC_ROUTES:
            failures.append(f"unregistered binding-OCC route: {key}")

    if failures:
        print("FAIL: ADR-0061 currency binding contract drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"OK: {len(SPECIALIZED_OCC_ROUTES)} installation binding-OCC route audited; "
        "row OCC remains an independent contract."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
