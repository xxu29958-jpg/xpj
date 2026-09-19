"""Human continuation of a staged native event through existing fact commands."""

from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import ApiIdempotencyKey, CsvImportEvent, CsvImportRow, Expense, ExpenseOffsetFact
from app.schemas import CsvImportReviewRequest, CsvImportRowResponse, ExpenseOffsetCreateRequest
from app.services.csv_import_batch_service._apply import _apply_one_claimed_csv_import_row
from app.services.csv_import_batch_service._events import (
    _matches_fact,
    claim_csv_event,
    find_source_root,
    get_csv_event,
    prepare_native_csv_row,
)
from app.services.csv_import_batch_service._queries import build_csv_row_responses, get_csv_import_batch
from app.services.currency_binding_service import resolve_write_capability
from app.services.exchange_rate_service import validate_imported_currency_snapshot
from app.services.expense_offset_service import ReviewedOffsetImport, create_expense_offset
from app.services.expense_query import resolve_expense
from app.services.time_service import now_utc


def _complete_reviewed_quote(row: CsvImportRow, payload: CsvImportReviewRequest) -> None:
    """Retain the file cells and commit a missing quote with the reviewed result."""
    if payload.manual_exchange_rate is not None:
        complete = all(value is not None for value in (
            row.exchange_rate_to_cny, row.exchange_rate_date, row.exchange_rate_source))
        changed = any(known is not None and known != supplied for known, supplied in (
            (row.exchange_rate_to_cny, payload.manual_exchange_rate),
            (row.exchange_rate_date, payload.exchange_rate_date)))
        if complete or changed:
            raise AppError("currency_snapshot_invalid", "文件已有汇率依据，不能在导入中替换。", status_code=422)
        row.exchange_rate_to_cny = payload.manual_exchange_rate
        row.exchange_rate_date = payload.exchange_rate_date
        row.exchange_rate_source = row.exchange_rate_source or "manual"
    if any(value is None for value in (
            row.exchange_rate_to_cny, row.exchange_rate_date, row.exchange_rate_source)):
        raise AppError("currency_snapshot_invalid", "请补录本笔汇率和报价日期，再继续复核。", status_code=422)
    validate_imported_currency_snapshot(row)


def _associate_source_root(db: Session, row: CsvImportRow, root: Expense) -> None:
    """A reviewed association is durable even if the source purchase is omitted."""
    db.execute(insert(CsvImportEvent).values(tenant_id=row.tenant_id, entry_kind="expense",
        source_event_public_id=row.source_root_public_id, source_row_id=None, expense_id=root.id)
        .on_conflict_do_nothing(constraint="uq_csv_import_events_source"))
    event = get_csv_event(db, tenant_id=row.tenant_id, entry_kind="expense",
        source_public_id=row.source_root_public_id, for_update=True)
    if event.expense_id is not None and event.expense_id != root.id:
        raise AppError("import_event_conflict", "该来源原单已关联其他记录，请查看原任务。", status_code=409)
    if event.expense_id is None and event.source_row_id is not None:
        original = db.scalar(ledger_scoped_select(CsvImportRow, row.tenant_id).where(
            CsvImportRow.id == event.source_row_id))
        if original is None or not _matches_fact(original, root):
            raise AppError("import_event_conflict", "所选原单与已保存的来源消费不一致，请先复核原消费。", status_code=409)
    event.expense_id = root.id


def _review_offset(db: Session, row: CsvImportRow, *, payload: CsvImportReviewRequest,
                   actor_account_id: int, actor_device_public_id: str | None,
                   actor_device_name: str | None) -> None:
    root = find_source_root(db, tenant_id=row.tenant_id, source_public_id=row.source_root_public_id)
    if payload.expense_id is not None:
        if root is not None and root.id != payload.expense_id:
            raise AppError("import_event_conflict", "所选原单与来源关联不一致，请核对原任务。", status_code=409)
        root = resolve_expense(db, row.tenant_id, payload.expense_id)
    if root is None:
        raise AppError("expense_not_found", "请先选择本账本的原消费，或补充导入原消费后回到此任务。", status_code=404)
    if root.status != "confirmed":
        raise AppError("expense_not_confirmed", "请先复核并确认原消费，再返回此任务。", status_code=409)
    if payload.expected_row_version is None:
        raise AppError("state_conflict", "请先查看所选原单的当前状态，再复核此事件。", status_code=409)
    _associate_source_root(db, row, root)
    event = claim_csv_event(db, row)
    request_key = f"csv-offset:{event.id}"
    create_expense_offset(db, tenant_id=row.tenant_id, expense_id=root.id,
        payload=ExpenseOffsetCreateRequest(kind=row.offset_kind,
            original_amount_minor=None if row.offset_kind == "reversal" else row.original_amount_minor,
            accounting_date=row.accounting_date, reason=payload.reason,
            expected_row_version=payload.expected_row_version),
        effective_expected_row_version=payload.expected_row_version, actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id, actor_device_name=actor_device_name,
        idempotency_key=request_key, imported=ReviewedOffsetImport(money=row, category=row.category), commit=False)
    receipt = db.scalar(ledger_scoped_select(ApiIdempotencyKey, row.tenant_id).where(
        ApiIdempotencyKey.idempotency_key == request_key))
    offset = db.scalar(ledger_scoped_select(ExpenseOffsetFact, row.tenant_id).where(
        ExpenseOffsetFact.public_id == receipt.resource_id))
    event.expense_id = root.id
    event.offset_id = offset.id
    event.source_row_id = row.id
    row.status = "applied"
    row.error_code = row.error_message = None
    row.review_reason = payload.reason
    row.updated_at = now_utc()
    db.flush()
    # Fact, immutable revision, canonical receipt, root association and the saved
    # import outcome are accepted by exactly one transaction.
    db.commit()


def review_csv_import_row(db: Session, *, tenant_id: str, public_id: str, line_number: int,
                         payload: CsvImportReviewRequest, actor_account_id: int,
                         actor_device_id: int | None, actor_device_public_id: str | None,
                         actor_device_name: str | None) -> CsvImportRowResponse:
    try:
        resolve_write_capability(db)
        batch = get_csv_import_batch(db, tenant_id=tenant_id, public_id=public_id)
        row = db.scalar(ledger_scoped_select(CsvImportRow, tenant_id).where(
            CsvImportRow.batch_id == batch.id, CsvImportRow.line_number == line_number).with_for_update())
        if row is None:
            raise AppError("import_batch_not_found", status_code=404)
        if row.status in {"applied", "matched"}:
            return build_csv_row_responses(db, tenant_id=tenant_id, rows=[row])[0]
        if row.status not in {"valid", "review"} or row.event_input is None:
            raise AppError("import_batch_conflict", "请先修正或完成当前行的处理，再继续复核。", status_code=409)
        may_admit_purchase = prepare_native_csv_row(db, row,
            accept_incomplete=payload.acknowledge_incomplete_lineage)
        if row.status in {"matched", "conflict"}:
            db.commit()
        else:
            _complete_reviewed_quote(row, payload)
            if row.entry_kind == "offset":
                _review_offset(db, row, payload=payload, actor_account_id=actor_account_id,
                    actor_device_public_id=actor_device_public_id, actor_device_name=actor_device_name)
            else:
                if not may_admit_purchase and not prepare_native_csv_row(db, row,
                        accept_incomplete=payload.acknowledge_incomplete_lineage):
                    raise AppError("import_lineage_incomplete", "请补充相关退款或冲正，或明确复核本次只导入原消费。", status_code=409)
                token = str(uuid4())
                row.status, row.apply_token, row.review_reason = "applying", token, payload.reason
                db.flush()
                _apply_one_claimed_csv_import_row(db, row_id=row.id, batch=batch, tenant_id=tenant_id,
                    initiator_account_id=actor_account_id, initiator_device_id=actor_device_id,
                    apply_token=token, now=now_utc(), accept_incomplete=payload.acknowledge_incomplete_lineage)
        return build_csv_row_responses(db, tenant_id=tenant_id, rows=[row])[0]
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
