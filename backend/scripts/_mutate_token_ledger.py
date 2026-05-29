"""Structured risk ledger for the mutate-token-coverage audit.

This is the data + schema half of the ADR-0038 mutate-token lane;
:file:`_audit_mutate_token_coverage.py` is the logic half that imports
this module and gates CI. It is deliberately NOT named ``_audit_*`` so
the release-audit aggregator does not run it as a standalone lane and
the generic allowlist-reason lane does not double-scan it. The entries
here are validated by :func:`validate_ledger`, which the coverage lane
calls — with checks far stricter than the free-text reason lane:
controlled ``reason_code`` / ``owner`` / ``risk`` vocabularies,
``touched_tables`` cross-checked against the live ``__tablename__``
rows, and a reason_code↔touched_tables consistency rule that makes a
false "read-only" claim impossible to express.

Each entry answers, for one mutating route that does NOT carry an
``expected_updated_at`` token: why is the exemption safe, who owns it,
how risky is it, when must it be re-reviewed, and which tables does it
actually write. See ADR-0038.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# --- Controlled vocabularies ------------------------------------------------

# reason_code is the reviewed invariant, not free text: it names *why*
# the route needs no optimistic-concurrency token.
REASON_CODES: frozenset[str] = frozenset(
    {
        "create_row",            # inserts a brand-new row; no prior version exists
        "append_only_fact",      # appends to an append-only log / event table
        "terminal_flag_flip",    # flips a status/archived flag; state machine guards races
        "upsert_bucket",         # replaces a tenant/account-keyed bucket; single writer
        "batch_db_write",        # touches many rows; owns its own batch / preview contract
        "governance_action",     # permission-gated membership / invitation / role write
        "session_rotation",      # mints / rotates / consumes auth + identity rows
        "admin_single_writer",   # owner/admin single-writer edit (rename/rotate/extend/limits)
        "enqueue_task",          # inserts a background_tasks row; the worker does the real write
        "external_side_effect",  # writes filesystem / .env / network only — NO db row
        "read_only_compute",     # preview / computation — NO write at all
    }
)

# reason_codes whose routes write NO database row. For these
# touched_tables MUST be empty; for every other reason_code it MUST be
# non-empty. That pair of rules is the teeth: a route that writes a row
# cannot be parked as read_only_compute with no tables — the audit
# rejects the mismatch, so the "/web/import/preview said read-only but
# creates a batch" class of drift can no longer be expressed.
EMPTY_TABLE_REASON_CODES: frozenset[str] = frozenset(
    {"external_side_effect", "read_only_compute"}
)

# Owning subsystem (maps to a service / route family), so an exemption
# always has a clear "who reviews this".
OWNERS: frozenset[str] = frozenset(
    {
        "identity",
        "expenses",
        "imports",
        "rules",
        "recurring",
        "goals",
        "budget",
        "bill_split",
        "learning",
        "merchants",
        "maintenance",
        "owner_console",
        "exchange_rates",
        "tasks",
    }
)

RISKS: frozenset[str] = frozenset({"low", "medium", "high"})

# Review cadence is risk-tiered, not a fabricated per-route date: low is
# reviewed annually, medium semi-annually, high quarterly. The audit
# FAILS once a tier's date lapses, forcing the ledger to be re-walked
# instead of silently aging. Bump these forward when you do the review.
RISK_REVIEW_BY: dict[str, date] = {
    "low": date(2027, 5, 31),
    "medium": date(2026, 11, 30),
    "high": date(2026, 8, 31),
}


@dataclass(frozen=True)
class Exempt:
    """One row of the mutate-token exemption risk ledger.

    Positional order is fixed so the entries below stay scannable:
    ``Exempt(reason_code, owner, touched_tables, risk="low")``.
    ``touched_tables`` are the real ``__tablename__`` rows the route is
    known to write (verified primary targets; not guaranteed to list
    every downstream cascade). ``review_by`` is derived from ``risk``.
    """

    reason_code: str
    owner: str
    touched_tables: tuple[str, ...]
    risk: str = "low"

    @property
    def review_by(self) -> date:
        return RISK_REVIEW_BY[self.risk]


# Shared table-set constants keep entries on one line and DRY repeated
# blast radii. Every name is a SQLAlchemy ``__tablename__`` value and is
# cross-checked against the live metadata by :func:`validate_ledger`.
_PAIR_BIND = ("devices", "auth_tokens", "pairing_codes")
_BOOTSTRAP_IDENTITY = (
    "accounts",
    "ledgers",
    "ledger_members",
    "devices",
    "auth_tokens",
    "pairing_codes",
    "bootstrap_secret_consumptions",
)
_ACCEPT_INVITE = ("ledger_members", "invitations", "auth_tokens")
_SWITCH = ("auth_tokens", "devices")
_DEVICE_REVOKE = ("devices", "auth_tokens")
_DEVICE_CLEANUP = ("devices", "auth_tokens", "upload_links")
_PUBLIC_UPLOAD = ("expenses", "upload_link_daily_usage", "upload_link_remote_attempts")
_UPLOAD_LINKS = ("upload_links",)
_IMPORT_CREATE = ("csv_import_batches", "csv_import_rows")
_IMPORT_APPLY = ("expenses", "csv_import_batches", "csv_import_rows")
_RULES_APPLY = ("expenses", "rule_application_batches", "rule_application_changes")
_LEARNING_PRUNE = ("algorithm_decisions", "ledger_learning_events", "ocr_facts")
_SUGGESTION_EVENT = ("algorithm_decisions", "ledger_learning_events")
_ADVISOR_WRITE = ("budget_advisor_audit_logs", "budget_advisor_quota_locks")
_BUDGET_BUCKET = ("budgets", "budget_categories")
_LEDGER_CREATE = ("ledgers", "ledger_members")
_OWNER_TRANSFER = ("ledger_members", "ledgers")
_ALGO_DECISIONS = ("algorithm_decisions",)
_INCOME_PLAN = ("monthly_income_plans",)
_RECURRING = ("recurring_items",)
_BILL_SPLIT = ("bill_split_invitations",)
_DASHBOARD = ("dashboard_card_preferences",)


# Key format: ``"METHOD PATH"`` exactly as FastAPI registers it.
ALLOWLIST: dict[str, Exempt] = {
    # --- /api create routes (collection POST → new row, no prior version) ---
    "POST /api/auth/pair": Exempt("session_rotation", "identity", _PAIR_BIND, "medium"),
    "POST /api/auth/refresh": Exempt("session_rotation", "identity", ("auth_tokens",)),
    "POST /api/app/upload-screenshot": Exempt("create_row", "expenses", ("expenses",)),
    "POST /api/bootstrap/owner": Exempt("session_rotation", "identity", _BOOTSTRAP_IDENTITY, "medium"),
    "POST /api/bootstrap/pairing-codes": Exempt("create_row", "identity", ("pairing_codes",)),
    "POST /api/expenses/manual": Exempt("create_row", "expenses", ("expenses",)),
    "POST /api/expenses/notification-drafts": Exempt("create_row", "expenses", ("expenses",)),
    "POST /api/expenses/{expense_id}/split-invite": Exempt("create_row", "bill_split", _BILL_SPLIT),
    "POST /api/goals": Exempt("create_row", "goals", ("goals",)),
    "POST /api/imports/csv": Exempt("create_row", "imports", _IMPORT_CREATE),
    "POST /api/income-plans": Exempt("create_row", "budget", _INCOME_PLAN),
    "POST /api/invitations/preview": Exempt("read_only_compute", "identity", ()),
    "POST /api/invitations/accept": Exempt("session_rotation", "identity", _ACCEPT_INVITE, "medium"),
    "POST /api/ledgers": Exempt("create_row", "identity", _LEDGER_CREATE),
    "POST /api/ledgers/{ledger_id}/invitations": Exempt("create_row", "identity", ("invitations",)),
    "POST /api/merchants/aliases": Exempt("create_row", "merchants", ("merchant_aliases",)),
    "POST /api/recurring/from-candidate": Exempt("create_row", "recurring", _RECURRING),
    "POST /api/rules/categories": Exempt("create_row", "rules", ("category_rules",)),
    "POST /u/{upload_key}": Exempt("create_row", "expenses", _PUBLIC_UPLOAD, "medium"),

    # --- /api admin devices / upload-links (account-scoped owner admin) ---
    "POST /api/admin/devices/{public_id}/rename": Exempt("admin_single_writer", "identity", ("devices",)),
    "POST /api/admin/devices/{public_id}/revoke": Exempt("terminal_flag_flip", "identity", _DEVICE_REVOKE, "medium"),
    "POST /api/admin/upload-links": Exempt("create_row", "identity", _UPLOAD_LINKS),
    "POST /api/admin/upload-links/{public_id}/revoke": Exempt("terminal_flag_flip", "identity", _UPLOAD_LINKS),
    "POST /api/admin/upload-links/{public_id}/rotate": Exempt("admin_single_writer", "identity", _UPLOAD_LINKS, "medium"),
    "POST /api/admin/upload-links/{public_id}/extend": Exempt("admin_single_writer", "identity", _UPLOAD_LINKS),

    # --- /api lifecycle terminal / append-only flows ---
    "POST /api/bill-splits/{public_id}/accept": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT, "medium"),
    "POST /api/bill-splits/{public_id}/reject": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT),
    "POST /api/bill-splits/{public_id}/cancel": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT),
    "POST /api/expenses/{expense_id}/suggestions/{decision_public_id}/accept": Exempt(
        "append_only_fact", "learning", _SUGGESTION_EVENT
    ),
    "POST /api/expenses/{expense_id}/suggestions/{decision_public_id}/reject": Exempt(
        "append_only_fact", "learning", _SUGGESTION_EVENT
    ),
    "POST /api/goals/{public_id}/archive": Exempt("terminal_flag_flip", "goals", ("goals",)),
    "POST /api/income-plans/{public_id}/restore": Exempt("terminal_flag_flip", "budget", _INCOME_PLAN),
    "POST /api/recurring/items/{public_id}/archive": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /api/recurring/items/{public_id}/pause": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /api/recurring/items/{public_id}/resume": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /api/tasks/{public_id}/cancel": Exempt("terminal_flag_flip", "tasks", ("background_tasks",)),

    # --- /api batch / maintenance / preview / advisor / session ---
    "POST /api/budget/advise": Exempt("append_only_fact", "budget", _ADVISOR_WRITE, "high"),
    "POST /api/imports/csv/{public_id}/apply": Exempt("batch_db_write", "imports", _IMPORT_APPLY, "medium"),
    "POST /api/ledgers/{ledger_id}/switch": Exempt("session_rotation", "identity", _SWITCH),
    "POST /api/maintenance/cleanup-ai-advisor-audit": Exempt(
        "batch_db_write", "maintenance", ("budget_advisor_audit_logs",)
    ),
    "POST /api/maintenance/cleanup-devices": Exempt("batch_db_write", "maintenance", _DEVICE_CLEANUP, "medium"),
    "POST /api/maintenance/cleanup-images": Exempt("batch_db_write", "maintenance", ("expenses",)),
    "POST /api/maintenance/cleanup-learning": Exempt("batch_db_write", "maintenance", _LEARNING_PRUNE, "medium"),
    "POST /api/maintenance/cleanup-orphans": Exempt("external_side_effect", "maintenance", ()),
    "POST /api/maintenance/cleanup-rejected": Exempt("batch_db_write", "maintenance", ("expenses",)),
    "POST /api/rules/apply-confirmed": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /api/rules/apply-pending": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /api/rules/apply-pending/preview": Exempt("read_only_compute", "rules", ()),
    "POST /api/rules/applications/{public_id}/rollback": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /api/rules/preview": Exempt("read_only_compute", "rules", ()),

    # --- /api governance (permission-gated membership / invitations / rates) ---
    "POST /api/ledgers/{ledger_id}/invitations/{public_id}/revoke": Exempt(
        "governance_action", "identity", ("invitations",)
    ),
    "POST /api/ledgers/{ledger_id}/members/{member_id}/disable": Exempt(
        "governance_action", "identity", ("ledger_members",), "medium"
    ),
    "POST /api/ledgers/{ledger_id}/members/{member_id}/role": Exempt(
        "governance_action", "identity", ("ledger_members",), "medium"
    ),
    "POST /api/ledgers/{ledger_id}/members/{member_id}/transfer-owner": Exempt(
        "governance_action", "identity", _OWNER_TRANSFER, "high"
    ),
    "PUT /api/exchange-rates/{currency_code}/{rate_date}": Exempt(
        "upsert_bucket", "exchange_rates", ("exchange_rates",)
    ),

    # --- /api upsert / replace-all / lifecycle (tenant/account-keyed bucket) ---
    "DELETE /api/income-plans/{public_id}": Exempt("terminal_flag_flip", "budget", _INCOME_PLAN),
    "PUT /api/budgets/monthly/{month}": Exempt("upsert_bucket", "budget", _BUDGET_BUCKET),
    "PUT /api/dashboard/cards": Exempt("upsert_bucket", "budget", _DASHBOARD),
    "PUT /api/me/ui-preferences": Exempt("upsert_bucket", "identity", ("user_ui_preferences",)),

    # --- /web mutate forms / create / batch / terminal ---
    "POST /web/budgets/save": Exempt("upsert_bucket", "budget", _BUDGET_BUCKET),
    "POST /web/budget-advise": Exempt("append_only_fact", "budget", _ADVISOR_WRITE, "high"),
    "POST /web/bill-splits/{public_id}/accept": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT, "medium"),
    "POST /web/bill-splits/{public_id}/cancel": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT),
    "POST /web/bill-splits/{public_id}/reject": Exempt("terminal_flag_flip", "bill_split", _BILL_SPLIT),
    "POST /web/categories/uncategorized/bulk-set": Exempt("batch_db_write", "expenses", ("expenses",)),
    "POST /web/dashboard/cards/reset": Exempt("upsert_bucket", "budget", _DASHBOARD),
    "POST /web/dashboard/cards/save": Exempt("upsert_bucket", "budget", _DASHBOARD),
    "POST /web/expenses/{expense_id}/split-invite": Exempt("create_row", "bill_split", _BILL_SPLIT),
    "POST /web/goals/create": Exempt("create_row", "goals", ("goals",)),
    "POST /web/goals/{public_id}/archive": Exempt("terminal_flag_flip", "goals", ("goals",)),
    "POST /web/import/preview": Exempt("create_row", "imports", _IMPORT_CREATE),
    "POST /web/import/confirm": Exempt("batch_db_write", "imports", _IMPORT_APPLY, "medium"),
    "POST /web/import/{public_id}/apply": Exempt("batch_db_write", "imports", _IMPORT_APPLY, "medium"),
    "POST /web/income-plans/create": Exempt("create_row", "budget", _INCOME_PLAN),
    "POST /web/income-plans/{public_id}/archive": Exempt("terminal_flag_flip", "budget", _INCOME_PLAN),
    "POST /web/income-plans/{public_id}/restore": Exempt("terminal_flag_flip", "budget", _INCOME_PLAN),
    "POST /web/merchants/aliases/create": Exempt("create_row", "merchants", ("merchant_aliases",)),
    "POST /web/pending/batch-reject": Exempt("batch_db_write", "expenses", ("expenses",)),
    "POST /web/recurring/confirm-candidate": Exempt("create_row", "recurring", _RECURRING),
    "POST /web/recurring/{public_id}/archive": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /web/recurring/{public_id}/pause": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /web/recurring/{public_id}/resume": Exempt("terminal_flag_flip", "recurring", _RECURRING),
    "POST /web/review/bulk": Exempt("batch_db_write", "expenses", ("expenses",)),
    "POST /web/rules/applications/{public_id}/rollback": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /web/rules/apply-confirmed": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /web/rules/apply-pending": Exempt("batch_db_write", "rules", _RULES_APPLY, "medium"),
    "POST /web/rules/create": Exempt("create_row", "rules", ("category_rules",)),
    "POST /web/tasks/{public_id}/cancel": Exempt("terminal_flag_flip", "tasks", ("background_tasks",)),

    # --- /owner console (loopback-only admin / single-writer / batch) ---
    "POST /owner/ai-advisor/confirmation": Exempt("external_side_effect", "owner_console", (), "medium"),
    "POST /owner/algorithm-versions/withdraw": Exempt("batch_db_write", "learning", _ALGO_DECISIONS, "medium"),
    "POST /owner/backups": Exempt("external_side_effect", "owner_console", ()),
    "POST /owner/devices/{public_id}/delete": Exempt("terminal_flag_flip", "owner_console", _DEVICE_REVOKE, "medium"),
    "POST /owner/devices/{public_id}/rename": Exempt("admin_single_writer", "owner_console", ("devices",)),
    "POST /owner/devices/{public_id}/revoke": Exempt("terminal_flag_flip", "owner_console", _DEVICE_REVOKE),
    "POST /owner/learning-maintenance/dismiss-decision": Exempt(
        "terminal_flag_flip", "learning", _ALGO_DECISIONS
    ),
    "POST /owner/learning-maintenance/run": Exempt("batch_db_write", "learning", _LEARNING_PRUNE, "medium"),
    "POST /owner/ledgers": Exempt("create_row", "owner_console", _LEDGER_CREATE),
    "POST /owner/ledgers/{ledger_id}/invitations": Exempt("create_row", "owner_console", ("invitations",)),
    "POST /owner/ledgers/{ledger_id}/invitations/{public_id}/revoke": Exempt(
        "governance_action", "owner_console", ("invitations",)
    ),
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/disable": Exempt(
        "governance_action", "owner_console", ("ledger_members",), "medium"
    ),
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/role": Exempt(
        "governance_action", "owner_console", ("ledger_members",), "medium"
    ),
    "POST /owner/ledgers/{ledger_id}/members/{member_id}/transfer-owner": Exempt(
        "governance_action", "owner_console", _OWNER_TRANSFER, "high"
    ),
    "POST /owner/migration-readiness/cut-over": Exempt("enqueue_task", "owner_console", ("background_tasks",), "high"),
    "POST /owner/migration-readiness/pre-v1-backup": Exempt("external_side_effect", "owner_console", ()),
    "POST /owner/pairing": Exempt("create_row", "owner_console", ("pairing_codes",)),
    "POST /owner/settings/public-base-url": Exempt("external_side_effect", "owner_console", ()),
    "POST /owner/upload-links": Exempt("create_row", "owner_console", _UPLOAD_LINKS),
    "POST /owner/upload-links/{public_id}/delete": Exempt("terminal_flag_flip", "owner_console", _UPLOAD_LINKS),
    "POST /owner/upload-links/{public_id}/limits": Exempt("admin_single_writer", "owner_console", _UPLOAD_LINKS),
    "POST /owner/upload-links/{public_id}/revoke": Exempt("terminal_flag_flip", "owner_console", _UPLOAD_LINKS),
    "POST /owner/upload-links/{public_id}/rotate": Exempt("admin_single_writer", "owner_console", _UPLOAD_LINKS, "medium"),
    "POST /owner/upload-links/{public_id}/extend": Exempt("admin_single_writer", "owner_console", _UPLOAD_LINKS),
}


def validate_entries(entries: dict[str, Exempt], real_table_names: set[str]) -> list[str]:
    """Return human-readable problems with ``entries``; empty list == OK.

    Enforces the structured contract that free text could not: known
    ``reason_code`` / ``owner`` / ``risk``, ``touched_tables`` that name
    only real tables, and the empty-iff-no-write consistency rule. Pure
    over its arguments so it can be exercised with crafted bad entries.
    """
    problems: list[str] = []
    for key, entry in entries.items():
        if entry.reason_code not in REASON_CODES:
            problems.append(f"{key}: unknown reason_code {entry.reason_code!r}")
        if entry.owner not in OWNERS:
            problems.append(f"{key}: unknown owner {entry.owner!r}")
        if entry.risk not in RISKS:
            problems.append(f"{key}: unknown risk {entry.risk!r}")
        for table in entry.touched_tables:
            if table not in real_table_names:
                problems.append(f"{key}: touched_tables names unknown table {table!r}")
        is_empty = len(entry.touched_tables) == 0
        must_be_empty = entry.reason_code in EMPTY_TABLE_REASON_CODES
        if must_be_empty and not is_empty:
            problems.append(
                f"{key}: reason_code {entry.reason_code!r} writes no row - touched_tables must be empty"
            )
        if not must_be_empty and is_empty:
            problems.append(
                f"{key}: reason_code {entry.reason_code!r} writes rows - touched_tables must list >=1 table"
            )
        path = key.split(" ", 1)[1] if " " in key else ""
        if entry.owner == "owner_console" and not path.startswith("/owner/"):
            problems.append(f"{key}: owner 'owner_console' is only valid for /owner routes")
    return problems


def validate_ledger(real_table_names: set[str]) -> list[str]:
    """Validate the module-level :data:`ALLOWLIST` against the live tables."""
    return validate_entries(ALLOWLIST, real_table_names)


def review_overdue(today: date | None = None) -> list[str]:
    """Return overdue review tiers (review_by < today), newest policy first."""
    today = today or date.today()
    return [
        f"risk '{risk}': review_by {when.isoformat()} has lapsed - re-walk the ledger and bump RISK_REVIEW_BY"
        for risk, when in sorted(RISK_REVIEW_BY.items())
        if when < today
    ]


def risk_histogram() -> dict[str, int]:
    """Count exemptions per risk tier for the audit's OK summary line."""
    counts = dict.fromkeys(RISKS, 0)
    for entry in ALLOWLIST.values():
        counts[entry.risk] = counts.get(entry.risk, 0) + 1
    return counts
