"""Audit paired API/Web routes that share one security-sensitive workflow.

Several project regressions came from adding a guard or audit path to the API
route while a same-meaning ``/web`` route kept a divergent implementation. This
lane keeps the high-risk pairs explicit and checks that both handlers still
delegate to the same service operation.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ROUTE_PAIRS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("POST", "/api/budget/advise", "POST", "/web/budget-advise", ("run_budget_advisor",)),
    (
        "POST",
        "/api/bill-splits/{public_id}/accept",
        "POST",
        "/web/bill-splits/{public_id}/accept",
        ("accept_invitation",),
    ),
    (
        "POST",
        "/api/bill-splits/{public_id}/reject",
        "POST",
        "/web/bill-splits/{public_id}/reject",
        ("reject_invitation",),
    ),
    (
        "POST",
        "/api/bill-splits/{public_id}/cancel",
        "POST",
        "/web/bill-splits/{public_id}/cancel",
        ("cancel_invitation",),
    ),
)


def _routes_by_key() -> dict[tuple[str, str], object]:
    from fastapi.routing import APIRoute

    from app.main import app

    routes: dict[tuple[str, str], object] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or ():
            routes[(method.upper(), route.path)] = route.endpoint
    return routes


def _source(endpoint: object) -> str:
    try:
        return inspect.getsource(endpoint)
    except (OSError, TypeError):
        return ""


def _module_source(endpoint: object) -> str:
    module = inspect.getmodule(endpoint)
    if module is None:
        return ""
    try:
        return inspect.getsource(module)
    except (OSError, TypeError):
        return ""


def main() -> int:
    routes = _routes_by_key()
    failures: list[str] = []
    for api_method, api_path, web_method, web_path, required_terms in ROUTE_PAIRS:
        api_endpoint = routes.get((api_method, api_path))
        web_endpoint = routes.get((web_method, web_path))
        if api_endpoint is None:
            failures.append(f"missing API route {api_method} {api_path}")
            continue
        if web_endpoint is None:
            failures.append(f"missing Web route {web_method} {web_path}")
            continue
        api_source = _source(api_endpoint)
        web_source = _source(web_endpoint)
        web_module_source = _module_source(web_endpoint)
        for term in required_terms:
            if term not in api_source:
                failures.append(f"{api_method} {api_path} no longer delegates to {term}")
            if term not in web_source and term not in web_module_source:
                failures.append(f"{web_method} {web_path} no longer delegates to {term}")

    get_budget = routes.get(("GET", "/web/budget-advise"))
    if get_budget is not None and "run_budget_advisor" in _source(get_budget):
        failures.append("GET /web/budget-advise must render only; live advisor calls belong to POST")

    if failures:
        print("FAIL: paired API/Web route consistency drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK: high-risk paired API/Web routes share service delegates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
