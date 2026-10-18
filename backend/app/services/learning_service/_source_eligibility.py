"""Eligibility of existing feedback; this module does not change scoring or train a model."""

import json
from collections import Counter

from sqlalchemy import select

from app.models import Expense, ExpenseOffsetFact, LedgerLearningEvent
from app.services.time_service import ensure_utc


def effective_expense_predicate():
    return ~select(ExpenseOffsetFact.id).where(ExpenseOffsetFact.tenant_id == Expense.tenant_id,
        ExpenseOffsetFact.expense_id == Expense.id, ExpenseOffsetFact.kind == "reversal",
        ExpenseOffsetFact.status == "active").exists()


def source_context(expense):
    return {"public_id": expense.public_id, "row_version": expense.row_version,
        "merchant": (expense.merchant or "").strip().casefold(), "category": expense.category,
        "amount_cents": expense.amount_cents, "original_currency_code": expense.original_currency_code,
        "original_amount_minor": expense.original_amount_minor,
        "expense_time": ensure_utc(expense.expense_time).isoformat() if expense.expense_time else None,
        "image_hash": expense.image_hash}


def decision_context(expense, decision_type, actor_account_id):
    snapshot = source_context(expense)
    required = ("public_id", "merchant", "category") if decision_type == "category_suggestion" else (
        "public_id", "merchant", "amount_cents", "original_currency_code",
        "original_amount_minor", "expense_time", "image_hash")
    return {**{name: snapshot[name] for name in required}, "actor_account_id": actor_account_id}


def capture_feedback_context(db, draft):
    payload = dict(draft.after_payload or {})
    if draft.subject_kind == "expense" and draft.subject_id is not None:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == draft.tenant_id, Expense.id == draft.subject_id))
        if expense is not None:
            payload["_source_context"] = source_context(expense)
    return payload


def feedback_sources(db, *, tenant_id, events):
    identifiers = {row.subject_id for row in events if row.subject_kind == "expense"}
    sources = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_(identifiers)))} if identifiers else {}
    reversed_ids = set(db.scalars(select(ExpenseOffsetFact.expense_id).where(
        ExpenseOffsetFact.tenant_id == tenant_id, ExpenseOffsetFact.expense_id.in_(identifiers),
        ExpenseOffsetFact.kind == "reversal", ExpenseOffsetFact.status == "active"))) if identifiers else set()
    return sources, reversed_ids


def feedback_eligibility(event, expense, reversed_ids):
    """Keep original feedback, with independent field decisions for a read-only preview."""
    if expense is None:
        return "invalid", "来源账目不存在或不在本账本", {}
    try:
        context = json.loads(event.after_payload or "{}").get("_source_context")
    except (TypeError, ValueError, AttributeError):
        context = None
    if not isinstance(context, dict) or event.actor_account_id is None:
        return "needs_review", "缺少原字段或明确操作人的证据，未用于学习", {}
    current = source_context(expense)
    fields = {name: ("valid" if context.get(name) == current[name] else "superseded")
        for name in ("merchant", "category", "amount_cents", "original_currency_code",
            "original_amount_minor", "expense_time", "image_hash")}
    if expense.status == "rejected" or expense.id in reversed_ids:
        return "invalid", "消费已撤销或已冲正；商家等未变字段仍保留原反馈证据", fields
    required = ("merchant", "category") if event.signal_type == "category_suggestion" else (
        "merchant", "amount_cents", "original_currency_code", "original_amount_minor", "expense_time", "image_hash")
    if context.get("public_id") != expense.public_id or any(fields[name] != "valid" for name in required):
        return "superseded", "此建议依赖的来源字段已更正", fields
    return "valid", "来源与此字段反馈仍一致", fields


def eligible_feedback(db, *, tenant_id, events, actor_account_id):
    if actor_account_id is None:
        return []
    events = [row for row in events if row.tenant_id == tenant_id and row.actor_account_id == actor_account_id]
    sources, reversed_ids = feedback_sources(db, tenant_id=tenant_id, events=events)
    return [row for row in events if feedback_eligibility(row, sources.get(row.subject_id), reversed_ids)[0] == "valid"]


def feedback_impact_preview(db, *, tenant_id):
    # No data rewrite, no new label inferred from historical defaults. The admin
    # sees counts; original individual feedback stays in its existing history.
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.subject_kind == "expense",
        LedgerLearningEvent.signal_type.in_(("category_suggestion", "duplicate_candidate")))))
    sources, reversed_ids = feedback_sources(db, tenant_id=tenant_id, events=events)
    counts = Counter(feedback_eligibility(row, sources.get(row.subject_id), reversed_ids)[0] for row in events)
    return {name: counts[name] for name in ("valid", "invalid", "superseded", "needs_review")}
