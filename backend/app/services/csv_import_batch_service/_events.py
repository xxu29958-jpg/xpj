"""Native CSV identity and admission, inside the existing row transaction.

File IDs resolve only in the selected ledger. The unique import result serializes
repeated files; all money still belongs to Expense/ExpenseOffsetFact commands.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch, CsvImportEvent, CsvImportRow, Expense, ExpenseOffsetFact
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.accounting_time_service import apply_accounting_time, resolve_accounting_time
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.import_financial_events import native_accounting_time
from app.services.ledger_calendar_service import calendar_revision
from app.services.time_service import ensure_utc, now_utc

_MONEY_FIELDS = ("home_currency_code", "original_currency_code", "original_amount_minor",
    "amount_cents", "exchange_rate_to_cny", "exchange_rate_date")
_PURCHASE_FIELDS = ("merchant", "category", "note", "expense_time", "accounting_date", "tags", "source")
_OFFSET_FIELDS = ("offset_kind", "source_root_public_id", "accounting_date", "category")
_QUOTE_FIELDS = ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source")


def get_csv_event(db: Session, *, tenant_id: str, entry_kind: str,
                  source_public_id: str, for_update: bool = False) -> CsvImportEvent | None:
    query = ledger_scoped_select(CsvImportEvent, tenant_id).where(
        CsvImportEvent.entry_kind == entry_kind, CsvImportEvent.source_event_public_id == source_public_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def claim_csv_event(db: Session, row: CsvImportRow) -> CsvImportEvent:
    if row.entry_kind not in {"expense", "offset"} or not row.source_event_public_id:
        raise AppError("invalid_request", "请先修正文件中的事件种类和来源标识。", status_code=422)
    db.execute(insert(CsvImportEvent).values(tenant_id=row.tenant_id, entry_kind=row.entry_kind,
        source_event_public_id=row.source_event_public_id, source_row_id=row.id)
        .on_conflict_do_nothing(constraint="uq_csv_import_events_source"))
    event = get_csv_event(db, tenant_id=row.tenant_id, entry_kind=row.entry_kind,
        source_public_id=row.source_event_public_id, for_update=True)
    if event is None:
        raise AppError("import_batch_conflict", "导入任务已变化，请返回原批次查看当前结果。", status_code=409)
    return event


def _same_source_row(left: CsvImportRow, right: CsvImportRow) -> bool:
    fields = _MONEY_FIELDS + ("exchange_rate_source",) + (
        _PURCHASE_FIELDS if left.entry_kind == "expense" else _OFFSET_FIELDS)
    # Stream contribution/lineage are current projections, not an event identity.
    left_time = native_accounting_time(left.event_input or {})
    right_time = native_accounting_time(right.event_input or {})
    return ((left_time is None or right_time is None or left_time == right_time)
        and left.entry_kind == right.entry_kind and all(
        _source_value(left, field) == _source_value(right, field) for field in fields))


def _source_value(row: CsvImportRow, field: str) -> object | None:
    # A reviewed missing quote fills typed evidence, without rewriting the file.
    if (field in _QUOTE_FIELDS and row.event_input is not None
            and not row.event_input.get(field, "").strip()):
        return None
    return getattr(row, field) or None


def _matches_fact(row: CsvImportRow, fact: Expense | ExpenseOffsetFact) -> bool:
    if any(getattr(row, field) != getattr(fact, field) for field in _MONEY_FIELDS):
        return False
    if not _matches_time_evidence(row, fact):
        return False
    if isinstance(fact, ExpenseOffsetFact):
        return (fact.status == "active" and row.offset_kind == fact.kind
            and row.accounting_date == fact.accounting_date and row.category == fact.category)
    return (fact.status in {"pending", "confirmed"} and _matches_purchase_clock(row, fact) and all(
        (getattr(row, field) or None) == (getattr(fact, field) or None)
        for field in _PURCHASE_FIELDS if field != "expense_time"))


def _matches_purchase_clock(row: CsvImportRow, fact: Expense) -> bool:
    source = native_accounting_time(row.event_input or {})
    if source is not None:
        effective_time = ensure_utc(fact.expense_time)
    elif fact.accounting_date_basis == "recorded_date" and fact.expense_time is None:
        effective_time = row.expense_time  # Original legacy file evidence remains on the canonical row.
    else:
        # Old exports used this presentation fallback. It is only a matching
        # witness here, never the producer of a new purchase instant.
        effective_time = ensure_utc(fact.expense_time) or ensure_utc(fact.confirmed_at)
    exported_time = (effective_time if source is not None else effective_time.replace(microsecond=0)) if effective_time else None
    return row.expense_time == exported_time


def _matches_time_evidence(row: CsvImportRow, fact: Expense | ExpenseOffsetFact) -> bool:
    source = native_accounting_time(row.event_input or {})
    if source is None:
        return True
    if source.instant_utc != ensure_utc(getattr(fact, "expense_time", None)):
        return False
    return all(getattr(source, field) == getattr(fact, attribute) for field, attribute in (
        ("precision", "time_precision"), ("user_local_date", "user_local_date"),
        ("source_timezone", "source_timezone"), ("source_utc_offset_seconds", "source_utc_offset_seconds")))


def freeze_csv_expense_time(db: Session, *, row: CsvImportRow, batch: CsvImportBatch, expense: Expense) -> None:
    if row.event_input is None and row.time_input is None:
        refresh_legacy_expense_time(db, expense)
        return
    revision = batch.calendar_revision or 1
    rule = calendar_revision(db, ledger_id=row.tenant_id, revision=revision)
    if rule is None:
        raise AppError("calendar_revision_conflict", status_code=409)
    if row.event_input is not None:
        source = native_accounting_time(row.event_input)
        snapshot = (source or AccountingTimeSnapshot()).model_copy(update={
            "accounting_date": row.accounting_date, "calendar_revision": rule.revision, "basis": "recorded_date"})
    else:
        value = AccountingTimeInput.model_validate(row.time_input)
        snapshot = resolve_accounting_time(value, ledger_timezone=rule.timezone_name, calendar_revision=rule.revision)
    apply_accounting_time(expense, snapshot)


def find_source_root(db: Session, *, tenant_id: str, source_public_id: str) -> Expense | None:
    event = get_csv_event(db, tenant_id=tenant_id, entry_kind="expense", source_public_id=source_public_id)
    query = ledger_scoped_select(Expense, tenant_id)
    if event is not None and event.expense_id is not None:
        return db.scalar(query.where(Expense.id == event.expense_id))
    return db.scalar(query.where(Expense.public_id == source_public_id))


def purchase_lineage_is_present(db: Session, row: CsvImportRow) -> bool:
    """A filtered file can omit other events; it must not claim a complete lineage."""
    if row.lineage_status in {None, "confirmed"}:
        return True
    sources = list(db.scalars(ledger_scoped_select(CsvImportRow, row.tenant_id).where(
        CsvImportRow.entry_kind == "offset", CsvImportRow.source_root_public_id == row.source_event_public_id,
        CsvImportRow.status.not_in(("error", "insert_failed", "conflict")))))
    events: dict[str, CsvImportRow] = {}
    for source in sources:
        previous = events.get(source.source_event_public_id)
        if previous is not None and not _same_source_row(previous, source):
            return False
        events[source.source_event_public_id] = source
    if row.lineage_status == "reversed":
        return any(source.offset_kind == "reversal" for source in events.values())
    refunds = [source for source in events.values() if source.offset_kind in {"refund", "chargeback"}]
    return bool(refunds) and all(source.home_currency_code == row.home_currency_code for source in refunds) and (
        row.amount_cents - sum(source.amount_cents for source in refunds) == row.lineage_home_net_cents)


def _finish_row(row: CsvImportRow, status: str, message: str | None = None) -> None:
    row.status = status
    row.apply_token = None
    row.error_code = "import_event_conflict" if status == "conflict" else None
    row.error_message = message
    row.updated_at = now_utc()


def _find_event_fact(db: Session, row: CsvImportRow, event: CsvImportEvent) -> Expense | ExpenseOffsetFact | None:
    if row.entry_kind == "expense":
        return db.scalar(ledger_scoped_select(Expense, row.tenant_id).where(
            Expense.id == event.expense_id if event.expense_id else Expense.public_id == row.source_event_public_id))
    return db.scalar(ledger_scoped_select(ExpenseOffsetFact, row.tenant_id).where(
        ExpenseOffsetFact.id == event.offset_id if event.offset_id else ExpenseOffsetFact.public_id == row.source_event_public_id))


def _match_existing_event(db: Session, row: CsvImportRow, canonical_row: CsvImportRow,
                          event: CsvImportEvent, fact: Expense | ExpenseOffsetFact) -> None:
    event.expense_id = fact.id if row.entry_kind == "expense" else fact.expense_id
    if row.entry_kind == "offset":
        event.offset_id = fact.id
    source_root = find_source_root(db, tenant_id=row.tenant_id,
        source_public_id=row.source_root_public_id) if row.entry_kind == "offset" else None
    relationship_matches = row.entry_kind == "expense" or (source_root is not None and source_root.id == fact.expense_id)
    if _matches_fact(canonical_row, fact) and _matches_time_evidence(row, fact) and relationship_matches:
        if event.source_row_id is None:
            event.source_row_id = row.id
        _finish_row(row, "matched")
    else:
        _finish_row(row, "conflict", "来源事件已有记录，但内容或状态不同；请核对已有记录，不会重复入账。")


def prepare_native_csv_row(db: Session, row: CsvImportRow, *, accept_incomplete: bool = False) -> bool:
    """Return True only when the existing apply owner should admit a new purchase."""
    event = claim_csv_event(db, row)
    canonical_row = row
    if event.source_row_id is not None and event.source_row_id != row.id:
        original = db.scalar(ledger_scoped_select(CsvImportRow, row.tenant_id).where(
            CsvImportRow.id == event.source_row_id))
        if original is None or not _same_source_row(row, original):
            _finish_row(row, "conflict", "同一来源事件的内容已变化，请查看已有记录并通过更正处理。")
            return False
        canonical_row = original
    fact = _find_event_fact(db, row, event)
    if fact is not None:
        _match_existing_event(db, row, canonical_row, event, fact)
        return False
    if (event.expense_id is not None and row.entry_kind == "expense") or event.offset_id is not None:
        _finish_row(row, "conflict", "此前关联的记录已移除，请核对原任务，不会重新创建。")
        return False
    if row.entry_kind == "offset":
        _finish_row(row, "review")
        return False
    if any(getattr(row, field) is None for field in _QUOTE_FIELDS):
        _finish_row(row, "review", "旧文件缺少汇率依据，请复核并补录本笔汇率和报价日期后继续。")
        return False
    if not accept_incomplete and not purchase_lineage_is_present(db, row):
        _finish_row(row, "review", "文件未包含原单的完整退款或冲正，请补充相关事件，或明确复核本次只导入原消费。")
        return False
    return True


def bind_created_purchase(db: Session, row: CsvImportRow, expense: Expense) -> None:
    event = get_csv_event(db, tenant_id=row.tenant_id, entry_kind="expense",
        source_public_id=row.source_event_public_id, for_update=True)
    if event is None or event.expense_id is not None:
        raise AppError("import_batch_conflict", "该来源事件已由其他请求处理，请返回原批次查看结果。", status_code=409)
    event.expense_id = expense.id
    event.source_row_id = row.id
