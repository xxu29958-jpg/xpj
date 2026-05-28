"""ADR-0038 mutate-token-coverage audit.

Walks the live OpenAPI schema (the same FastAPI app the smoke and
contract tests hit) and verifies every mutating route accepts an
optimistic-concurrency token — either a body field named
``expected_updated_at`` or a batch token map
``expected_updated_at_by_id``. Routes that legitimately do NOT take a
token (create endpoints, account-level admin actions that don't mutate
a versioned row, lifecycle no-ops, pure read-modify-emit endpoints)
live in :data:`ALLOWLIST` with a one-line reason.

Why we need this: the v1.3 PR-2 series found two real "server added
the field but a client didn't" gaps (Android ``deleteCategoryRule``
from PR-1, ``/web/rules`` toggle/delete from PR-1, the entire
``acknowledge-mismatch`` surface from goal triage). Each one shipped
because no audit checked "does this mutate route have a token at
all". This lane closes that loop: every new mutate route either has
``expected_updated_at`` in its body, or shows up explicitly in
:data:`ALLOWLIST` with a reason. Forgetting both fails the audit.

Naming convention follows :file:`release_audit.py`: drop this file
into ``backend/scripts/`` and the aggregator picks it up automatically.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_mutate_token_coverage.py
"""

from __future__ import annotations

import pathlib
import sys

# Allow running from anywhere by anchoring sys.path on backend/.
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes that legitimately do NOT need ``expected_updated_at``. Each
# entry MUST have a one-line reason explaining why the row this route
# touches doesn't follow the ADR-0038 optimistic-concurrency contract
# (e.g. it creates a new row, it doesn't mutate a versioned row, the
# state machine has no race window, etc.).
#
# Key format: ``"METHOD PATH"`` exactly as FastAPI registers it.
ALLOWLIST: dict[str, str] = {
    # --- /api create routes (collection POST → 201). New row has no
    # prior version, optimistic concurrency doesn't apply.
    "POST /api/auth/pair": "create — new device-binding row",
    "POST /api/auth/refresh": "session refresh — no versioned row",
    "POST /api/app/upload-screenshot": "create — uploads a new expense",
    "POST /api/bootstrap/owner": "create — bootstrap owner identity",
    "POST /api/bootstrap/pairing-codes": "create — new pairing-code row",
    "POST /api/expenses/manual": "create — new row",
    "POST /api/expenses/notification-drafts": "create — new row",
    "POST /api/expenses/{expense_id}/split-invite": "create — new bill_split_invitation row",
    "POST /api/goals": "create — new savings-goal row",
    "POST /api/imports/csv": "create — new csv_import_batch row",
    "POST /api/income-plans": "create — new income-plan row",
    "POST /api/invitations/preview": "preview — read-only computation",
    "POST /api/invitations/accept": "accept invite — pre-bind identity flip, no row mutate",
    "POST /api/ledgers": "create — new ledger row",
    "POST /api/ledgers/{ledger_id}/invitations": "create — new invitation row",
    "POST /api/merchants/aliases": "create — new alias row",
    "POST /api/recurring/from-candidate": "create — new recurring-item row",
    "POST /api/rules/categories": "create — new rule row",
    "POST /u/{upload_key}": "public upload — create new expense",

    # --- /api admin devices / upload-links (account-scoped admin).
    # Owner-only, single-writer in practice.
    "POST /api/admin/devices/{public_id}/rename": "owner-only — single-writer rename",
    "POST /api/admin/devices/{public_id}/revoke": "owner-only — terminal revoke",
    "POST /api/admin/upload-links": "owner-only — create new upload-link",
    "POST /api/admin/upload-links/{public_id}/revoke": "owner-only — terminal revoke",
    "POST /api/admin/upload-links/{public_id}/rotate": "owner-only — rotate secret",
    "POST /api/admin/upload-links/{public_id}/extend": "owner-only — extend expiry without rotating secret",

    # --- /api lifecycle terminal / idempotent flows. State machine
    # rejects out-of-band transitions, no race window worth a token.
    "POST /api/bill-splits/{public_id}/accept": "terminal state — idempotent",
    "POST /api/bill-splits/{public_id}/reject": "terminal state",
    "POST /api/bill-splits/{public_id}/cancel": "terminal state",
    "POST /api/expenses/{expense_id}/suggestions/{decision_public_id}/accept":
        "learning decision — append-only fact, no versioned row mutate",
    "POST /api/expenses/{expense_id}/suggestions/{decision_public_id}/reject":
        "learning decision — append-only fact, no versioned row mutate",
    "POST /api/goals/{public_id}/archive": "archive — terminal flag flip",
    "POST /api/income-plans/{public_id}/restore": "restore — terminal flag flip",
    "POST /api/recurring/items/{public_id}/archive": "archive — terminal flag flip",
    "POST /api/recurring/items/{public_id}/pause": "pause — terminal flag flip",
    "POST /api/recurring/items/{public_id}/resume": "resume — terminal flag flip",
    "POST /api/tasks/{public_id}/cancel": "task cancel — own status enum",

    # --- /api batch / maintenance / preview / admin actions. No
    # per-row token because they touch many rows or no rows.
    "POST /api/budget/advise": "advisor — read-with-LLM, no row mutate",
    "POST /api/imports/csv/{public_id}/apply": "batch apply — owns its preview_token contract",
    "POST /api/ledgers/{ledger_id}/switch": "session-level ledger switch — no row mutate",
    "POST /api/maintenance/cleanup-ai-advisor-audit": "batch cleanup",
    "POST /api/maintenance/cleanup-images": "batch cleanup",
    "POST /api/maintenance/cleanup-learning": "batch cleanup",
    "POST /api/maintenance/cleanup-orphans": "batch cleanup",
    "POST /api/maintenance/cleanup-rejected": "batch cleanup",
    "POST /api/rules/apply-confirmed": "batch apply — own preview_token contract",
    "POST /api/rules/apply-pending": "batch apply — own preview_token contract",
    "POST /api/rules/apply-pending/preview": "preview — read-only computation",
    "POST /api/rules/applications/{public_id}/rollback":
        "rollback — own version field on rule_applications.status",
    "POST /api/rules/preview": "preview — read-only computation",

    # --- /api governance (members / invitations / rate-edits).
    # Owner / member governance is owner-console-only single-writer
    # in practice. Promote to per-row token once the owner-console
    # gets a second writer; today the contention isn't real.
    "POST /api/ledgers/{ledger_id}/invitations/{public_id}/revoke":
        "owner-console-only — terminal flag",
    "POST /api/ledgers/{ledger_id}/members/{member_id}/disable":
        "owner-console-only — terminal flag",
    "POST /api/ledgers/{ledger_id}/members/{member_id}/role":
        "owner-console-only — role assignment",
    "POST /api/ledgers/{ledger_id}/members/{member_id}/transfer-owner":
        "owner-console-only — terminal",
    "PUT /api/exchange-rates/{currency_code}/{rate_date}":
        "owner-console-only — manual rate edit",

    # --- /api upsert / replace-all / lifecycle surfaces (account-
    # level prefs, monthly-key budgets, dashboard layout, archive).
    # These are not per-row PATCHes — they overwrite a tenant/account-
    # keyed bucket OR are idempotent terminal lifecycle. ADR-0038
    # PR-2j confirmed these route shapes deliberately stay token-free.
    "DELETE /api/income-plans/{public_id}":
        "archive lifecycle — idempotent terminal, mirrors restore POST",
    "PUT /api/budgets/monthly/{month}":
        "upsert by (tenant, month) — replaces the whole monthly budget bucket",
    "PUT /api/dashboard/cards":
        "replace-all layout by (tenant, surface) — single writer per surface",
    "PUT /api/me/ui-preferences":
        "upsert single row per account — local UI cache, no cross-window contention",

    # --- /web mutate forms / create / batch / nav. The /web/<edit>
    # surface that DOES need per-row tokens already carries them and
    # is detected as TOKEN by this audit — those entries don't appear
    # here. What appears here are the create / batch / terminal flows
    # that don't gate on a specific row's version.
    "POST /web/budgets/save": "owner-console-only — single-writer monthly budget",
    "POST /web/budget-advise": "advisor — read-with-LLM, no row mutate",
    "POST /web/bill-splits/{public_id}/accept": "terminal state",
    "POST /web/bill-splits/{public_id}/cancel": "terminal state",
    "POST /web/bill-splits/{public_id}/reject": "terminal state",
    "POST /web/categories/uncategorized/bulk-set":
        "bulk classify uncategorized — operates on rows still in default category",
    # NOTE: ``POST /web/confirmed/batch-update`` is NOT in ALLOWLIST —
    # it carries ``expected_updated_at_by_id`` and must be detected as
    # a token carrier by ``_schema_carries_token``. Putting it here
    # would silently mask a regression if the token field were removed.
    "POST /web/dashboard/cards/reset": "reset dashboard — terminal default",
    "POST /web/dashboard/cards/save": "save dashboard layout — single writer",
    "POST /web/expenses/{expense_id}/split-invite": "create — new bill_split_invitation row",
    "POST /web/goals/create": "create — new savings-goal row",
    "POST /web/goals/{public_id}/archive": "archive — terminal flag flip",
    "POST /web/import/preview": "preview — read-only",
    "POST /web/import/confirm": "confirm preview — own preview_token contract",
    "POST /web/import/{public_id}/apply": "batch apply — own preview_token contract",
    "POST /web/income-plans/create": "create — new income-plan row",
    "POST /web/income-plans/{public_id}/archive": "archive — terminal flag flip",
    "POST /web/income-plans/{public_id}/restore": "restore — terminal flag flip",
    "POST /web/merchants/aliases/create": "create — new alias row",
    "POST /web/pending/batch-reject": "pending bulk reject — terminal state",
    "POST /web/recurring/confirm-candidate": "create — promote candidate to recurring item",
    "POST /web/recurring/{public_id}/archive": "archive — terminal flag flip",
    "POST /web/recurring/{public_id}/pause": "pause — terminal flag flip",
    "POST /web/recurring/{public_id}/resume": "resume — terminal flag flip",
    "POST /web/review/bulk": "pending bulk review — status-machine guarded",
    "POST /web/rules/applications/{public_id}/rollback":
        "rollback — own version field on rule_applications.status",
    "POST /web/rules/apply-confirmed": "batch apply — own preview_token contract",
    "POST /web/rules/apply-pending": "batch apply — own preview_token contract",
    "POST /web/rules/create": "create — new rule row",
    "POST /web/tasks/{public_id}/cancel": "task cancel — own status enum",

    # --- /owner console. All admin / single-writer / batch / create
    # actions. Promote to per-row token if owner-console ever runs
    # multi-writer.
    "POST /owner/ai-advisor/confirmation": "owner-console-only — privacy gate flip",
    "POST /owner/algorithm-versions/withdraw": "owner-console-only — terminal flag",
    "POST /owner/backups": "owner-console-only — snapshot batch",
    "POST /owner/devices/{public_id}/delete": "owner-console-only — terminal",
    "POST /owner/devices/{public_id}/rename": "owner-console-only — single-writer",
    "POST /owner/devices/{public_id}/revoke": "owner-console-only — terminal",
    "POST /owner/learning-maintenance/dismiss-decision":
        "owner-console-only — terminal flag",
    "POST /owner/learning-maintenance/run":
        "owner-console-only — maintenance batch",
    "POST /owner/ledgers": "owner-console-only — create",
    "POST /owner/ledgers/{ledger_id}/invitations": "owner-console-only — create",
    "POST /owner/ledgers/{ledger_id}/invitations/{public_id}/revoke":
        "owner-console-only — terminal flag",
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/disable":
        "owner-console-only — terminal flag",
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/role":
        "owner-console-only — role assignment",
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/transfer-owner":
        "owner-console-only — terminal",
    "POST /owner/migration-readiness/cut-over":
        "owner-console-only — one-shot cut-over",
    "POST /owner/migration-readiness/pre-v1-backup":
        "owner-console-only — backup snapshot",
    "POST /owner/pairing": "owner-console-only — create pairing-code",
    "POST /owner/settings/public-base-url":
        "owner-console-only — server config",
    "POST /owner/upload-links": "owner-console-only — create",
    "POST /owner/upload-links/{public_id}/delete": "owner-console-only — terminal",
    "POST /owner/upload-links/{public_id}/limits":
        "owner-console-only — single-writer rate-limit edit",
    "POST /owner/upload-links/{public_id}/revoke": "owner-console-only — terminal revoke",
    "POST /owner/upload-links/{public_id}/rotate": "owner-console-only — rotate secret",
    "POST /owner/upload-links/{public_id}/extend": "owner-console-only — extend expiry without rotating secret",
}

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
# as TOKEN carriers; 4 moved to ALLOWLIST with explicit reasons
# (upsert / replace-all / archive lifecycle). The set is empty and
# strict mode is the working default.
KNOWN_GAPS: frozenset[str] = frozenset()

# Routes that ARE expected to carry the token but the audit can't see
# it via the schema alone (e.g. a query-string token, a header). We
# do not currently expose any such route — if you add one, document
# it here so the audit doesn't get confused.
QUERY_STRING_TOKEN_ROUTES: frozenset[str] = frozenset()

TOKEN_FIELD_NAMES = frozenset({"expected_updated_at", "expected_updated_at_by_id"})


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

    The third bucket exists so an ALLOWLIST entry that has since grown
    a real ``expected_updated_at`` body field is flagged as a stale
    exemption rather than silently masking a regression — the schema
    is now the authoritative signal for that route, the allowlist
    entry would only matter again if someone removes the token. Keep
    the allowlist focused on routes that genuinely have no token.
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


def main() -> int:
    spec = _load_openapi_app_schema()
    routes = _iter_routes(spec)
    (
        missing_new,
        missing_known,
        allowlist_but_has_token,
        unused_allowlist,
        unused_known_gaps,
        token_carriers,
    ) = _bucket_routes(spec)

    failed = False
    strict = _strict_gate_enabled()

    if allowlist_but_has_token:
        failed = True
        print(
            "FAIL: routes in ALLOWLIST that actually DO carry "
            "``expected_updated_at`` in their schema. Remove from "
            "ALLOWLIST so the schema is the authoritative signal — "
            "keeping the entry would silently mask a regression if "
            "the token field were ever removed from the route:"
        )
        for key in sorted(allowlist_but_has_token):
            print(f"  - {key} ({ALLOWLIST[key]})")

    if missing_new:
        failed = True
        print("FAIL: NEW mutate routes missing ``expected_updated_at`` body field:")
        for line in sorted(missing_new):
            print(f"  - {line}")
        print(
            "\nFix: add ``expected_updated_at: datetime`` to the request "
            "schema (ADR-0038 PR-1 / PR-2 pattern), wire the service to "
            "``claim_row_with_token`` / ``delete_row_with_token``, and "
            "add a contract test. If the route legitimately cannot use a "
            "token (create, terminal lifecycle, batch with its own "
            "guard), add it to ALLOWLIST in this script with a reason."
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
            "\nFAIL: ALLOWLIST entries that no longer match any registered route. "
            "Remove the stale entries — keeping them dilutes the allowlist's signal:"
        )
        for key in sorted(unused_allowlist):
            print(f"  - {key} ({ALLOWLIST[key]})")

    if unused_known_gaps:
        failed = True
        print(
            "\nFAIL: KNOWN_GAPS entries that no longer match any registered "
            "route. Remove them — the gap was either closed or the route was "
            "renamed:"
        )
        for key in sorted(unused_known_gaps):
            print(f"  - {key}")

    if failed:
        return 1

    total = len(routes)
    print(
        f"OK: {total} mutate routes audited; "
        f"{token_carriers} carry ``expected_updated_at``, "
        f"{len(ALLOWLIST)} explicitly exempted, "
        f"{len(KNOWN_GAPS)} grandfathered as known gaps."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
