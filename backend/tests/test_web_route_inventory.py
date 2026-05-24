"""Static classification of every /web/* route.

Before /web can serve public traffic (Cloudflare Tunnel + Web session,
v1.0 PR-3/4), every existing /web route must be classified along these
axes:

- ``local-only-rendering`` — GET that depends on the current
  ``selected_ledger_id`` fallback (which defaults to ``owner``); rendering
  this to an unauthenticated public visitor would leak the owner ledger.
  Only safe to publish after a Web session forces ``selected_ledger_id``
  to the logged-in account's ledger.

- ``writer-only`` — state-changing endpoint that already calls
  :func:`app.routes.web_common._require_selected_ledger_write` against the
  resolved ledger. Going public still requires a Web session (so the
  caller is a known account), but the ledger-write boundary is already in
  place.

- ``media`` — protected binary stream (image / thumbnail). Authorisation
  is enforced inside the service layer, not at route level.

- ``auth`` — the cookie session flow itself (login form / submit /
  logout / whoami). These are intentionally NOT gated by
  ``_require_selected_ledger_write`` — login by definition runs without
  any prior session — and they don't depend on the owner-default ledger
  either. Public host is fine.

This file is the **single source of truth** for that classification. The
tests below assert:

1. Every ``/web/*`` route registered on the live FastAPI app appears in
   :data:`_WEB_ROUTE_CLASSIFICATION` (forces a deliberate classification
   whenever a new route is added).
2. No duplicate ``(method, path)`` pair is registered; FastAPI would otherwise
   silently let the first endpoint win.
3. Every ``writer-only`` route endpoint itself references
   ``_require_selected_ledger_write`` (so the classification doesn't drift
   away from the code).

Adding a route without classifying it = pytest red, which is the entire
point.
"""

from __future__ import annotations

import inspect
from collections import Counter
from collections.abc import Callable
from typing import Literal

import pytest
from starlette.routing import Route

from app.main import app

Classification = Literal["local-only-rendering", "writer-only", "media", "auth"]


# (method, path) -> classification. Keep sorted by path for diff readability.
_WEB_ROUTE_CLASSIFICATION: dict[tuple[str, str], Classification] = {
    # Cookie session flow — public-host safe by design (login runs before
    # any session exists; logout / whoami carry the cookie themselves).
    ("GET", "/web/auth/login"): "auth",
    ("POST", "/web/auth/login"): "auth",
    ("POST", "/web/auth/logout"): "auth",
    ("GET", "/web/auth/whoami"): "auth",
    # /web root and slash redirect.
    ("GET", "/web"): "local-only-rendering",
    ("GET", "/web/"): "local-only-rendering",
    # Account flows
    ("GET", "/web/confirmed"): "local-only-rendering",
    ("POST", "/web/confirmed/batch-update"): "writer-only",
    # Budgets
    ("GET", "/web/budgets"): "local-only-rendering",
    ("POST", "/web/budgets/save"): "writer-only",
    # v1.1 AI budget advisor + income plan (PR-9)
    ("GET", "/web/budget-advise"): "local-only-rendering",
    ("GET", "/web/income-plans"): "local-only-rendering",
    ("POST", "/web/income-plans/create"): "writer-only",
    ("POST", "/web/income-plans/{public_id}/archive"): "writer-only",
    ("POST", "/web/income-plans/{public_id}/restore"): "writer-only",
    # Categories
    ("GET", "/web/categories"): "local-only-rendering",
    ("GET", "/web/categories/uncategorized"): "local-only-rendering",
    ("POST", "/web/categories/uncategorized/bulk-set"): "writer-only",
    # Dashboard
    ("GET", "/web/dashboard/data"): "local-only-rendering",
    ("GET", "/web/dashboard/cards"): "local-only-rendering",
    ("POST", "/web/dashboard/cards/save"): "writer-only",
    ("POST", "/web/dashboard/cards/reset"): "writer-only",
    # Data quality
    ("GET", "/web/data-quality"): "local-only-rendering",
    # Duplicates
    ("GET", "/web/duplicates"): "local-only-rendering",
    ("POST", "/web/duplicates/{expense_id}/keep"): "writer-only",
    ("POST", "/web/duplicates/{expense_id}/reject-current"): "writer-only",
    ("POST", "/web/duplicates/{expense_id}/reject-original"): "writer-only",
    # Expense edit (pending + confirmed both land here)
    ("GET", "/web/expenses/{expense_id}/edit"): "local-only-rendering",
    ("POST", "/web/expenses/{expense_id}/save"): "writer-only",
    ("POST", "/web/expenses/{expense_id}/confirm"): "writer-only",
    ("POST", "/web/expenses/{expense_id}/items/save"): "writer-only",
    ("POST", "/web/expenses/{expense_id}/items/acknowledge-mismatch"): "writer-only",
    # ADR-0030 background tasks UI
    ("GET", "/web/tasks"): "local-only-rendering",
    # Cancel is account-scoped, not ledger-write; service layer enforces
    # account match in request_cancellation.
    ("POST", "/web/tasks/{public_id}/cancel"): "local-only-rendering",
    # ADR-0029 bill split UI
    ("POST", "/web/expenses/{expense_id}/split-invite"): "writer-only",
    ("GET", "/web/bill-splits/inbox"): "local-only-rendering",
    ("GET", "/web/bill-splits/sent"): "local-only-rendering",
    # accept / reject 不写 selected_ledger（accept 写 target_ledger
    # 在 service 层 _load_writer_member 校验；reject 不写任何 ledger）
    ("POST", "/web/bill-splits/{public_id}/accept"): "local-only-rendering",
    ("POST", "/web/bill-splits/{public_id}/reject"): "local-only-rendering",
    ("POST", "/web/bill-splits/{public_id}/cancel"): "writer-only",
    ("POST", "/web/expenses/{expense_id}/splits/save"): "writer-only",
    ("POST", "/web/expenses/{expense_id}/reject"): "writer-only",
    # Media — handler is in web_media.py (the duplicate in web_app.py was
    # removed in PR #55). Auth happens inside ensure_image_file /
    # ensure_thumbnail_file via ledger_scoped_select.
    ("GET", "/web/expenses/{expense_id}/image"): "media",
    ("GET", "/web/expenses/{expense_id}/thumbnail"): "media",
    # CSV export
    ("GET", "/web/export.csv"): "local-only-rendering",
    # Goals
    ("GET", "/web/goals"): "local-only-rendering",
    ("POST", "/web/goals/create"): "writer-only",
    ("POST", "/web/goals/{public_id}/archive"): "writer-only",
    # CSV import
    ("GET", "/web/import"): "local-only-rendering",
    ("POST", "/web/import/preview"): "writer-only",
    ("GET", "/web/import/{public_id}"): "local-only-rendering",
    ("POST", "/web/import/{public_id}/apply"): "writer-only",
    ("GET", "/web/import/{public_id}/errors.csv"): "local-only-rendering",
    ("POST", "/web/import/confirm"): "writer-only",
    # Merchants
    ("GET", "/web/merchants"): "local-only-rendering",
    ("POST", "/web/merchants/aliases/create"): "writer-only",
    ("POST", "/web/merchants/aliases/{public_id}/toggle"): "writer-only",
    ("POST", "/web/merchants/aliases/{public_id}/delete"): "writer-only",
    # Pending
    ("GET", "/web/pending"): "local-only-rendering",
    ("POST", "/web/pending/batch-reject"): "writer-only",
    ("POST", "/web/review/bulk"): "writer-only",
    # Recurring
    ("GET", "/web/recurring"): "local-only-rendering",
    ("POST", "/web/recurring/confirm-candidate"): "writer-only",
    ("POST", "/web/recurring/{public_id}/pause"): "writer-only",
    ("POST", "/web/recurring/{public_id}/resume"): "writer-only",
    ("POST", "/web/recurring/{public_id}/archive"): "writer-only",
    # Reports
    ("GET", "/web/reports"): "local-only-rendering",
    ("GET", "/web/reports/export.csv"): "local-only-rendering",
    # Rules
    ("GET", "/web/rules"): "local-only-rendering",
    ("POST", "/web/rules/create"): "writer-only",
    ("POST", "/web/rules/applications/{public_id}/rollback"): "writer-only",
    ("POST", "/web/rules/{rule_id}/toggle"): "writer-only",
    ("POST", "/web/rules/{rule_id}/delete"): "writer-only",
    ("POST", "/web/rules/apply-pending"): "writer-only",
    ("POST", "/web/rules/apply-confirmed"): "writer-only",
    # Search / Stats
    ("GET", "/web/search"): "local-only-rendering",
    ("GET", "/web/stats"): "local-only-rendering",
}


def _enumerate_web_routes() -> set[tuple[str, str]]:
    """Return (method, path) pairs for every /web/* route on the live app.

    Static (StaticFiles) and ``HEAD``/``OPTIONS`` are skipped — only routes
    with a Python handler that a Web session would need to gate.
    """
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        if not route.path.startswith("/web"):
            continue
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.add((method, route.path))
    return found


def _enumerate_web_route_counts() -> Counter[tuple[str, str]]:
    found: Counter[tuple[str, str]] = Counter()
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        if not route.path.startswith("/web"):
            continue
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            found[(method, route.path)] += 1
    return found


def _writer_only_paths() -> list[tuple[str, str]]:
    return [
        key for key, kind in _WEB_ROUTE_CLASSIFICATION.items()
        if kind == "writer-only"
    ]


def _route_endpoint(method: str, path: str) -> Callable[..., object] | None:
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        if route.path != path:
            continue
        if method in (route.methods or ()):
            return route.endpoint
    return None


def test_every_web_route_is_classified() -> None:
    """Every live /web/* route must appear in the classification table.

    Adding a /web route without writing down its classification = test red.
    This forces every Web session / public-host PR (v1.0 PR-3/4) to make
    a deliberate choice instead of inheriting a default.
    """
    live = _enumerate_web_routes()
    classified = set(_WEB_ROUTE_CLASSIFICATION.keys())
    missing_in_table = sorted(live - classified)
    stale_in_table = sorted(classified - live)
    assert not missing_in_table, (
        "/web routes registered on the app but not classified in "
        f"_WEB_ROUTE_CLASSIFICATION: {missing_in_table}"
    )
    assert not stale_in_table, (
        f"_WEB_ROUTE_CLASSIFICATION lists routes that no longer exist: "
        f"{stale_in_table}"
    )


def test_web_routes_are_not_registered_twice() -> None:
    counts = _enumerate_web_route_counts()
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    assert not duplicates, f"duplicate /web route registrations: {duplicates}"


@pytest.mark.parametrize("method,path", _writer_only_paths())
def test_writer_only_routes_actually_check_writer(method: str, path: str) -> None:
    """``writer-only`` classification must be backed by endpoint code."""
    endpoint = _route_endpoint(method, path)
    assert endpoint is not None, f"endpoint not found: {method} {path}"
    source = inspect.getsource(endpoint)
    assert "_require_selected_ledger_write(" in source, (
        f"{method} {path} is classified as writer-only but its handler "
        f"({endpoint.__module__}.{endpoint.__name__}) does not reference "
        "_require_selected_ledger_write directly."
    )
