"""Merchant ranking and category comparisons over the already projected stream."""

from collections import defaultdict

from app.services.category_service import normalize_category
from app.services.merchant_alias_service import canonical_merchant_for
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.reports_service._aggregation import _amount_count, _amount_delta
from app.services.spending_contract_service import enabled_merchant_display_map


def _canonical_display(merchant, alias_map):
    display = display_merchant(merchant)
    if not display:
        return "未填写商家"
    return display_merchant(canonical_merchant_for(display, alias_map=alias_map)) or display


def _merchant_ranking(db, entries, *, tenant_id, top_n, category, ranking_metric):
    alias_map = enabled_merchant_display_map(db, tenant_id=tenant_id)
    grouped = defaultdict(list)
    names = {}
    for entry in entries:
        if category and entry.category != normalize_category(category):
            continue
        display = _canonical_display(entry.merchant or "", alias_map)
        key = normalize_merchant(display) or "__empty_merchant__"
        names[key] = display
        grouped[key].append(entry)
    rows = []
    for key, values in grouped.items():
        amount, count = _amount_count(values)
        rows.append({"merchant": names[key], "amount_cents": amount, "count": count})
    complete = all(row["amount_cents"] is not None for row in rows)
    if ranking_metric == "amount":
        if not complete:
            return []
        return sorted(rows, key=lambda row: (-row["amount_cents"], -row["count"], row["merchant"]))[:top_n]
    # Unknown amounts cannot break equal-count ties as though they were zero.
    return sorted(rows, key=lambda row: (-row["count"],
        -row["amount_cents"] if complete else 0, row["merchant"]))[:top_n]


def _category_totals(entries):
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.category].append(entry)
    return {category: _amount_count(rows) for category, rows in grouped.items()}


def _category_comparison(current, previous, year_over_year):
    periods = [_category_totals(entries) for entries in (current, previous, year_over_year)]
    items = []
    for category in set().union(*periods):
        (amount, count), (prev_amount, prev_count), (yoy_amount, yoy_count) = [
            period.get(category, (0, 0)) for period in periods]
        items.append({"category": category, "amount_cents": amount, "count": count,
            "previous_amount_cents": prev_amount, "previous_count": prev_count,
            "delta_amount_cents": _amount_delta(amount, prev_amount), "delta_count": count - prev_count,
            "year_over_year_amount_cents": yoy_amount, "year_over_year_count": yoy_count,
            "year_over_year_delta_amount_cents": _amount_delta(amount, yoy_amount),
            "year_over_year_delta_count": count - yoy_count})
    if any(row["amount_cents"] is None for row in items):
        return sorted(items, key=lambda row: row["category"])
    previous_complete = all(row["previous_amount_cents"] is not None for row in items)
    return sorted(items, key=lambda row: (-row["amount_cents"],
        -row["previous_amount_cents"] if previous_complete else 0, row["category"]))
