"""Audit paired API/Web routes that share one security-sensitive workflow.

Several project regressions came from adding a guard or audit path to the API
route while a same-meaning ``/web`` route kept a divergent implementation. This
lane catches that drift in two layers:

1. **Precise pairs** (:data:`ROUTE_PAIRS`) — the highest-risk cross-surface
   workflows (bill-split lifecycle, the live advisor call). Each names the
   exact service delegate both handlers MUST call, so removing the delegate
   from either surface fails immediately.

2. **Coverage diff** — every ``/web`` mutating route must either delegate to a
   service operation that the ``/api`` surface also uses (proving a shared
   implementation rather than a web-only reimplementation) or be listed in
   :data:`WEB_ONLY_ROUTES` with the reason it has no API sibling. A new ``/web``
   mutation that quietly reimplements a workflow — instead of calling the
   shared service the API route calls — fails the lane until it either
   delegates or is explicitly classified web-only.

Layer 2 is what turns "we check 4 hand-picked pairs" into "we account for every
web mutation". It is derived from the live router + service source each run, so
it cannot silently fall behind as routes are added.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SERVICES_DIR = ROOT / "app" / "services"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Service-layer helpers that are cross-cutting infrastructure, not workflow
# mutations. They show up on both surfaces incidentally (response shaping,
# time, the generic ``get``) so they must not count as "a shared workflow
# delegate" for the coverage diff — otherwise every route would look covered.
_INFRA_OPS = frozenset(
    {
        "get",
        "main",
        "to_iso",
        "now_utc",
        "expense_to_response",
        "recurring_item_response",
        "to_inbox_response_dict",
        "to_sent_response_dict",
        "to_response_dict",
        "current_month",
        "current_accounting_month",
    }
)

# ``/web`` mutating routes that legitimately have NO ``/api`` sibling sharing a
# service delegate. Each is a web-surface-only flow; keep the reason current.
WEB_ONLY_ROUTES: dict[str, str] = {
    "POST /web/categories/uncategorized/bulk-set": "bulk classify uncategorized — no /api equivalent",
    "POST /web/review/bulk": "web-only pending bulk-review action",
    "POST /web/import/confirm": "web-only preview→confirm step; the apply step has the /api pair",
    "POST /web/pending/batch-reject": "web-only pending bulk-reject action",
    "POST /web/auth/logout": "browser session teardown — web session is web-only",
}


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


def _service_func_names() -> frozenset[str]:
    """Top-level (public) function names defined under ``app/services``."""
    names: set[str] = set()
    for path in _SERVICES_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                names.add(node.name)
    return frozenset(names - _INFRA_OPS)


_SERVICE_FUNCS = _service_func_names()


def _route_ops(endpoint: object) -> set[str]:
    """Service operations a route handler references (word-boundary match)."""
    source = _source(endpoint)
    if not source:
        return set()
    return {fn for fn in _SERVICE_FUNCS if re.search(rf"\b{re.escape(fn)}\b", source)}


def _check_explicit_pairs(routes: dict[tuple[str, str], object]) -> list[str]:
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
    return failures


def _check_web_coverage(routes: dict[tuple[str, str], object]) -> tuple[list[str], list[str]]:
    """Every /web mutation must share a service op with /api or be opted out.

    Returns ``(failures, info_lines)``. ``info_lines`` reports the coverage
    diff (web-only routes and api-only service ops) for human review without
    failing the lane.
    """
    explicit_web = {(web_method, web_path) for _, _, web_method, web_path, _ in ROUTE_PAIRS}

    api_ops: set[str] = set()
    web_routes: list[tuple[str, str, set[str]]] = []
    for (method, path), endpoint in routes.items():
        if method not in MUTATING_METHODS:
            continue
        if path.startswith("/web"):
            web_routes.append((method, path, _route_ops(endpoint)))
        elif path.startswith(("/api", "/u")):
            api_ops |= _route_ops(endpoint)

    failures: list[str] = []
    web_only_used: set[str] = set()
    web_ops: set[str] = set()
    for method, path, ops in web_routes:
        key = f"{method} {path}"
        web_ops |= ops
        if (method, path) in explicit_web:
            continue  # gated by the precise ROUTE_PAIRS layer
        if key in WEB_ONLY_ROUTES:
            web_only_used.add(key)
            continue
        if not (ops & api_ops):
            failures.append(
                f"{key} delegates to no service shared with /api "
                f"(ops={sorted(ops) or 'none'}); either make it call the same "
                f"service its /api sibling uses, or add it to WEB_ONLY_ROUTES."
            )

    for stale in sorted(set(WEB_ONLY_ROUTES) - web_only_used):
        failures.append(f"WEB_ONLY_ROUTES entry no longer matches a registered route: {stale}")

    info = [f"web-only routes: {len(WEB_ONLY_ROUTES)}", f"/api-only service ops: {len(api_ops - web_ops)}"]
    return failures, info


def main() -> int:
    routes = _routes_by_key()
    failures = _check_explicit_pairs(routes)

    coverage_failures, info = _check_web_coverage(routes)
    failures.extend(coverage_failures)

    get_budget = routes.get(("GET", "/web/budget-advise"))
    if get_budget is not None and "run_budget_advisor" in _source(get_budget):
        failures.append("GET /web/budget-advise must render only; live advisor calls belong to POST")

    if failures:
        print("FAIL: paired API/Web route consistency drift:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"OK: {len(ROUTE_PAIRS)} precise API/Web pairs share their service delegate; "
        f"every /web mutation delegates to a shared service or is web-only "
        f"({'; '.join(info)})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
