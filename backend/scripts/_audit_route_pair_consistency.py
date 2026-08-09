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
_READ_ONLY_SERVICE_PREFIXES = (
    "current_",
    "find_",
    "get_",
    "list_",
    "require_",
    "resolve_",
    "serialize_",
    "to_",
    "validate_",
)

# A Web form adapter may deliberately strengthen a legacy JSON lifecycle
# contract with actor-scoped idempotency/OCC while preserving the same domain
# transition. Keep those equivalences explicit: unlike WEB_ONLY_ROUTES these
# entries still require an API sibling and participate in coverage.
_SERVICE_OP_ALIASES: dict[str, frozenset[str]] = {
    "create_goal": frozenset({"create_debt_repayment_goal"}),
    "remove_voided_debt_goal_links_idempotently": frozenset(
        {"replace_debt_repayment_goal_links"}
    ),
    "archive_debt_repayment_goal_idempotently": frozenset({"archive_goal"}),
    "restore_debt_repayment_goal_idempotently": frozenset({"restore_goal"}),
}

# ``/web`` mutating routes that legitimately have NO ``/api`` sibling sharing a
# service delegate. Each is a web-surface-only flow; keep the reason current.
WEB_ONLY_ROUTES: dict[str, str] = {
    "POST /web/categories/uncategorized/bulk-set": "bulk classify uncategorized — no /api equivalent",
    "POST /web/review/bulk": "web-only pending bulk-review action",
    "POST /web/import/confirm": "web-only preview→confirm step; the apply step has the /api pair",
    "POST /web/pending/batch-reject": "web-only pending bulk-reject action",
    "POST /web/duplicates/{expense_id}/reject-original": (
        "web-only atomic keep-current/reject-original decision; API exposes separate primitives"
    ),
    "POST /web/auth/logout": "browser session teardown — web session is web-only",
}


ROUTE_PAIRS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("POST", "/api/budget/advise", "POST", "/web/budget-advise", ("run_budget_advisor",)),
    (
        "POST",
        "/api/expenses/{expense_id}/confirm",
        "POST",
        "/web/expenses/{expense_id}/confirm",
        ("confirm_expense_submission",),
    ),
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

_COMMAND_CONTRACTS: tuple[
    tuple[str, str, frozenset[str], frozenset[str]], ...
] = (
    (
        "POST",
        "/api/expenses/{expense_id}/confirm",
        frozenset({"confirm_expense_submission"}),
        frozenset({"commit", "cleanup_after_confirm", "confirm_expense", "update_expense"}),
    ),
    (
        "POST",
        "/web/expenses/{expense_id}/confirm",
        frozenset({"confirm_expense_submission"}),
        frozenset({"commit", "cleanup_after_confirm", "confirm_expense", "update_expense"}),
    ),
    (
        "POST",
        "/web/duplicates/{expense_id}/reject-original",
        frozenset({"reject_duplicate_original_keep_current"}),
        frozenset({"commit", "mark_expense_not_duplicate", "reject_expense"}),
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


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


def _resolve_call_target(node: ast.expr, namespace: dict[str, object]) -> object | None:
    if isinstance(node, ast.Name):
        return namespace.get(node.id)
    if not isinstance(node, ast.Attribute):
        return None
    owner = _resolve_call_target(node.value, namespace)
    if owner is None:
        return None
    return getattr(owner, node.attr, None)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _function_belongs_to(target: object, package: str) -> bool:
    if not inspect.isfunction(target):
        return False
    module_name = getattr(target, "__module__", "")
    return module_name == package or module_name.startswith(f"{package}.")


def _service_callback_names(
    node: ast.Call,
    namespace: dict[str, object],
) -> set[str]:
    names: set[str] = set()
    callback_nodes = [*node.args, *(item.value for item in node.keywords)]
    for callback_node in callback_nodes:
        callback = _resolve_call_target(callback_node, namespace)
        if _function_belongs_to(callback, "app.services"):
            names.add(callback.__name__)
    return names


def _route_call_graph(endpoint: object) -> tuple[str, set[str], set[str], set[str]]:
    """Return route source, calls, and proven service calls/callback references."""

    pending = [endpoint]
    visited: set[int] = set()
    segments: list[str] = []
    calls: set[str] = set()
    service_calls: set[str] = set()
    service_refs: set[str] = set()
    while pending:
        function = pending.pop()
        if not inspect.isfunction(function) or id(function) in visited:
            continue
        visited.add(id(function))
        source = _source(function)
        if not source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        segments.append(source)
        namespace = getattr(function, "__globals__", {})
        call_nodes = (node for node in ast.walk(tree) if isinstance(node, ast.Call))
        for node in call_nodes:
            name = _call_name(node)
            if name is not None:
                calls.add(name)
            target = _resolve_call_target(node.func, namespace)
            if _function_belongs_to(target, "app.services"):
                service_calls.add(target.__name__)
                service_refs.add(target.__name__)
            elif _function_belongs_to(target, "app.routes"):
                pending.append(target)
            service_refs.update(_service_callback_names(node, namespace))
    return "\n".join(segments), calls, service_calls, service_refs


def _service_func_names() -> frozenset[str]:
    """Top-level public function names defined under ``app/services``."""
    names: set[str] = set()
    for path in _SERVICES_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                names.add(node.name)
    return frozenset(
        name
        for name in names - _INFRA_OPS
        if name.startswith("get_or_create_")
        or not name.startswith(_READ_ONLY_SERVICE_PREFIXES)
    )


_SERVICE_FUNCS = _service_func_names()


def _expanded_service_ops(direct: set[str]) -> set[str]:
    expanded: set[str] = set()
    pending = list(direct)
    while pending:
        operation = pending.pop()
        if operation in expanded:
            continue
        expanded.add(operation)
        pending.extend(_SERVICE_OP_ALIASES.get(operation, ()))
        if operation.endswith("_idempotently"):
            base = operation.removesuffix("_idempotently")
            if base in _SERVICE_FUNCS:
                pending.append(base)
    return expanded


def _route_ops(endpoint: object) -> set[str]:
    """Service operations a route reaches through local/service adapters."""
    _source_text, _calls, service_calls, service_refs = _route_call_graph(endpoint)
    return _expanded_service_ops((service_calls | service_refs) & _SERVICE_FUNCS)


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
        for term in required_terms:
            failures.extend(
                _route_delegate_contract_failures(
                    f"{api_method} {api_path}",
                    api_endpoint,
                    required=frozenset({term}),
                    forbidden=frozenset(),
                )
            )
            failures.extend(
                _route_delegate_contract_failures(
                    f"{web_method} {web_path}",
                    web_endpoint,
                    required=frozenset({term}),
                    forbidden=frozenset(),
                )
            )
    return failures


def _delegate_contract_failures(
    label: str,
    source: str,
    *,
    required: frozenset[str],
    forbidden: frozenset[str],
) -> list[str]:
    try:
        calls = _called_names(ast.parse(source))
    except SyntaxError:
        return [f"{label} source could not be parsed"]
    failures = [
        f"{label} must delegate to {name}"
        for name in sorted(required - calls)
    ]
    failures.extend(
        f"{label} must not own {name}"
        for name in sorted(forbidden & calls)
    )
    return failures


def _route_delegate_contract_failures(
    label: str,
    endpoint: object,
    *,
    required: frozenset[str],
    forbidden: frozenset[str],
) -> list[str]:
    _source_text, calls, service_calls, _service_refs = _route_call_graph(endpoint)
    failures = [
        f"{label} must call app.services.{name}"
        for name in sorted(required - service_calls)
    ]
    failures.extend(
        f"{label} route call graph must not own {name}"
        for name in sorted(forbidden & calls)
    )
    return failures


def _check_command_delegates(
    routes: dict[tuple[str, str], object],
) -> list[str]:
    failures: list[str] = []
    for method, path, required, forbidden in _COMMAND_CONTRACTS:
        endpoint = routes.get((method, path))
        label = f"{method} {path}"
        if endpoint is None:
            failures.append(f"missing Web route {label}")
            continue
        failures.extend(
            _route_delegate_contract_failures(
                label,
                endpoint,
                required=required,
                forbidden=forbidden,
            )
        )
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
    failures.extend(_check_command_delegates(routes))

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
