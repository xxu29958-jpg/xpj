"""Owner Console view-model helpers.

Aggregates data needed by the Owner Console HTML pages. These functions are
called exclusively from :mod:`app.routes.owner_console` and must never depend
on FastAPI Request or return HTTP responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Account, Expense, RecurringItem, UploadLink
from app.services.admin_service import (
    DeviceSummary,
    UploadLinkSecret,
    UploadLinkSummary,
    create_upload_link,
    delete_device,
    delete_upload_link,
    list_devices,
    list_upload_links,
    rename_device,
    revoke_device,
    revoke_upload_link,
    rotate_upload_link,
)
from app.services.data_quality_service import (
    DataQualitySummary,
    data_quality_summary,
)
from app.services.identity_service import (
    PairingCodeResult,
    create_pairing_code,
)
from app.services.budget_service import get_monthly_budget
from app.services.ledger_service import (
    LedgerSummary,
    create_ledger as ledger_service_create_ledger,
    ledger_member_counts,
    list_managed_ledgers_for_account,
)
from app.tenants import DEFAULT_TENANT_ID
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION
from app.services.time_service import current_month, now_utc


OWNER_CONSOLE_TIMEZONE = "Asia/Shanghai"


def _amount_yuan(amount_cents: int) -> str:
    return f"{int(amount_cents) / 100:.2f}"


@dataclass
class BudgetStatusVM:
    ledger_id: str
    ledger_name: str
    month: str
    configured: bool
    total_amount_cents: int
    spent_amount_cents: int
    remaining_amount_cents: int
    overspent_amount_cents: int
    spent_percent: int
    is_over_budget: bool
    category_over_count: int
    total_amount_yuan: str
    spent_amount_yuan: str
    remaining_amount_yuan: str
    overspent_amount_yuan: str


@dataclass
class ConsoleIndexVM:
    backend_version: str
    identity_schema: str
    database_status: str
    upload_dir_status: str
    owner_console_status: str
    pending_count: int
    confirmed_count: int
    account_name: str
    ledger_name: str
    active_device_count: int
    active_upload_link_count: int
    dq_summary: DataQualitySummary | None = None
    recurring_ops: RecurringOpsVM | None = None
    budget_status: BudgetStatusVM | None = None
    primary_tenant_id: str = DEFAULT_TENANT_ID


@dataclass
class RecurringOpsVM:
    active_count: int
    paused_count: int
    archived_count: int
    due_soon_count: int
    overdue_count: int
    notification_pending_count: int
    notification_recent_24h_count: int
    notification_incomplete_count: int


@dataclass
class RuleApplicationAuditRow:
    ledger_id: str
    ledger_name: str
    public_id: str
    status: str
    pending_scanned: int
    changed_count: int
    created_at: object
    rolled_back_at: object | None


@dataclass
class RuleApplicationAuditVM:
    ledger_choices: list[LedgerSummary]
    selected_ledger_id: str | None
    selected_ledger_name: str | None
    rows: list[RuleApplicationAuditRow]


def _owner_ledger_ids(db: Session) -> list[str]:
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return [row.ledger_id for row in list_managed_ledgers_for_account(db, account_id=owner_id)]


def _count_recurring(db: Session, ledger_ids: list[str], status: str) -> int:
    if not ledger_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == status)
        )
        or 0
    )


def get_recurring_ops(db: Session) -> RecurringOpsVM:
    ledger_ids = _owner_ledger_ids(db)
    if not ledger_ids:
        return RecurringOpsVM(
            active_count=0,
            paused_count=0,
            archived_count=0,
            due_soon_count=0,
            overdue_count=0,
            notification_pending_count=0,
            notification_recent_24h_count=0,
            notification_incomplete_count=0,
        )

    now = now_utc()
    today = now.date()
    soon = today + timedelta(days=7)
    notification_filter = Expense.source.like("通知草稿:%")
    due_soon = int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == "active")
            .where(RecurringItem.next_expected_date.is_not(None))
            .where(RecurringItem.next_expected_date >= today)
            .where(RecurringItem.next_expected_date <= soon)
        )
        or 0
    )
    overdue = int(
        db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id.in_(ledger_ids))
            .where(RecurringItem.status == "active")
            .where(RecurringItem.next_expected_date.is_not(None))
            .where(RecurringItem.next_expected_date < today)
        )
        or 0
    )
    notification_pending = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.status == "pending")
        )
        or 0
    )
    notification_recent = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.created_at >= now - timedelta(hours=24))
        )
        or 0
    )
    notification_incomplete = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(ledger_ids))
            .where(notification_filter)
            .where(Expense.status == "pending")
            .where((Expense.amount_cents.is_(None)) | (Expense.merchant.is_(None)))
        )
        or 0
    )
    return RecurringOpsVM(
        active_count=_count_recurring(db, ledger_ids, "active"),
        paused_count=_count_recurring(db, ledger_ids, "paused"),
        archived_count=_count_recurring(db, ledger_ids, "archived"),
        due_soon_count=due_soon,
        overdue_count=overdue,
        notification_pending_count=notification_pending,
        notification_recent_24h_count=notification_recent,
        notification_incomplete_count=notification_incomplete,
    )


def get_rule_application_audit(
    db: Session,
    *,
    ledger_id: str | None = None,
    limit: int = 20,
) -> RuleApplicationAuditVM:
    """Recent rule application batches for the Owner Console.

    This is a read-only audit view. It intentionally reuses the existing rule
    application list service and only allows ledgers the local owner account
    can already manage from the console.
    """
    from app.services.classify_service import list_rule_applications

    choices = list_console_ledger_choices(db)
    if not choices:
        return RuleApplicationAuditVM(
            ledger_choices=[],
            selected_ledger_id=None,
            selected_ledger_name=None,
            rows=[],
        )

    by_id = {row.ledger_id: row for row in choices}
    if ledger_id:
        selected = by_id.get(ledger_id)
        if selected is None:
            raise AppError("ledger_forbidden", "请选择一个有权限的账本。", status_code=403)
    else:
        selected = choices[0]

    batches = list_rule_applications(db, tenant_id=selected.ledger_id, limit=limit)
    rows = [
        RuleApplicationAuditRow(
            ledger_id=selected.ledger_id,
            ledger_name=selected.name,
            public_id=batch.public_id,
            status=batch.status,
            pending_scanned=batch.pending_scanned,
            changed_count=batch.changed_count,
            created_at=batch.created_at,
            rolled_back_at=batch.rolled_back_at,
        )
        for batch in batches
    ]
    return RuleApplicationAuditVM(
        ledger_choices=choices,
        selected_ledger_id=selected.ledger_id,
        selected_ledger_name=selected.name,
        rows=rows,
    )


def get_index_vm(db: Session) -> ConsoleIndexVM:
    cfg = get_settings()
    db_status = "ok"
    if cfg.database_url.startswith("sqlite:///"):
        from pathlib import Path

        db_path = Path(cfg.database_url[len("sqlite:///") :])
        db_status = "ok" if db_path.is_file() else "missing"

    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"

    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    ledger_choices = list_console_ledger_choices(db)
    primary_ledger = ledger_choices[0] if ledger_choices else None
    visible_ledger_ids = _visible_console_ledger_ids(db)

    pending_count = _expense_status_count(db, tenant_ids=visible_ledger_ids, status="pending")
    confirmed_count = _expense_status_count(db, tenant_ids=visible_ledger_ids, status="confirmed")

    visible_devices = list_devices(db, ledger_ids=visible_ledger_ids)
    active_devices = sum(1 for device in visible_devices if device.revoked_at is None)
    active_links = _active_upload_link_count(db, ledger_ids=visible_ledger_ids)

    primary_tenant_id = primary_ledger.ledger_id if primary_ledger else DEFAULT_TENANT_ID
    try:
        dq_summary: DataQualitySummary | None = data_quality_summary(
            db, tenant_id=primary_tenant_id
        )
    except Exception:
        dq_summary = None
    try:
        recurring_ops: RecurringOpsVM | None = get_recurring_ops(db)
    except Exception:
        recurring_ops = None
    try:
        budget_status = _budget_status_for_primary_ledger(db, primary_ledger)
    except Exception:
        budget_status = None

    return ConsoleIndexVM(
        backend_version=BACKEND_VERSION,
        identity_schema=IDENTITY_SCHEMA_VERSION,
        database_status=db_status,
        upload_dir_status=upload_status,
        owner_console_status="available",
        pending_count=pending_count,
        confirmed_count=confirmed_count,
        account_name=account.display_name if account else "（未初始化）",
        ledger_name=primary_ledger.name if primary_ledger else "（未初始化）",
        active_device_count=active_devices,
        active_upload_link_count=active_links,
        dq_summary=dq_summary,
        recurring_ops=recurring_ops,
        budget_status=budget_status,
        primary_tenant_id=primary_tenant_id,
    )


def _budget_status_for_primary_ledger(
    db: Session,
    primary_ledger: LedgerSummary | None,
) -> BudgetStatusVM | None:
    if primary_ledger is None:
        return None
    month = current_month(OWNER_CONSOLE_TIMEZONE)
    budget = get_monthly_budget(
        db,
        tenant_id=primary_ledger.ledger_id,
        month=month,
        timezone_name=OWNER_CONSOLE_TIMEZONE,
    )
    available_amount_cents = int(budget.total_amount_cents) + int(budget.rollover_amount_cents)
    spent_amount_cents = int(budget.spent_amount_cents)
    spent_percent = (
        round(spent_amount_cents / available_amount_cents * 100)
        if available_amount_cents > 0
        else 0
    )
    remaining_amount_cents = int(budget.remaining_amount_cents)
    overspent_amount_cents = int(budget.overspent_amount_cents)
    return BudgetStatusVM(
        ledger_id=primary_ledger.ledger_id,
        ledger_name=primary_ledger.name,
        month=month,
        configured=bool(budget.configured),
        total_amount_cents=available_amount_cents,
        spent_amount_cents=spent_amount_cents,
        remaining_amount_cents=remaining_amount_cents,
        overspent_amount_cents=overspent_amount_cents,
        spent_percent=spent_percent,
        is_over_budget=overspent_amount_cents > 0 or remaining_amount_cents < 0,
        category_over_count=sum(1 for item in budget.category_budgets if item.overspent_amount_cents > 0),
        total_amount_yuan=_amount_yuan(available_amount_cents),
        spent_amount_yuan=_amount_yuan(spent_amount_cents),
        remaining_amount_yuan=_amount_yuan(remaining_amount_cents),
        overspent_amount_yuan=_amount_yuan(overspent_amount_cents),
    )


def get_devices(db: Session) -> list[DeviceSummary]:
    return list_devices(db, ledger_ids=_visible_console_ledger_ids(db))


def do_revoke_device(db: Session, public_id: str, current_device_public_id: str) -> DeviceSummary:
    return revoke_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def do_delete_device(db: Session, public_id: str, current_device_public_id: str) -> None:
    delete_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def do_rename_device(db: Session, public_id: str, new_name: str) -> DeviceSummary:
    return rename_device(
        db,
        public_id=public_id,
        new_name=new_name,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def get_upload_links(db: Session) -> list[UploadLinkSummary]:
    visible_ids = _visible_console_ledger_ids(db)
    if not visible_ids:
        return []
    return list_upload_links(db, ledger_ids=visible_ids)


def do_create_upload_link(
    db: Session, *, ledger_id: str, admin_account_id: int, default_timezone: str
) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return create_upload_link(
        db,
        ledger_id=ledger_id,
        admin_account_id=admin_account_id,
        default_timezone=default_timezone,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def do_rotate_upload_link(db: Session, public_id: str) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return rotate_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def do_revoke_upload_link(db: Session, public_id: str) -> UploadLinkSummary:
    return revoke_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def do_delete_upload_link(db: Session, public_id: str) -> None:
    delete_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_visible_console_ledger_ids(db),
    )


def compose_public_upload_url(secret: UploadLinkSecret) -> str | None:
    """Return the absolute public URL for an UploadLink secret.

    Combines :envvar:`PUBLIC_BASE_URL` with the relative ``upload_url_path``
    produced by :mod:`app.services.admin_service`. Returns ``None`` when
    ``PUBLIC_BASE_URL`` is not configured so the caller can render a
    configuration hint instead of a half-broken URL.

    The relative path already includes ``?tz=...``; do not append it again.
    Never log or persist the returned value.
    """
    cfg = get_settings()
    base = (cfg.public_base_url or "").rstrip("/")
    if not base:
        return None
    return base + secret.upload_url_path


def do_create_pairing_code(
    db: Session, *, ledger_id: str, account_id: int, ttl_minutes: int = 15
) -> PairingCodeResult:
    return create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)


def get_default_ledger_id(db: Session) -> str | None:
    choices = list_console_ledger_choices(db)
    if not choices:
        return None
    default = next((ledger for ledger in choices if ledger.is_default), None)
    return (default or choices[0]).ledger_id


def _visible_console_ledger_ids(db: Session) -> set[str]:
    return {ledger.ledger_id for ledger in list_console_ledger_choices(db)}


def _expense_status_count(db: Session, *, tenant_ids: set[str], status: str) -> int:
    if not tenant_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(tenant_ids), Expense.status == status)
        )
        or 0
    )


def _active_upload_link_count(db: Session, *, ledger_ids: set[str]) -> int:
    if not ledger_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(UploadLink)
            .where(UploadLink.ledger_id.in_(ledger_ids), UploadLink.revoked_at.is_(None))
        )
        or 0
    )


def get_owner_account_id(db: Session) -> int | None:
    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    return account.id if account else None


# ── v0.4-alpha1: ledger management view-models ──────────────────────────────

@dataclass
class LedgerHealthVM:
    """Per-ledger snapshot for the Owner Console dashboard health card.

    Counters mirror :class:`DataQualitySummary` but are scoped to one ledger
    so the owner can spot which ledger needs attention without opening each
    one individually. All values are read-only; the dashboard renders direct
    links to the matching /web pages.
    """

    ledger_id: str
    name: str
    is_default: bool
    pending: int
    ready_to_confirm: int
    suspected_duplicates: int
    missing_merchant: int
    missing_category: int
    oldest_pending_age_days: int | None


def list_ledger_health(db: Session) -> list[LedgerHealthVM]:
    """Compute :class:`LedgerHealthVM` for every ledger the owner owns.

    Reuses :func:`data_quality_summary` so the counters always match the
    /web/data-quality page exactly. Empty list when the owner has no
    ledgers yet (fresh install).
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    rows: list[LedgerHealthVM] = []
    for summary in list_managed_ledgers_for_account(db, account_id=owner_id):
        try:
            dq = data_quality_summary(db, tenant_id=summary.ledger_id)
        except Exception:
            continue
        rows.append(
            LedgerHealthVM(
                ledger_id=summary.ledger_id,
                name=summary.name,
                is_default=summary.is_default,
                pending=dq.pending_total,
                ready_to_confirm=dq.ready_to_confirm,
                suspected_duplicates=dq.suspected_duplicates,
                missing_merchant=dq.missing_merchant,
                missing_category=dq.missing_category,
                oldest_pending_age_days=dq.oldest_pending_age_days,
            )
        )
    return rows


@dataclass
class LedgerConsoleVM:
    """View-model for a single ledger row in the Owner Console ledgers page.

    Counts are computed at display time; for v0.4-alpha1 the absolute numbers
    matter less than confirming each ledger has its own pending/confirmed
    bucket and that switching ledgers does not bleed counts across.
    """

    ledger_id: str
    name: str
    role: str
    is_default: bool
    pending_count: int
    confirmed_count: int
    active_device_count: int


def list_console_ledgers(db: Session) -> list[LedgerConsoleVM]:
    """Return ledger rows the local owner can manage from the console.

    Uses the same owner-management rule as API admin scope: visible
    member/viewer ledgers are not manageable from the local console. The
    "owner account" is the first account row created at bootstrap; multi-
    account login is not part of v0.4-alpha1.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    summaries: list[LedgerSummary] = list_managed_ledgers_for_account(db, account_id=owner_id)
    rows: list[LedgerConsoleVM] = []
    for summary in summaries:
        pending = int(
            db.scalar(
                select(func.count())
                .select_from(Expense)
                .where(Expense.tenant_id == summary.ledger_id)
                .where(Expense.status == "pending")
            )
            or 0
        )
        confirmed = int(
            db.scalar(
                select(func.count())
                .select_from(Expense)
                .where(Expense.tenant_id == summary.ledger_id)
                .where(Expense.status == "confirmed")
            )
            or 0
        )
        counts = ledger_member_counts(db, ledger_id=summary.ledger_id)
        rows.append(
            LedgerConsoleVM(
                ledger_id=summary.ledger_id,
                name=summary.name,
                role=summary.role,
                is_default=summary.is_default,
                pending_count=pending,
                confirmed_count=confirmed,
                active_device_count=counts["active_devices"],
            )
        )
    return rows


def list_console_ledger_choices(db: Session) -> list[LedgerSummary]:
    """Return owner-managed ledgers the pairing dropdown should show.

    Returns an empty list before bootstrap so the caller can render a clear
    "service not initialised" message instead of a blank dropdown.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return list_managed_ledgers_for_account(db, account_id=owner_id)


def do_create_ledger(db: Session, *, name: str) -> LedgerSummary:
    """Create a new ledger owned by the local owner account.

    Owner Console runs as the local owner; we look up that account here so
    the route handler stays free of identity logic.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        raise AppError(
            "invalid_request",
            "服务未初始化，请先运行 bootstrap_dev_owner.ps1。",
            status_code=409,
        )
    return ledger_service_create_ledger(db, account_id=owner_id, name=name)
