"""Independent personal category examples; accepted/default values never vote."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select

from app.models import Expense, LedgerLearningEvent
from app.services.category_service import list_ledger_category_options
from app.services.duplicate_evidence import _identifiers
from app.services.learning_service._category_context import category_context_key, category_contexts
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.merchant_alias_service import canonical_merchant_for, enabled_merchant_alias_map
from app.services.merchant_service import normalize_merchant


@dataclass
class CategoryMerchantScope:
    tenant_id: str
    aliases: dict[str, str]
    canonical_keys: set[str]
    names: dict[str, list[str]]


def load_category_merchant_scope(db, *, tenant_id: str, merchants: list[str | None]) -> CategoryMerchantScope:
    """Resolve stored names once for one response; never retain this across requests."""
    aliases = enabled_merchant_alias_map(db, tenant_id=tenant_id)
    canonical_keys = {normalize_merchant(value) for value in aliases.values()}
    groups = defaultdict(list)
    needed = {normalize_merchant(canonical_merchant_for(value, alias_map=aliases)) for value in merchants}
    if needed & canonical_keys:
        names = db.scalars(select(Expense.merchant).where(
            Expense.tenant_id == tenant_id, Expense.merchant.is_not(None)).distinct())
        for name in names:
            canonical = normalize_merchant(canonical_merchant_for(name, alias_map=aliases))
            if canonical in needed:
                groups[canonical].append(name)
    return CategoryMerchantScope(tenant_id, aliases, canonical_keys, dict(groups))


def category_merchant_filter(db, *, tenant_id: str, merchant: str, legacy_key: str,
        scope: CategoryMerchantScope | None = None):
    """Use the same explicit aliases as rules, including their normalization."""
    scope = scope or load_category_merchant_scope(db, tenant_id=tenant_id, merchants=[merchant])
    if scope.tenant_id != tenant_id:
        raise ValueError("Category merchant scope belongs to another ledger")
    canonical = normalize_merchant(canonical_merchant_for(merchant, alias_map=scope.aliases))
    if canonical not in scope.canonical_keys:
        return func.lower(func.trim(Expense.merchant)) == legacy_key
    # Resolve actual stored names, rather than approximating Python casefold,
    # whitespace and notification-suffix normalization with SQL lower().
    return Expense.merchant.in_(scope.names.get(canonical, []))


def _event_groups(examples, facts) -> list:
    groups = []
    for event, expense in examples:
        namespace, identifiers = _identifiers(expense, facts.get(expense.id))
        keys = {("expense", expense.id)}
        # duplicate_of_id is a recall candidate, never a confirmed event identity.
        if expense.image_hash:
            keys.add(("image", expense.image_hash))
        keys.update(("transaction", namespace, identifier) for identifier in identifiers if namespace)
        latest = (event.id, expense.category)
        remaining = []
        for known_keys, known_latest in groups:
            if keys & known_keys:
                keys.update(known_keys)
                latest = max(latest, known_latest)
            else:
                remaining.append((known_keys, known_latest))
        groups = [*remaining, (keys, latest)]
    return groups


def independent_category_rejects(db, *, tenant_id: str, events: list, expense_id: int | None) -> int:
    from app.services.learning_service import read_ocr_facts

    ids = {event.subject_id for event in events}
    sources = {row.id: row for row in db.scalars(select(Expense).where(
        Expense.tenant_id == tenant_id, Expense.id.in_(ids | {expense_id})))}
    contexts = category_contexts(db, tenant_id=tenant_id, expenses=list(sources.values()))
    target = contexts.get(expense_id)
    examples = [(event, sources[event.subject_id]) for event in events if event.subject_id in sources
        and (target is None or _event_payload(event).get("_category_context") == target)]
    facts = read_ocr_facts(db, tenant_id=tenant_id, expenses=[expense for _, expense in examples])
    return len(_event_groups(examples, facts))


def _personal_example_matches(event, expense, *, expense_id, observed_at, categories, contexts, target_key):
    payload = _event_payload(event)
    return (payload.get("_category_intent") == "manual"
        and expense.id != expense_id and expense.status == "confirmed"
        and (expense.confirmed_at is None or expense.confirmed_at <= observed_at)
        and expense.category in categories and payload.get("_category_context") == contexts[expense.id]
        and (target_key is None or category_context_key(contexts[expense.id]) == target_key))


def personal_category_counts(db, *, tenant_id: str, merchant_filter, actor_account_id: int,
        expense_id: int | None, cutoff, current_date, observed_at) -> list[tuple[str, int]]:
    from app.services.learning_service import read_ocr_facts

    rows = db.execute(select(LedgerLearningEvent, Expense)
        .join(Expense, Expense.id == LedgerLearningEvent.subject_id)
        .where(LedgerLearningEvent.tenant_id == tenant_id, Expense.tenant_id == tenant_id,
            LedgerLearningEvent.actor_account_id == actor_account_id,
            LedgerLearningEvent.signal_type == "category_suggestion", LedgerLearningEvent.subject_kind == "expense",
            LedgerLearningEvent.created_at <= observed_at, Expense.accounting_date >= cutoff,
            Expense.accounting_date <= current_date, merchant_filter)
        .order_by(LedgerLearningEvent.id.desc()).limit(200)).all()
    target = db.scalar(select(Expense).where(Expense.tenant_id == tenant_id, Expense.id == expense_id))
    sources = {expense.id: expense for _, expense in rows}
    if target is not None:
        sources[target.id] = target
    contexts = category_contexts(db, tenant_id=tenant_id, expenses=list(sources.values()))
    target_key = category_context_key(contexts[target.id]) if target is not None else None
    valid = {event.id for event in eligible_feedback(db, tenant_id=tenant_id,
        events=[event for event, _ in rows], actor_account_id=actor_account_id)}
    categories = set(list_ledger_category_options(db, tenant_id=tenant_id))
    examples = [(event, expense) for event, expense in rows if event.id in valid
        and _personal_example_matches(event, expense, expense_id=expense_id, observed_at=observed_at,
            categories=categories, contexts=contexts, target_key=target_key)]
    facts = read_ocr_facts(db, tenant_id=tenant_id, expenses=[expense for _, expense in examples])
    counts = Counter(latest[1] for _, latest in _event_groups(examples, facts))
    return counts.most_common()
