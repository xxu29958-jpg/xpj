"""Read-only expense lookups."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date

from sqlalchemy import Date as SqlDate
from sqlalchemy import Integer, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseOffsetFact
from app.schemas import (
    ConfirmedExpenseStreamEntry,
    ConfirmedExpenseStreamItem,
    ConfirmedOffsetStreamEntry,
    ExpenseResponse,
)
from app.services.category_common import category_filter_values
from app.services.expense_offset_summary import expense_financial_summary
from app.services.expense_query import (  # noqa: F401 — re-exported
    get_expense,
    resolve_expense,
    resolve_expense_for_mutation,
)
from app.services.expense_response_service import expenses_to_responses
from app.services.spending_contract_service import (
    accounting_timezone_key,
    confirmed_query,
    parse_month,
    stat_time_expr,
)

__all__ = [
    "fetch_expense_row_version_in_status",
    "get_expense",
    "is_expense_in_status_for_tenant",
    "ledger_has_any_expense",
    "list_confirmed",
    "list_expenses_by_ids",
    "list_pending",
    "resolve_expense",
    "resolve_expense_for_mutation",
]


def ledger_has_any_expense(db: Session, tenant_id: str) -> bool:
    """Cheap predicate: does this ledger have *any* expense row ever (any status)?

    Drives the /web dashboard first-day onboarding branch — a brand-new ledger
    with zero lifetime expenses gets directional guidance (where to add the first
    receipt) instead of a screen full of zeros. Lifetime (not this-month) scope is
    deliberate: a ledger that had expenses last month but none this month is NOT
    first-day, so the month-scoped ``confirmed_count`` / ``pending_count`` already
    in the dashboard payload can't answer this. ``LIMIT 1`` keeps it an existence
    probe, not a count over the whole table.
    """
    return (
        db.scalar(
            ledger_scoped_select(Expense, tenant_id)
            .with_only_columns(Expense.id)
            .limit(1)
        )
        is not None
    )


def is_expense_in_status_for_tenant(
    db: Session, *, expense_id: int, tenant_id: str, status: str
) -> bool:
    """Cheap predicate: does this expense exist in [status] under [tenant_id].

    ADR-0038 /web undo: the pending.html banner uses this to decide whether the
    ``?undo=<id>`` query in the URL is still meaningful (right ledger, still
    rejected, not yet purged). Soft affordance — the atomic UPDATE in
    ``undo_reject_expense`` is the real authority; this is the page telling
    the truth rather than rendering a misleading "可撤销" button.
    """
    return (
        db.scalar(
            ledger_scoped_select(Expense, tenant_id)
            .with_only_columns(Expense.id)
            .where(Expense.id == expense_id)
            .where(Expense.status == status)
            .limit(1)
        )
        is not None
    )


def fetch_expense_row_version_in_status(
    db: Session, *, expense_id: int, tenant_id: str, status: str
) -> int | None:
    """ADR-0041: return the row's ``row_version`` if it's in [status] under
    [tenant_id], else None. Used by ``/web/pending`` to seed the undo banner's
    hidden ``expected_row_version`` form field — without it the banner POSTs a
    body the server can't validate.

    Combines "is it still rejected?" with "what's its CAS token?" in one query
    so the ownership check and token read stay consistent (no TOCTOU between the
    predicate and a separate token fetch)."""
    return db.scalar(
        ledger_scoped_select(Expense, tenant_id)
        .with_only_columns(Expense.row_version)
        .where(Expense.id == expense_id)
        .where(Expense.status == status)
        .limit(1)
    )


def list_pending(db: Session, tenant_id: str) -> list[Expense]:
    return list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id)
            .where(Expense.status == "pending")
            .order_by(Expense.created_at.desc(), Expense.id.desc())
        )
    )


def list_expenses_by_ids(
    db: Session, *, tenant_id: str, expense_ids: list[int]
) -> list[Expense]:
    """Fetch ledger-scoped expenses by primary key ids.

    Cross-ledger ids are silently filtered out (caller decides how to surface
    that via len() comparison). The order of results is not guaranteed.
    """
    if not expense_ids:
        return []
    return list(
        db.scalars(
            ledger_scoped_select(Expense, tenant_id).where(Expense.id.in_(expense_ids))
        )
    )


def list_confirmed(
    db: Session,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> tuple[list[ConfirmedExpenseStreamItem], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)

    stream = _confirmed_stream_locator_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )
    total = int(db.scalar(select(func.count()).select_from(stream)) or 0)
    locators = list(
        db.execute(
            select(stream)
            .order_by(
                stream.c.stream_date.desc(),
                stream.c.sort_time.desc(),
                stream.c.sort_id.desc(),
                stream.c.entry_kind.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).mappings()
    )
    return _confirmed_stream_entries(db, tenant_id=tenant_id, locators=locators), total


def _offset_month_bounds(month: str) -> tuple[date, date]:
    year, month_number = parse_month(month)
    start = date(year, month_number, 1)
    if month_number == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month_number + 1, 1)


def _confirmed_stream_locator_query(
    *,
    tenant_id: str,
    month: str | None,
    category: str | None,
    tag: str | None,
    timezone_name: str | None,
):
    timezone_key = accounting_timezone_key(timezone_name)
    expense_time = stat_time_expr()
    expense_scope = confirmed_query(
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_key,
    )
    expense_entries = expense_scope.with_only_columns(
        literal("expense").label("entry_kind"),
        cast(func.timezone(timezone_key, expense_time), SqlDate).label("stream_date"),
        expense_time.label("sort_time"),
        Expense.id.label("sort_id"),
        Expense.id.label("root_expense_id"),
        cast(literal(None), Integer).label("offset_id"),
    )

    tagged_confirmed_roots = confirmed_query(
        tenant_id=tenant_id,
        tag=tag,
        timezone_name=timezone_key,
    ).with_only_columns(Expense.id)
    offset_entries = (
        select(
            literal("offset").label("entry_kind"),
            ExpenseOffsetFact.accounting_date.label("stream_date"),
            ExpenseOffsetFact.created_at.label("sort_time"),
            ExpenseOffsetFact.id.label("sort_id"),
            ExpenseOffsetFact.expense_id.label("root_expense_id"),
            ExpenseOffsetFact.id.label("offset_id"),
        )
        .where(ExpenseOffsetFact.tenant_id == tenant_id)
        .where(ExpenseOffsetFact.status == "active")
        .where(ExpenseOffsetFact.expense_id.in_(tagged_confirmed_roots))
    )
    if month:
        start, end = _offset_month_bounds(month)
        offset_entries = offset_entries.where(
            ExpenseOffsetFact.accounting_date >= start,
            ExpenseOffsetFact.accounting_date < end,
        )
    if category:
        offset_entries = offset_entries.where(
            ExpenseOffsetFact.category.in_(category_filter_values(category))
        )
    return union_all(expense_entries, offset_entries).subquery("confirmed_stream")


def _confirmed_stream_entries(
    db: Session,
    *,
    tenant_id: str,
    locators: list[Mapping[str, object]],
) -> list[ConfirmedExpenseStreamItem]:
    if not locators:
        return []
    roots, offsets = _stream_source_rows(
        db,
        tenant_id=tenant_id,
        locators=locators,
    )
    expense_entry_ids = {
        int(row["root_expense_id"])
        for row in locators
        if row["entry_kind"] == "expense"
    }
    response_by_id, offsets_by_expense_id = _expense_entry_context(
        db,
        tenant_id=tenant_id,
        roots=roots,
        expense_entry_ids=expense_entry_ids,
    )

    items: list[ConfirmedExpenseStreamItem] = []
    for locator in locators:
        root_id = int(locator["root_expense_id"])
        root = roots[root_id]
        if locator["entry_kind"] == "expense":
            items.append(
                _expense_stream_entry(
                    root,
                    response_by_id[root_id],
                    offsets_by_expense_id[root_id],
                    stream_date=locator["stream_date"],
                )
            )
        else:
            items.append(_offset_stream_entry(root, offsets[int(locator["offset_id"])]))
    return items


def _stream_source_rows(
    db: Session,
    *,
    tenant_id: str,
    locators: list[Mapping[str, object]],
) -> tuple[dict[int, Expense], dict[int, ExpenseOffsetFact]]:
    root_ids = {int(row["root_expense_id"]) for row in locators}
    roots = {
        expense.id: expense
        for expense in db.scalars(
            select(Expense)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.id.in_(root_ids))
        )
    }
    offset_ids = {
        int(row["offset_id"])
        for row in locators
        if row["entry_kind"] == "offset"
    }
    offsets = {
        offset.id: offset
        for offset in db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == tenant_id)
            .where(ExpenseOffsetFact.id.in_(offset_ids))
        )
    }
    return roots, offsets


def _expense_entry_context(
    db: Session,
    *,
    tenant_id: str,
    roots: dict[int, Expense],
    expense_entry_ids: set[int],
) -> tuple[dict[int, ExpenseResponse], dict[int, list[ExpenseOffsetFact]]]:
    response_by_id = {
        response.id: response
        for response in expenses_to_responses(
            db,
            tenant_id=tenant_id,
            expenses=[roots[expense_id] for expense_id in expense_entry_ids],
        )
    }
    offsets_by_expense_id: dict[int, list[ExpenseOffsetFact]] = defaultdict(list)
    if expense_entry_ids:
        active_offsets = db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == tenant_id)
            .where(ExpenseOffsetFact.expense_id.in_(expense_entry_ids))
            .where(ExpenseOffsetFact.status == "active")
        )
        for offset in active_offsets:
            offsets_by_expense_id[offset.expense_id].append(offset)
    return response_by_id, offsets_by_expense_id


def _expense_stream_entry(
    root: Expense,
    response: ExpenseResponse,
    active_offsets: list[ExpenseOffsetFact],
    *,
    stream_date: date,
) -> ConfirmedExpenseStreamEntry:
    summary = expense_financial_summary(root, active_offsets)
    return ConfirmedExpenseStreamEntry(
        **response.model_dump(),
        stream_date=stream_date,
        stream_amount_cents=0 if summary.status == "reversed" else int(root.amount_cents or 0),
        lineage_status=summary.status,
        lineage_home_net_cents=summary.lineage_home_net_cents,
    )


def _offset_stream_entry(
    root: Expense,
    offset: ExpenseOffsetFact,
) -> ConfirmedOffsetStreamEntry:
    return ConfirmedOffsetStreamEntry(
        public_id=offset.public_id,
        kind=offset.kind,
        stream_date=offset.accounting_date,
        stream_amount_cents=0 if offset.kind == "reversal" else -offset.amount_cents,
        amount_cents=offset.amount_cents,
        original_amount_minor=offset.original_amount_minor,
        original_currency_code=offset.original_currency_code,
        home_currency_code=offset.home_currency_code,
        root_expense_id=root.id,
        root_expense_public_id=root.public_id,
        root_merchant_label=root.merchant,
        category=offset.category,
    )
