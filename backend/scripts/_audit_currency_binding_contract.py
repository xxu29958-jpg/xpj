"""Audit the live product entry for installation-currency adoption.

Currency adoption uses installation binding OCC rather than row OCC. The
product command is a Desktop form, intentionally absent from the public API
schema; this lane inspects FastAPI's registered runtime route instead.
"""

from __future__ import annotations

import pathlib
import sys

from fastapi.routing import APIRoute

_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app  # noqa: E402

_PRODUCT_PATH = "/web/currency-adoption"
_RETIRED_API_PATH = "/api/maintenance/currency-binding/adoption"
_REQUIRED_FORM_FIELDS = frozenset(
    {
        "currency_contract_version",
        "evidence_token",
        "expected_binding_revision",
        "expected_state",
        "home_currency_code",
        "idempotency_key",
    }
)


def main() -> int:
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    failures: list[str] = []
    if any(route.path == _RETIRED_API_PATH for route in routes):
        failures.append(f"retired adoption API is registered: {_RETIRED_API_PATH}")

    product_routes = [route for route in routes if route.path == _PRODUCT_PATH]
    methods = {method for route in product_routes for method in route.methods}
    if not {"GET", "POST"}.issubset(methods):
        failures.append(f"product adoption route needs GET and POST, found: {sorted(methods)}")

    post = next((route for route in product_routes if "POST" in route.methods), None)
    if post is not None:
        form_fields = {parameter.name for parameter in post.dependant.body_params}
        missing = sorted(_REQUIRED_FORM_FIELDS - form_fields)
        if missing:
            failures.append(f"product adoption form is missing: {missing}")
        non_form = sorted(
            parameter.name
            for parameter in post.dependant.body_params
            if parameter.field_info.media_type != "application/x-www-form-urlencoded"
        )
        if non_form:
            failures.append(f"product adoption fields are not form-bound: {non_form}")

    if failures:
        print("FAIL: installation currency adoption product contract drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: Desktop adoption route owns the installation binding OCC form; legacy API is retired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
