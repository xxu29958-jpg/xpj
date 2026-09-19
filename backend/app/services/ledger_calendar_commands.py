"""Owner governance of future calendar rules using existing command receipts."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Ledger, LedgerAuditLog, LedgerCalendarRevision
from app.schemas._ledger_calendar import LedgerCalendarChangeRequest, LedgerCalendarResponse
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.ledger_calendar_service import calendar_revision, current_calendar
from app.services.ledger_service import get_ledger_for_account
from app.services.session_credential_lock import lock_and_revalidate_mutation_actor
from app.services.time_service import now_utc, strict_zone
from app.tenants import AuthContext


def read_ledger_calendar(db: Session, *, ledger_id: str, account_id: int,
                         revision: int | None = None) -> LedgerCalendarResponse:
    get_ledger_for_account(db, ledger_id=ledger_id, account_id=account_id)
    rule = (current_calendar(db, ledger_id=ledger_id) if revision is None
            else calendar_revision(db, ledger_id=ledger_id, revision=revision))
    if rule is None:
        raise AppError("calendar_revision_conflict", "未找到这份账务日历。", status_code=409)
    return LedgerCalendarResponse.model_validate(rule)


def ledger_calendar_history(db: Session, *, ledger_id: str, account_id: int) -> list[LedgerCalendarResponse]:
    get_ledger_for_account(db, ledger_id=ledger_id, account_id=account_id)
    rules = db.scalars(select(LedgerCalendarRevision).where(LedgerCalendarRevision.ledger_id == ledger_id)
                       .order_by(LedgerCalendarRevision.revision.desc()))
    return [LedgerCalendarResponse.model_validate(rule) for rule in rules]


def _append_calendar_rule(db: Session, *, ledger_id: str, actor_account_id: int,
                          payload: LedgerCalendarChangeRequest) -> LedgerCalendarResponse:
    zone = strict_zone(payload.timezone_name)
    ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id).with_for_update()
                       .execution_options(populate_existing=True))
    if ledger is None or ledger.calendar_revision != payload.expected_revision:
        raise AppError("calendar_revision_conflict", "账务日历已更新，请保留输入并核对当前设置。", status_code=409)
    current = calendar_revision(db, ledger_id=ledger_id, revision=ledger.calendar_revision)
    if current is None:
        raise AppError("calendar_revision_conflict", "未找到当前账务日历。", status_code=409)
    if current.timezone_name == zone.key:
        return LedgerCalendarResponse.model_validate(current)
    rule = LedgerCalendarRevision(ledger_id=ledger_id, revision=current.revision + 1,
        timezone_name=zone.key, basis="owner_selected", actor_account_id=actor_account_id, adopted_at=now_utc())
    db.add(rule)
    db.flush()
    ledger.calendar_revision = rule.revision
    db.add(LedgerAuditLog(ledger_id=ledger_id, action="calendar_changed", actor_account_id=actor_account_id,
        resource_type="ledger_calendar_revision", resource_public_id=str(rule.revision),
        detail=json.dumps({"previous_revision": current.revision, "timezone_name": zone.key}, ensure_ascii=False)))
    return LedgerCalendarResponse.model_validate(rule)


def change_ledger_calendar(db: Session, *, ledger_id: str, actor_account_id: int,
                           auth: AuthContext | None, payload: LedgerCalendarChangeRequest,
                           idempotency_key: str) -> LedgerCalendarResponse:
    lock_and_revalidate_mutation_actor(db, auth, actor_account_id=actor_account_id, ledger_id=ledger_id)
    ledger, role = get_ledger_for_account(db, account_id=actor_account_id, ledger_id=ledger_id)
    if role != "owner" or ledger.owner_account_id != actor_account_id:
        raise AppError("permission_denied", status_code=403)
    fingerprint = fingerprint_request(operation="change_ledger_calendar", target_id=ledger_id,
        body={**payload.model_dump(mode="json"), "actor_account_id": actor_account_id},
        expected_row_version=payload.expected_revision)
    try:
        claim = claim_idempotency_key(db, tenant_id=ledger_id, idempotency_key=idempotency_key,
            operation="change_ledger_calendar", request_fingerprint=fingerprint, target_type="ledger", target_id=ledger_id)
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return LedgerCalendarResponse.model_validate(claim.row.response_body)
        response = _append_calendar_rule(db, ledger_id=ledger_id, actor_account_id=actor_account_id, payload=payload)
        mark_idempotency_succeeded(db, claim.row, resource_type="ledger_calendar_revision",
            resource_id=str(response.revision), response_body=response.model_dump(mode="json"))
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
