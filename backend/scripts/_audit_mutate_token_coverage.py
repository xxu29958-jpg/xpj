"""ADR-0038 mutate-token-coverage audit.

Walks the live OpenAPI schema (the same FastAPI app the smoke and
contract tests hit) and verifies every mutating route accepts an
optimistic-concurrency token — either a body field named
``expected_row_version`` or a batch token map
``expected_row_version_by_id``. Routes that legitimately do NOT take a
token (create endpoints, account-level admin actions that don't mutate
a versioned row, lifecycle no-ops, pure read-modify-emit endpoints)
live in the structured risk ledger (:mod:`_mutate_token_ledger`), each
with a controlled ``reason_code``, ``owner``, ``risk``, and the real
``touched_tables`` the route writes.

Why we need this: the v1.3 PR-2 series found two real "server added
the field but a client didn't" gaps (Android ``deleteCategoryRule``
from PR-1, ``/web/rules`` toggle/delete from PR-1, the entire
``acknowledge-mismatch`` surface from goal triage). Each one shipped
because no audit checked "does this mutate route have a token at
all". This lane closes that loop: every new mutate route either has
``expected_row_version`` in its body, or shows up explicitly in the
ledger with a reviewed ``reason_code``. Forgetting both fails the audit.

Naming convention follows :file:`release_audit.py`: drop this file
into ``backend/scripts/`` and the aggregator picks it up automatically.
The ledger data lives in the sibling ``_mutate_token_ledger.py`` (no
``_audit_`` prefix, so the aggregator doesn't run it as its own lane);
this script imports + validates it.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_mutate_token_coverage.py
"""

from __future__ import annotations

import pathlib
import sys

# Allow running from anywhere by anchoring sys.path on backend/ (for
# ``app.*`` imports) and on scripts/ (for the sibling ledger module).
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _mutate_token_ledger import (  # noqa: E402 — needs the sys.path bootstrap above
    ALLOWLIST,
    review_overdue,
    risk_histogram,
    validate_ledger,
)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Pre-existing PATCH / DELETE / PUT routes that legitimately COULD use
# optimistic-concurrency tokens but pre-date ADR-0038 and don't yet.
# Audit emits these as WARN — not FAIL — so a route can be parked here
# mid-migration. NEW mutating routes that should have a token must
# NOT be added here — add the token instead. Set
# XPJ_AUDIT_MUTATE_TOKEN_STRICT=1 to gate strictly (turn WARNs into
# FAILs).
#
# v1.3 PR-2j paid down the original 6 entries: 2 routes now carry the
# token (goals PATCH / income-plans PATCH) so they're auto-detected
# as TOKEN carriers; 4 moved to the ledger with explicit reason_codes
# (upsert / replace-all / archive lifecycle). The set is empty and
# strict mode is the working default.
KNOWN_GAPS: frozenset[str] = frozenset()

# Routes that ARE expected to carry the token but the audit can't see
# it via the schema alone (e.g. a query-string token, a header). We
# do not currently expose any such route — if you add one, document
# it here so the audit doesn't get confused.
QUERY_STRING_TOKEN_ROUTES: frozenset[str] = frozenset()

TOKEN_FIELD_NAMES = frozenset({"expected_row_version", "expected_row_version_by_id"})


def _load_openapi_app_schema() -> dict:
    """Import the live FastAPI app and emit its OpenAPI schema in-process.

    This is the same schema the contract snapshot is generated from;
    importing it here means the audit catches a new route in the same
    breath the route lands.
    """
    from app.main import app  # noqa: F401 — populates router

    return app.openapi()


def _resolve_ref(spec: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    node: dict | list = spec
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, {})
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _schema_carries_token(spec: dict, schema: dict, depth: int = 0) -> bool:
    """Return True if the schema (or any inlined sub-schema) declares
    one of :data:`TOKEN_FIELD_NAMES` as a property."""
    if not schema or depth > 5:
        return False
    if "$ref" in schema:
        return _schema_carries_token(spec, _resolve_ref(spec, schema["$ref"]), depth + 1)
    if "properties" in schema and any(
        name in schema["properties"] for name in TOKEN_FIELD_NAMES
    ):
        return True
    # ``oneOf`` / ``anyOf`` / ``allOf`` — accept if any variant carries.
    for combinator in ("oneOf", "anyOf", "allOf"):
        for variant in schema.get(combinator, []):
            if _schema_carries_token(spec, variant, depth + 1):
                return True
    return False


_RELEVANT_MEDIA = ("json", "x-www-form-urlencoded", "form-data")


def _operation_carries_token(spec: dict, operation: dict) -> bool:
    body = operation.get("requestBody")
    if not body:
        return False
    content = body.get("content", {})
    for media_type, media in content.items():
        media_lower = media_type.lower()
        if not any(marker in media_lower for marker in _RELEVANT_MEDIA):
            continue
        if _schema_carries_token(spec, media.get("schema", {})):
            return True
    return False


def _iter_routes(spec: dict) -> list[tuple[str, str, dict]]:
    routes: list[tuple[str, str, dict]] = []
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method.upper() not in MUTATING_METHODS:
                continue
            routes.append((method.upper(), path, operation))
    return routes


def _strict_gate_enabled() -> bool:
    """Default-on: KNOWN_GAPS entries FAIL the audit (not WARN).

    ADR-0038 PR-2j paid down all the v1.1 sediment, so strict is the
    working default. ``XPJ_AUDIT_MUTATE_TOKEN_STRICT=0`` flips it
    back to WARN — only useful when a route is genuinely mid-
    migration and you need the audit to ride along without blocking.
    """
    import os

    return os.environ.get("XPJ_AUDIT_MUTATE_TOKEN_STRICT", "1") == "1"


def _bucket_routes(
    spec: dict,
) -> tuple[list[str], list[str], list[str], set[str], set[str], int]:
    """Split mutate routes into (new-gaps, known-gaps, allowlist-but-
    actually-carries-token, unused-allowlist, unused-known,
    token-carrier-count). Pulled out of ``main`` to keep it under the
    audit-script complexity budget.

    The third bucket exists so a ledger entry that has since grown a
    real ``expected_row_version`` body field is flagged as a stale
    exemption rather than silently masking a regression — the schema
    is now the authoritative signal for that route, the ledger entry
    would only matter again if someone removes the token. Keep the
    ledger focused on routes that genuinely have no token.
    """
    missing_new: list[str] = []
    missing_known: list[str] = []
    allowlist_but_has_token: list[str] = []
    unused_allowlist = set(ALLOWLIST)
    unused_known_gaps = set(KNOWN_GAPS)
    token_carriers = 0

    for method, path, operation in _iter_routes(spec):
        key = f"{method} {path}"
        carries_token = _operation_carries_token(spec, operation)
        if key in ALLOWLIST:
            unused_allowlist.discard(key)
            if carries_token:
                allowlist_but_has_token.append(key)
            continue
        if path in QUERY_STRING_TOKEN_ROUTES:
            continue
        if carries_token:
            token_carriers += 1
            continue
        if key in KNOWN_GAPS:
            unused_known_gaps.discard(key)
            missing_known.append(key)
            continue
        missing_new.append(key)

    return (
        missing_new,
        missing_known,
        allowlist_but_has_token,
        unused_allowlist,
        unused_known_gaps,
        token_carriers,
    )


def _emit_ledger_failures(ledger_problems: list[str], overdue: list[str]) -> bool:
    """Print ledger-shape + review-cadence failures; return whether any fired."""
    failed = False

    if ledger_problems:
        failed = True
        print("FAIL: mutate-token exemption ledger is not well-formed:")
        for problem in ledger_problems:
            print(f"  - {problem}")

    if overdue:
        failed = True
        print("\nFAIL: mutate-token exemption review is overdue:")
        for line in overdue:
            print(f"  - {line}")

    return failed


def _emit_route_failures(
    *,
    allowlist_but_has_token: list[str],
    missing_new: list[str],
    missing_known: list[str],
    unused_allowlist: set[str],
    unused_known_gaps: set[str],
    strict: bool,
) -> bool:
    """Print coverage failures (token gaps / stale ledger entries).

    Kept separate from ``main`` and from the ledger-shape lane so each
    stays under the audit-script complexity budget (C901).
    """
    failed = False

    if allowlist_but_has_token:
        failed = True
        print(
            "\nFAIL: ledger routes that actually DO carry "
            "``expected_row_version`` in their schema. Remove from the "
            "ledger so the schema is the authoritative signal — keeping "
            "the entry would silently mask a regression if the token "
            "field were ever removed from the route:"
        )
        for key in sorted(allowlist_but_has_token):
            print(f"  - {key} ({ALLOWLIST[key].reason_code})")

    if missing_new:
        failed = True
        print("\nFAIL: NEW mutate routes missing ``expected_row_version`` body field:")
        for line in sorted(missing_new):
            print(f"  - {line}")
        print(
            "\nFix: add ``expected_row_version: int`` to the request "
            "schema (ADR-0038 PR-1 / PR-2 pattern), wire the service to "
            "``claim_row_with_token`` / ``delete_row_with_token``, and "
            "add a contract test. If the route legitimately cannot use a "
            "token (create, terminal lifecycle, batch with its own "
            "guard), add it to the ledger in _mutate_token_ledger.py with "
            "a reason_code."
        )

    if missing_known:
        prefix = "FAIL" if strict else "WARN"
        if strict:
            failed = True
        print(
            f"\n{prefix}: pre-ADR-0038 mutate routes without token (KNOWN_GAPS — "
            f"sediment to pay down):"
        )
        for line in sorted(missing_known):
            print(f"  - {line}")

    if unused_allowlist:
        failed = True
        print(
            "\nFAIL: ledger entries that no longer match any registered route. "
            "Remove the stale entries — keeping them dilutes the ledger's signal:"
        )
        for key in sorted(unused_allowlist):
            print(f"  - {key} ({ALLOWLIST[key].reason_code})")

    if unused_known_gaps:
        failed = True
        print(
            "\nFAIL: KNOWN_GAPS entries that no longer match any registered "
            "route. Remove them — the gap was either closed or the route was "
            "renamed:"
        )
        for key in sorted(unused_known_gaps):
            print(f"  - {key}")

    return failed


def main() -> int:
    spec = _load_openapi_app_schema()
    routes = _iter_routes(spec)

    # Validate the ledger itself now that importing the app has
    # registered every model (so touched_tables can be cross-checked
    # against the live ``__tablename__`` set).
    from app.database import Base

    ledger_problems = validate_ledger(set(Base.metadata.tables.keys()))
    overdue = review_overdue()

    (
        missing_new,
        missing_known,
        allowlist_but_has_token,
        unused_allowlist,
        unused_known_gaps,
        token_carriers,
    ) = _bucket_routes(spec)

    ledger_failed = _emit_ledger_failures(ledger_problems, overdue)
    route_failed = _emit_route_failures(
        allowlist_but_has_token=allowlist_but_has_token,
        missing_new=missing_new,
        missing_known=missing_known,
        unused_allowlist=unused_allowlist,
        unused_known_gaps=unused_known_gaps,
        strict=_strict_gate_enabled(),
    )
    if ledger_failed or route_failed:
        return 1

    total = len(routes)
    hist = risk_histogram()
    print(
        f"OK: {total} mutate routes audited; "
        f"{token_carriers} carry ``expected_row_version``, "
        f"{len(ALLOWLIST)} explicitly exempted "
        f"({hist['high']} high / {hist['medium']} medium / {hist['low']} low risk), "
        f"{len(KNOWN_GAPS)} grandfathered as known gaps."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
