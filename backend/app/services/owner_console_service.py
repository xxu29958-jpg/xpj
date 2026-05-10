"""Owner Console view-model helpers.

Aggregates data needed by the Owner Console HTML pages. These functions are
called exclusively from :mod:`app.routes.owner_console` and must never depend
on FastAPI Request or return HTTP responses.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Account, Device, Expense, Ledger, UploadLink
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
from app.services.identity_service import (
    PairingCodeResult,
    create_pairing_code,
)
from app.services.ledger_service import (
    LedgerSummary,
    create_ledger as ledger_service_create_ledger,
    ledger_member_counts,
    list_ledgers_for_account,
)
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION


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


def get_index_vm(db: Session) -> ConsoleIndexVM:
    cfg = get_settings()
    db_status = "ok"
    if cfg.database_url.startswith("sqlite:///"):
        from pathlib import Path

        db_path = Path(cfg.database_url[len("sqlite:///") :])
        db_status = "ok" if db_path.is_file() else "missing"

    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"

    pending_count = int(
        db.scalar(select(func.count()).select_from(Expense).where(Expense.status == "pending")) or 0
    )
    confirmed_count = int(
        db.scalar(select(func.count()).select_from(Expense).where(Expense.status == "confirmed")) or 0
    )

    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    ledger = db.scalar(select(Ledger).where(Ledger.archived_at.is_(None)).order_by(Ledger.id.asc()).limit(1))

    active_devices = int(
        db.scalar(select(func.count()).select_from(Device).where(Device.revoked_at.is_(None))) or 0
    )
    active_links = int(
        db.scalar(select(func.count()).select_from(UploadLink).where(UploadLink.revoked_at.is_(None))) or 0
    )

    return ConsoleIndexVM(
        backend_version=BACKEND_VERSION,
        identity_schema=IDENTITY_SCHEMA_VERSION,
        database_status=db_status,
        upload_dir_status=upload_status,
        owner_console_status="available",
        pending_count=pending_count,
        confirmed_count=confirmed_count,
        account_name=account.display_name if account else "（未初始化）",
        ledger_name=ledger.name if ledger else "（未初始化）",
        active_device_count=active_devices,
        active_upload_link_count=active_links,
    )


def get_devices(db: Session) -> list[DeviceSummary]:
    return list_devices(db)


def do_revoke_device(db: Session, public_id: str, current_device_public_id: str) -> DeviceSummary:
    return revoke_device(db, public_id=public_id, current_device_public_id=current_device_public_id)


def do_delete_device(db: Session, public_id: str, current_device_public_id: str) -> None:
    delete_device(db, public_id=public_id, current_device_public_id=current_device_public_id)


def do_rename_device(db: Session, public_id: str, new_name: str) -> DeviceSummary:
    return rename_device(db, public_id=public_id, new_name=new_name)


def get_upload_links(db: Session) -> list[UploadLinkSummary]:
    return list_upload_links(db)


def do_create_upload_link(
    db: Session, *, ledger_id: str, admin_account_id: int, default_timezone: str
) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return create_upload_link(db, ledger_id=ledger_id, admin_account_id=admin_account_id, default_timezone=default_timezone)


def do_rotate_upload_link(db: Session, public_id: str) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return rotate_upload_link(db, public_id=public_id)


def do_revoke_upload_link(db: Session, public_id: str) -> UploadLinkSummary:
    return revoke_upload_link(db, public_id=public_id)


def do_delete_upload_link(db: Session, public_id: str) -> None:
    delete_upload_link(db, public_id=public_id)


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
    ledger = db.scalar(select(Ledger).where(Ledger.archived_at.is_(None)).order_by(Ledger.id.asc()).limit(1))
    return ledger.ledger_id if ledger else None


def get_owner_account_id(db: Session) -> int | None:
    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    return account.id if account else None


# ── v0.4-alpha1: ledger management view-models ──────────────────────────────

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

    Uses the same membership rules as :func:`list_ledgers_for_account`. The
    "owner account" is the first account row created at bootstrap; multi-
    account login is not part of v0.4-alpha1.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    summaries: list[LedgerSummary] = list_ledgers_for_account(db, account_id=owner_id)
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
    """Return the ledger summaries the pairing dropdown should show.

    Returns an empty list before bootstrap so the caller can render a clear
    "service not initialised" message instead of a blank dropdown.
    """
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return list_ledgers_for_account(db, account_id=owner_id)


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
