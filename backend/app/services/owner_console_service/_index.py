"""Owner Console index page aggregator.

This module composes ConsoleIndexVM from data fetched across all other
owner_console submodules. The index page renders four independent
"cards" (data quality, recurring ops, budget status, devices); each
card's data-fetch is wrapped in a broad except so one service hiccup
cannot 500 the operator's last-line-of-defence visibility page.
Those broad catches carry ``# noqa: BLE001`` and **must not be
narrowed** without an explicit audit decision (see S-006).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Account
from app.services.admin_service import list_devices
from app.services.budget_service import get_monthly_budget
from app.services.data_quality_service import DataQualitySummary, data_quality_summary
from app.services.ledger_service import LedgerSummary
from app.services.owner_console_service._common import (
    OWNER_CONSOLE_TIMEZONE,
    _active_upload_link_count,
    _amount_yuan,
    _expense_status_count,
    logger,
)
from app.services.owner_console_service._ledger_console import (
    _managed_console_ledger_ids,
    list_console_ledger_choices,
)
from app.services.owner_console_service._recurring_ops import (
    RecurringOpsVM,
    get_recurring_ops,
)
from app.services.time_service import current_month
from app.tenants import DEFAULT_TENANT_ID
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION


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


def get_index_vm(db: Session) -> ConsoleIndexVM:
    cfg = get_settings()
    # PG-only: static "ok" (no SQLite file-presence proxy; a live readiness
    # probe is out of scope — see ``main.private_status``).
    db_status = "ok"
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"

    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    ledger_choices = list_console_ledger_choices(db)
    primary_ledger = ledger_choices[0] if ledger_choices else None
    managed_ledger_ids = _managed_console_ledger_ids(db)

    pending_count = _expense_status_count(db, tenant_ids=managed_ledger_ids, status="pending")
    confirmed_count = _expense_status_count(db, tenant_ids=managed_ledger_ids, status="confirmed")

    visible_devices = list_devices(db, ledger_ids=managed_ledger_ids)
    active_devices = sum(1 for device in visible_devices if device.revoked_at is None)
    active_links = _active_upload_link_count(db, ledger_ids=managed_ledger_ids)

    # The owner console index renders four independent "cards". A single
    # service hiccup must not 500 the whole page — the page is the operator's
    # last line of visibility into the system. Each card therefore guards its
    # data-fetch with a broad except + logger.exception, and degrades to None.
    primary_tenant_id = primary_ledger.ledger_id if primary_ledger else DEFAULT_TENANT_ID
    try:
        dq_summary: DataQualitySummary | None = data_quality_summary(
            db, tenant_id=primary_tenant_id
        )
    except Exception:  # noqa: BLE001 — owner console index card degrades to None
        logger.exception("owner_console index: data_quality_summary failed for ledger=%s", primary_tenant_id)
        dq_summary = None
    try:
        recurring_ops: RecurringOpsVM | None = get_recurring_ops(db)
    except Exception:  # noqa: BLE001 — owner console index card degrades to None
        logger.exception("owner_console index: get_recurring_ops failed")
        recurring_ops = None
    try:
        budget_status = _budget_status_for_primary_ledger(db, primary_ledger)
    except Exception:  # noqa: BLE001 — owner console index card degrades to None
        logger.exception("owner_console index: budget_status failed for ledger=%s", primary_tenant_id)
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
