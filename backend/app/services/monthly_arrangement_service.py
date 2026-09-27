"""Transaction-owned arrangements: captured units, CAS, receipt replay and history."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, MonthlyArrangement, MonthlyArrangementRevision
from app.money_contract import MoneySign, ensure_money_minor
from app.schemas._monthly_arrangement import (
    MonthlyArrangementDto,
    MonthlyArrangementHistory,
    MonthlyArrangementRevisionDto,
    MonthlyArrangementSaveRequest,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import normalize_currency_code
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.spending_contract_service import clean_month
from app.services.time_service import now_utc

_OPERATION = "save_monthly_arrangement"
_TARGET = "monthly_arrangement"


def _dto(row: MonthlyArrangement) -> MonthlyArrangementDto:
    return MonthlyArrangementDto(ledger_id=row.tenant_id, month=row.month,
        home_currency_code=row.home_currency_code, savings_target_cents=row.savings_target_cents,
        reserved_buffer_cents=row.reserved_buffer_cents, row_version=row.row_version, updated_at=row.updated_at)


def _read_row(db: Session, *, tenant_id: str, month: str) -> MonthlyArrangement | None:
    return db.scalar(select(MonthlyArrangement).where(
        MonthlyArrangement.tenant_id == tenant_id, MonthlyArrangement.month == month))


def read_monthly_arrangement(db: Session, *, tenant_id: str, month: str) -> MonthlyArrangementDto | None:
    row = _read_row(db, tenant_id=tenant_id, month=clean_month(month))
    return _dto(row) if row is not None else None


def review_monthly_arrangement_save(db: Session, *, tenant_id: str, month: str, idempotency_key: str) -> bool:
    month = clean_month(month)
    row = db.scalar(select(ApiIdempotencyKey).where(
        ApiIdempotencyKey.tenant_id == tenant_id, ApiIdempotencyKey.idempotency_key == idempotency_key))
    if row is None:
        return False
    if (row.operation, row.target_type, row.target_id) != (_OPERATION, _TARGET, month):
        raise AppError("idempotency_key_reused", status_code=422)
    if row.status != "succeeded":
        raise AppError("idempotency_key_in_progress", "原保存结果尚未确认，请保留输入并原样重试。", status_code=409)
    return True


def record_monthly_arrangement_revision(db: Session, row: MonthlyArrangement, *, actor_account_id: int | None) -> None:
    db.add(MonthlyArrangementRevision(tenant_id=row.tenant_id, arrangement_id=row.id,
        row_version=row.row_version, home_currency_code=row.home_currency_code,
        savings_target_cents=row.savings_target_cents, reserved_buffer_cents=row.reserved_buffer_cents,
        actor_account_id=actor_account_id, recorded_at=row.updated_at))
    db.flush()


def _apply_save(db: Session, *, tenant_id: str, month: str, payload: MonthlyArrangementSaveRequest,
    actor_account_id: int | None) -> MonthlyArrangementDto:
    savings = ensure_money_minor(payload.savings_target_cents, sign=MoneySign.NONNEGATIVE, label="arrangement.savings")
    buffer = ensure_money_minor(payload.reserved_buffer_cents, sign=MoneySign.NONNEGATIVE, label="arrangement.buffer")
    currency = normalize_currency_code(payload.home_currency_code)
    resolve_write_capability(db)
    now = now_utc()
    row = _read_row(db, tenant_id=tenant_id, month=month)
    if row is None:
        if payload.expected_row_version is not None:
            raise AppError("state_conflict", "这月安排已发生变化，请保留输入并重新核对。", status_code=409)
        row = db.scalar(insert(MonthlyArrangement).values(tenant_id=tenant_id, month=month,
            home_currency_code=currency, savings_target_cents=savings, reserved_buffer_cents=buffer,
            created_at=now, updated_at=now).on_conflict_do_nothing(
                constraint="uq_monthly_arrangement_tenant_month").returning(MonthlyArrangement))
        if row is None:
            raise AppError("state_conflict", "另一端已创建这月安排，请保留输入并重新核对。", status_code=409)
    else:
        if payload.expected_row_version != row.row_version:
            raise AppError("state_conflict", "另一端已修改这月安排，请保留输入并重新核对。", status_code=409)
        if currency != row.home_currency_code:
            raise AppError("state_conflict", "输入币种与这月安排不同，请保留原金额并核对。", status_code=409)
        claimed = claim_row_with_token(db, MonthlyArrangement, pk_id=row.id, tenant_id=tenant_id,
            expected_row_version=payload.expected_row_version, set_values={"updated_at": now,
                "savings_target_cents": savings, "reserved_buffer_cents": buffer},
            extra_where=(MonthlyArrangement.home_currency_code == currency,))
        if claimed != 1:
            raise AppError("state_conflict", "另一端已修改这月安排，请保留输入并重新核对。", status_code=409)
        db.refresh(row)
    record_monthly_arrangement_revision(db, row, actor_account_id=actor_account_id)
    return _dto(row)


def save_monthly_arrangement(db: Session, *, tenant_id: str, month: str,
    payload: MonthlyArrangementSaveRequest, actor_account_id: int | None,
    idempotency_key: str | None) -> MonthlyArrangementDto:
    month = clean_month(month)
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    try:
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
            operation=_OPERATION, target_type=_TARGET, target_id=month,
            request_fingerprint=fingerprint_request(operation=_OPERATION, target_id=month,
                body={"actor_account_id": actor_account_id,
                    "intent": payload.model_dump(mode="json", exclude={"expected_row_version"})},
                expected_row_version=payload.expected_row_version))
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return MonthlyArrangementDto.model_validate(claim.row.response_body)
        response = _apply_save(db, tenant_id=tenant_id, month=month, payload=payload, actor_account_id=actor_account_id)
        mark_idempotency_succeeded(db, claim.row, resource_type=_TARGET, resource_id=month,
            response_body=response.model_dump(mode="json"))
        db.commit()
        return response
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise


def list_monthly_arrangement_history(db: Session, *, tenant_id: str, month: str,
    before_version: int | None = None, limit: int = 20) -> MonthlyArrangementHistory:
    month = clean_month(month)
    query = select(MonthlyArrangementRevision).join(MonthlyArrangement,
        (MonthlyArrangement.id == MonthlyArrangementRevision.arrangement_id)
        & (MonthlyArrangement.tenant_id == MonthlyArrangementRevision.tenant_id)).where(
            MonthlyArrangement.tenant_id == tenant_id, MonthlyArrangement.month == month)
    if before_version is not None:
        query = query.where(MonthlyArrangementRevision.row_version < before_version)
    rows = db.scalars(query.order_by(MonthlyArrangementRevision.row_version.desc()).limit(limit + 1)).all()
    selected = rows[:limit]
    return MonthlyArrangementHistory(ledger_id=tenant_id, month=month,
        items=[MonthlyArrangementRevisionDto(row_version=row.row_version, recorded_at=row.recorded_at,
            home_currency_code=row.home_currency_code, savings_target_cents=row.savings_target_cents,
            reserved_buffer_cents=row.reserved_buffer_cents) for row in selected],
        next_before_version=selected[-1].row_version if len(rows) > limit else None)
