"""The recorded purpose of a category choice, read in batches for personal recall."""

import json

from sqlalchemy import select

from app.models import ExpenseFunding, ExpenseItem


def _text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def category_contexts(db, *, tenant_id: str, expenses: list) -> dict[int, dict]:
    contexts = {row.id: {"currency": row.original_currency_code or row.home_currency_code,
        "note": _text(row.note), "tags": sorted(_text(row.tags).split(",")), "items": [], "accounts": []}
        for row in expenses}
    if not contexts:
        return contexts
    items = db.scalars(select(ExpenseItem).where(ExpenseItem.tenant_id == tenant_id,
        ExpenseItem.expense_id.in_(contexts), ExpenseItem.kind == "product"))
    for item in items:
        contexts[item.expense_id]["items"].append(_text(item.name))
    funding = db.scalars(select(ExpenseFunding).where(ExpenseFunding.tenant_id == tenant_id,
        ExpenseFunding.expense_id.in_(contexts), ExpenseFunding.voided_at.is_(None)))
    for part in funding:
        contexts[part.expense_id]["accounts"].append(part.account_id)
    for context in contexts.values():
        context["items"] = sorted(set(context["items"]))
        context["accounts"] = sorted(set(context["accounts"]))
    return contexts


def category_context_key(context: dict) -> str:
    return json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
