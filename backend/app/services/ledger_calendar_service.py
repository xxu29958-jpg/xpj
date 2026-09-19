"""Frozen ledger calendar reads and one-time runtime compatibility adoption."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database._ledger_calendar_adoption import materialize_legacy_accounting_dates
from app.errors import AppError, DataIntegrityError
from app.models import Ledger, LedgerAuditLog, LedgerCalendarRevision
from app.services.time_service import now_utc


def calendar_revision(db: Session, *, ledger_id: str, revision: int) -> LedgerCalendarRevision | None:
    return db.get(LedgerCalendarRevision, (ledger_id, revision))


def current_calendar(db: Session, *, ledger_id: str) -> LedgerCalendarRevision | None:
    return db.scalar(select(LedgerCalendarRevision).join(
        Ledger,
        (Ledger.ledger_id == LedgerCalendarRevision.ledger_id)
        & (Ledger.calendar_revision == LedgerCalendarRevision.revision),
    ).where(Ledger.ledger_id == ledger_id))


def current_ledger_month(db: Session, *, ledger_id: str) -> str:
    """Default a new read or intent from the ledger, never a display preference."""
    rule = current_calendar(db, ledger_id=ledger_id)
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到当前账本的账务日历，请稍后重试。", status_code=409)
    return now_utc().astimezone(ZoneInfo(rule.timezone_name)).strftime("%Y-%m")


def adopt_ledger_calendar(
    db: Session, *, ledger_id: str, timezone_name: str, actor_account_id: int | None = None,
) -> LedgerCalendarRevision:
    """Adopt within the caller's transaction; never commit or acquire currency authority.

    This runtime bootstrap owner receives the correctly configured view snapshot.
    A recorded rule always wins over a later environment or display preference.
    """
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id).with_for_update()
                       .execution_options(populate_existing=True))
    if ledger is None:
        raise ValueError("calendar ledger does not exist")
    if ledger.calendar_revision is not None:
        rule = calendar_revision(db, ledger_id=ledger_id, revision=ledger.calendar_revision)
        if rule is None:
            raise DataIntegrityError("recorded ledger calendar rule is missing")
        return rule
    ZoneInfo(timezone_name)  # Reject unusable snapshots; never choose a fallback zone.
    rule = LedgerCalendarRevision(
        ledger_id=ledger_id, revision=1, timezone_name=timezone_name,
        basis="legacy_assumed", adopted_at=now_utc(), actor_account_id=actor_account_id,
    )
    db.add(rule)
    db.flush()
    ledger.calendar_revision = rule.revision
    db.add(LedgerAuditLog(
        ledger_id=ledger_id, action="calendar_adopted", actor_account_id=actor_account_id,
        resource_type="ledger_calendar_revision", resource_public_id=str(rule.revision),
        detail=json.dumps({"timezone_name": timezone_name, "basis": rule.basis}, ensure_ascii=False),
    ))
    db.flush()
    materialize_legacy_accounting_dates(db, ledger_id=ledger_id,
        revision=rule.revision, timezone_name=rule.timezone_name)
    db.expire_all()
    return rule


def adopt_all_ledger_calendars(*, timezone_name: str) -> None:
    """Adopt every ledger, including archived ledgers, in separate atomic transactions."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        ledgers = list(db.scalars(select(Ledger.ledger_id).order_by(Ledger.ledger_id)))
    for ledger_id in ledgers:
        with SessionLocal.begin() as db:
            adopt_ledger_calendar(db, ledger_id=ledger_id, timezone_name=timezone_name)
