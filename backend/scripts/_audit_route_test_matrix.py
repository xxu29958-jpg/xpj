"""v1.1 Batch 3: route test-matrix coverage gate.

Every route registered under :data:`app.main.app` should have a test
file that exercises it. Mutating routes (POST / PUT / PATCH / DELETE)
should additionally have a no-auth rejection test (i.e. some test
calls that exact path WITHOUT an ``Authorization`` header and expects
401), so an auth regression can't ship silently. The test corpus must
also carry explicit security markers for cross-ledger, viewer-write,
and existence-hiding coverage so those categories stay visible in CI.

This is a heuristic — it cannot prove that a test really enforces
cross-ledger isolation or 404-no-existence — but it catches the cheap
class of "route exists, no test references it" gap.

Two failure modes:

* **No test references the route at all** (the path string never
  appears in any ``test_*.py``) — counts as a hard FAIL.
* **The route is mutating but no test in the corpus pairs that path
  with a ``401``** — printed as a WARN. Existing v1.0 routes carry
  this gap inconsistently; only newly-added entries are required to
  fix it before merging (use ``KNOWN_GAPS`` as a sediment list).

Adding a route that legitimately needs no test (health, static
mounts) → add its path to :data:`ALLOWLIST` with a one-line reason.
Adding a route that needs a 401 test but doesn't have one yet → add
to :data:`KNOWN_GAPS` with the ticket / commit that introduced it.
"""

from __future__ import annotations

import pathlib
import re
import sys

# Allow running from anywhere by anchoring sys.path on backend/.
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Routes that don't need a dedicated coverage test (health probes,
# legacy detectors, static mounts).
ALLOWLIST: dict[str, str] = {
    "/api/health": "loopback health probe — no data surface",
    "/api/status/private": "internal status — exercised via /api/health",
    "/api/upload/check": "legacy retirement marker — see _reject_legacy_upload_endpoint",
    "/api/upload-screenshot": "legacy retirement marker — see _reject_legacy_upload_endpoint",
    # Cross-cutting routes whose coverage lives under a sibling
    # surface; the audit's grep heuristic can't see the link.
    "/api/bill-splits/inbox": "covered by test_bill_split.py inbox_router fixture",
    "/api/bill-splits/{public_id}/accept": "covered by test_bill_split.py",
    "/api/bill-splits/{public_id}/reject": "covered by test_bill_split.py",
    "/owner/settings/about": "static-render — covered via /owner _index test",
    "/owner/devices/{public_id}/delete": "covered by owner_console_members test",
    "/owner/upload-links/{public_id}/rotate": "covered by admin_devices_and_upload_links",
}

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# v1.0 routes that pre-date this audit and do not yet have an explicit
# 401-rejection test. NEW mutating routes should not be added here —
# add the test instead. Audit prints these as WARN, not FAIL, so the
# v1.1 cut-over is unblocked while the gap is paid down incrementally.
# A future ``XPJ_AUDIT_ROUTE_MATRIX_STRICT=1`` lane uses this set so
# only NEW gaps fail.
KNOWN_GAPS: frozenset[str] = frozenset()

SECURITY_MARKERS: dict[str, str] = {
    "auth-401": "# coverage: auth-401",
    "cross-ledger": "# coverage: cross-ledger",
    "viewer-write": "# coverage: viewer-write",
    "existence-404": "# coverage: existence-404",
}


def _route_index() -> list[tuple[str, str, str]]:
    """Return the list of (method, path, handler-name) registered on the
    FastAPI app. We import lazily so the audit can run without standing
    up the full request lifecycle.
    """

    from fastapi.routing import APIRoute

    from app.main import app  # noqa: F401 — populates the router

    routes: list[tuple[str, str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or ():
            routes.append((method.upper(), route.path, route.endpoint.__name__))
    return routes


def _path_pattern_for_grep(path: str) -> str:
    """Convert ``/api/imports/csv/{public_id}/apply`` into a regex that
    matches the same path with any literal substituted into the
    placeholder. Test code typically writes the path as an f-string."""

    parts = re.split(r"\{[^}]+\}", path)
    return ".+".join(re.escape(part) for part in parts)


def _grep_tests_for(pattern: str, tests_root: pathlib.Path) -> bool:
    regex = re.compile(pattern)
    for file in tests_root.rglob("test_*.py"):
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if regex.search(text):
            return True
    return False


def _grep_no_auth_check(path: str, tests_root: pathlib.Path) -> bool:
    """Loose heuristic: a test file mentions this path AND ``401`` in
    the same file. Doesn't validate the actual assertion shape — that's
    what code review is for — but flags the cheap missing-401-gate case.
    """

    pattern = _path_pattern_for_grep(path)
    path_regex = re.compile(pattern)
    for file in tests_root.rglob("test_*.py"):
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path_regex.search(text) and "401" in text:
            return True
    return False


def _grep_security_marker(marker: str, tests_root: pathlib.Path) -> bool:
    for file in tests_root.rglob("test_*.py"):
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if marker in text:
            return True
    return False


def _missing_security_markers(tests_root: pathlib.Path) -> list[str]:
    return [name for name, marker in SECURITY_MARKERS.items() if not _grep_security_marker(marker, tests_root)]


def _strict_401_gate_enabled() -> bool:
    import os

    return os.environ.get("XPJ_AUDIT_ROUTE_MATRIX_STRICT", "1") == "1"


def _new_401_gaps(missing_401: list[str]) -> list[str]:
    return [line for line in missing_401 if line.split(" ", 1)[1] not in KNOWN_GAPS]


def _collect_route_gaps(tests_root: pathlib.Path) -> tuple[list[str], list[str]]:
    missing_any: list[str] = []
    missing_401: list[str] = []
    # codex P2: 按 (method, path) 元组去重,不是按 path。同一 path 上 POST 和 PUT 必须
    # 各自独立验证 401 覆盖;此前只按 path 去重会让"POST 有 401 测试 + PUT 没"的 case
    # 静默通过。已知漏检例:PUT /api/expenses/{expense_id}/splits、PUT /api/dashboard/cards、
    # PUT /api/me/ui-preferences。
    seen: set[tuple[str, str]] = set()
    for method, path, handler in _route_index():
        if path in ALLOWLIST or not method:
            continue
        pattern = _path_pattern_for_grep(path)
        if not _grep_tests_for(pattern, tests_root):
            missing_any.append(f"{method} {path}  (handler: {handler})")
            continue
        key = (method, path)
        if key not in seen and method in MUTATING_METHODS:
            if path.startswith("/web/") or path.startswith("/owner/"):
                seen.add(key)
                continue
            if not _grep_no_auth_check(path, tests_root):
                missing_401.append(f"{method} {path}")
        seen.add(key)
    return missing_any, missing_401


def main() -> int:
    tests_root = pathlib.Path("tests")
    if not tests_root.is_dir():
        print("audit: tests/ directory not found — run from backend/", file=sys.stderr)
        return 1

    missing_any, missing_401 = _collect_route_gaps(tests_root)
    failed = False
    if missing_any:
        failed = True
        print("FAIL: routes with no test coverage:")
        for line in sorted(missing_any):
            print(f"  - {line}")

    new_401_gaps = _new_401_gaps(missing_401)
    if new_401_gaps:
        # Emit as WARN by default — these are best-practice gaps, not
        # missing coverage outright. CI lanes that want a hard gate can
        # set XPJ_AUDIT_ROUTE_MATRIX_STRICT=1.
        strict = _strict_401_gate_enabled()
        prefix = "FAIL" if strict else "WARN"
        print(f"{prefix}: mutating routes with no 401-rejection coverage:")
        for line in sorted(new_401_gaps):
            print(f"  - {line}")
        if strict:
            failed = True

    missing_markers = _missing_security_markers(tests_root)
    if missing_markers:
        failed = True
        print("FAIL: route security coverage markers missing:")
        for name in sorted(missing_markers):
            print(f"  - {name} ({SECURITY_MARKERS[name]})")

    if failed:
        print(
            "\nFix: add a test that POSTs/GETs the route, plus a "
            "no-auth call expecting 401. ALLOWLIST entries in this "
            "script document the few exceptions; KNOWN_GAPS is the "
            "sediment list for legacy gaps being paid down."
        )
        return 1

    print("OK: every route is referenced by a test file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
