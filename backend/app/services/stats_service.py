from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Expense, ExpenseTag, Tag
from app.services.category_service import list_ledger_category_options
from app.services.csv_security import safe_csv_cell
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.expense_service import filtered_confirmed_stream
from app.services.ledger_calendar_service import current_calendar
from app.services.money_projection_service import sum_projected_amounts
from app.services.spending_contract_service import (
    accounting_zone,
    calendar_month_bounds,
    canonical_merchant_display,
    confirmed_stream_query,
    current_accounting_month,
    enabled_merchant_display_map,
)
from app.services.spending_contract_service import (
    clean_month as _contract_clean_month,
)
from app.services.spending_contract_service import (
    stat_time as _contract_stat_time,
)
from app.services.spending_projection_service import entry_gaps, read_spending_period
from app.services.stats_money import (
    export_money_values as _export_money_values,
)
from app.services.time_service import (
    ensure_utc,
    now_utc,
)


def _stat_time(expense: Expense):
    return _contract_stat_time(expense)


def _clean_month_filter(month: str) -> str:
    return _contract_clean_month(month)


def list_categories(db: Session, tenant_id: str) -> list[str]:
    return list_ledger_category_options(db, tenant_id=tenant_id)


def list_months(
    db: Session, tenant_id: str, timezone_name: str | None = None
) -> list[str]:
    resolved_timezone = current_calendar(db, ledger_id=tenant_id).timezone_name
    current_month_label = current_accounting_month(resolved_timezone)
    stream = confirmed_stream_query(
        tenant_id=tenant_id,
        timezone_name=resolved_timezone,
    )
    months = {
        stream_date.strftime("%Y-%m")
        for stream_date in db.scalars(
            select(stream.c.stream_date).where(stream.c.stream_date.is_not(None))
        )
        if stream_date.strftime("%Y-%m") <= current_month_label
    }
    return sorted(months, reverse=True)


def export_confirmed_csv(
    db: Session,
    *,
    tenant_id: str,
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone_name: str | None = None,
) -> str:
    entries = filtered_confirmed_stream(
        db,
        tenant_id=tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone_name,
    )
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "public_id",
            "amount_cents",
            "amount_yuan",
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_to_cny",
            "exchange_rate_date",
            "exchange_rate_source",
            "merchant",
            "category",
            "note",
            "source",
            "expense_time",
            "confirmed_at",
            "tags",
            "value_score",
            "regret_score",
            # Append-only currency-aware replacements.  Keep every released
            # column above in its original position for positional consumers.
            "home_currency_code",
            "amount_home_major",
            "entry_kind",
            "offset_kind",
            "root_expense_id",
            "root_expense_public_id",
            "stream_date",
            "stream_amount_cents",
            "lineage_status",
            "lineage_home_net_cents",
            "accounting_time",
        ]
    )
    for entry in entries:
        writer.writerow(_confirmed_stream_csv_row(entry))
    return output.getvalue()


def _export_stream_date(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def _confirmed_stream_csv_row(entry) -> list:
    root = entry.root
    if entry.entry_kind == "expense":
        amount_cents, amount_yuan, amount_home_major = _export_money_values(
            amount_cents=root.amount_cents,
            home_currency_code=root.home_currency,
            label="stats.export_expense_response",
        )
        stat_time = _stat_time(root)
        confirmed_at = ensure_utc(root.confirmed_at)
        return [
            root.id,
            root.public_id,
            amount_cents,
            amount_yuan,
            root.original_currency_code,
            root.original_amount_minor if root.original_amount_minor is not None else "",
            root.exchange_rate_to_cny if root.exchange_rate_to_cny is not None else "",
            root.exchange_rate_date.isoformat() if root.exchange_rate_date else "",
            safe_csv_cell(root.exchange_rate_source or ""),
            safe_csv_cell(root.merchant or ""),
            safe_csv_cell(root.category),
            safe_csv_cell(root.note or ""),
            safe_csv_cell(root.source),
            stat_time.isoformat().replace("+00:00", "Z") if stat_time else "",
            confirmed_at.isoformat().replace("+00:00", "Z") if confirmed_at else "",
            safe_csv_cell(root.tags or ""),
            root.value_score or "",
            root.regret_score or "",
            root.home_currency,
            amount_home_major,
            entry.entry_kind,
            "",
            root.id,
            root.public_id,
            _export_stream_date(entry.stream_date),
            entry.stream_amount_cents,
            entry.lineage_status,
            entry.lineage_home_net_cents,
            _export_accounting_time(root),
        ]
    offset = entry.offset
    if offset is None:
        raise ValueError("offset CSV row requires an offset projection")
    amount_cents, amount_yuan, amount_home_major = _export_money_values(
        amount_cents=offset.amount_cents,
        home_currency_code=offset.home_currency_code,
        label="stats.export_offset_response",
    )
    return [
        "",
        offset.public_id,
        amount_cents,
        amount_yuan,
        offset.original_currency_code,
        offset.original_amount_minor,
        offset.exchange_rate_to_cny,
        offset.exchange_rate_date,
        safe_csv_cell(offset.exchange_rate_source),
        safe_csv_cell(root.merchant or ""),
        safe_csv_cell(offset.category),
        "",
        "",
        _export_stream_date(entry.stream_date),
        "",
        "",
        "",
        "",
        offset.home_currency_code,
        amount_home_major,
        entry.entry_kind,
        offset.kind,
        root.id,
        root.public_id,
        _export_stream_date(entry.stream_date),
        entry.stream_amount_cents,
        entry.lineage_status,
        entry.lineage_home_net_cents,
        _export_accounting_time(offset),
    ]


def _export_accounting_time(fact) -> str:
    snapshot = fact.accounting_time
    return json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False) if snapshot is not None else ""


def _amount_rows(grouped, key):
    rows = [{key: name, "amount_cents": sum_projected_amounts(
        (entry.amount_cents for entry in entries), label=f"stats.{key}_total"), "count": len(entries)}
        for name, entries in grouped.items()]
    if any(row["amount_cents"] is None for row in rows):
        return sorted(rows, key=lambda row: row[key])
    return sorted(rows, key=lambda row: (-row["amount_cents"], -row["count"], row[key]))


def _category_rows(entries):
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.category].append(entry)
    return _amount_rows(grouped, "category")


def _tag_rows(db, *, tenant_id, entries):
    roots = {entry.root_expense_id for entry in entries}
    if not roots:
        return []
    tags_by_root = defaultdict(set)
    for root_id, tag in db.execute(select(ExpenseTag.expense_id, Tag.name)
        .join(Tag, (Tag.id == ExpenseTag.tag_id) & (Tag.tenant_id == tenant_id))
        .where(ExpenseTag.tenant_id == tenant_id, ExpenseTag.expense_id.in_(roots), Tag.deleted_at.is_(None))):
        tags_by_root[root_id].add(tag)
    grouped = defaultdict(list)
    for entry in entries:
        for tag in tags_by_root[entry.root_expense_id]:
            grouped[tag].append(entry)
    return _amount_rows(grouped, "tag")


def _read_stats_entries(db, *, tenant_id, month, timezone_name, home_currency_code, tag=None):
    home = normalize_currency_code(home_currency_code or require_runtime_home_currency_code(db))
    projection = read_spending_period(db, tenant_id=tenant_id, ranges=[calendar_month_bounds(month)],
        timezone_name=timezone_name, home=home, tag=tag)
    return home, projection


def monthly_stats(db: Session, month: str, tenant_id: str, timezone_name: str | None = None,
    tag: str | None = None, home_currency_code: str | None = None,
) -> dict:
    month = _clean_month_filter(month)
    home, projection = _read_stats_entries(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name,
        home_currency_code=home_currency_code, tag=tag)
    entries = projection.entries
    undated = projection.undated_expense_count
    return {"month": month, "home_currency_code": home, "missing_rates": entry_gaps(entries),
        "undated_expense_count": undated,
        "total_amount_cents": None if undated else sum_projected_amounts((entry.amount_cents for entry in entries), label="stats.month_total"),
        "count": len(entries), "by_category": _category_rows(entries),
        "by_tag": _tag_rows(db, tenant_id=tenant_id, entries=entries)}


def _rank_score_group(expenses, amount_by_id):
    amounts_known = all(amount_by_id[item.id] is not None for item in expenses)

    def key(item):
        time = _stat_time(item)
        return (-(amount_by_id[item.id] if amounts_known else 0),
            -time.timestamp() if time is not None else 0, -item.id)

    return sorted(expenses, key=key)


def _ranked_scored_expenses(expenses, *, amount_by_id, score_attr, limit=5):
    groups = defaultdict(list)
    for item in expenses:
        score = getattr(item, score_attr)
        if score is not None:
            groups[score].append(item)
    ranked = [item for score in sorted(groups, reverse=True)
        for item in _rank_score_group(groups[score], amount_by_id)]
    return ranked[:limit]


def _highest_expense(expenses: Sequence[Expense], amount_by_id: Mapping[int, int | None]) -> Expense | None:
    if any(amount_by_id[item.id] is None for item in expenses):
        return None
    positive = [item for item in expenses if amount_by_id[item.id] > 0]
    return max(positive, key=lambda item: (amount_by_id[item.id], item.id), default=None)


def _frequent_merchants(db, *, tenant_id, entries):
    alias_map = enabled_merchant_display_map(db, tenant_id=tenant_id)
    grouped = defaultdict(list)
    for entry in entries:
        if entry.merchant and entry.merchant.strip():
            grouped[canonical_merchant_display(entry.merchant, alias_map)].append(entry)
    rows = _amount_rows(grouped, "merchant")
    if any(entry.amount_cents is None for entry in entries):
        rows.sort(key=lambda row: (-row["count"], row["merchant"]))
    return rows[:5]


def _recent_seven_days(entries, *, month, timezone_name):
    zone = accounting_zone(timezone_name)
    start, end = calendar_month_bounds(month)
    last_day = min(now_utc().astimezone(zone).date(), end - timedelta(days=1))
    first_day = max(start, last_day - timedelta(days=6))
    return sum_projected_amounts((entry.amount_cents for entry in entries
        if first_day <= entry.stream_date <= last_day), label="stats.recent_seven_days")


def lifestyle_stats(db: Session, month: str, tenant_id: str, timezone_name: str | None = None,
    home_currency_code: str | None = None,
) -> dict:
    month = _clean_month_filter(month)
    timezone_name = current_calendar(db, ledger_id=tenant_id).timezone_name
    home, projection = _read_stats_entries(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name,
        home_currency_code=home_currency_code)
    entries = projection.entries
    amount_by_id = {entry.root_expense_id: entry.amount_cents for entry in entries if entry.entry_kind == "expense"}
    expenses = list(db.scalars(ledger_scoped_select(Expense, tenant_id).where(
        Expense.id.in_(amount_by_id)))) if amount_by_id else []
    categories = {row["category"]: row["amount_cents"] for row in _category_rows(entries)}
    undated_categories = projection.undated_by_category
    undated = sum(undated_categories.values())
    return {"month": month, "home_currency_code": home, "missing_rates": entry_gaps(entries),
        "undated_expense_count": undated,
        "ai_subscription_amount_cents": None if undated_categories.get("AI订阅") else categories.get("AI订阅", 0),
        "digital_amount_cents": None if undated_categories.get("数码") else categories.get("数码", 0),
        "max_expense": None if undated else _highest_expense(expenses, amount_by_id),
        "recent_7_days_amount_cents": None if undated else _recent_seven_days(entries, month=month, timezone_name=timezone_name),
        "frequent_merchants": _frequent_merchants(db, tenant_id=tenant_id, entries=entries),
        "best_value_expenses": _ranked_scored_expenses(expenses, amount_by_id=amount_by_id, score_attr="value_score"),
        "most_regretted_expenses": _ranked_scored_expenses(expenses, amount_by_id=amount_by_id, score_attr="regret_score")}
