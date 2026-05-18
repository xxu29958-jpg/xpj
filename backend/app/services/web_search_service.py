"""Bounded search for the loopback-only /web surface."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import CategoryRule, Expense, Goal
from app.services.merchant_alias_service import list_merchant_aliases
from app.services.merchant_service import normalize_merchant


MAX_QUERY_LENGTH = 80
DEFAULT_GROUP_LIMIT = 6


@dataclass(frozen=True)
class WebSearchResult:
    group: str
    title: str
    subtitle: str
    href: str
    badge: str
    amount_cents: int | None = None


@dataclass(frozen=True)
class WebSearchGroup:
    key: str
    title: str
    results: list[WebSearchResult]


def search_web(
    db: Session,
    *,
    tenant_id: str,
    query: str,
    limit_per_group: int = DEFAULT_GROUP_LIMIT,
) -> list[WebSearchGroup]:
    """Search web-visible entities inside one ledger.

    This is intentionally scoped and bounded: no public API, no cross-ledger
    search, and every group has its own small result limit.
    """

    term = _clean_query(query)
    if not term:
        return [
            WebSearchGroup("pending", "待确认", []),
            WebSearchGroup("confirmed", "已确认", []),
            WebSearchGroup("rules", "规则", []),
            WebSearchGroup("goals", "目标", []),
        ]

    limit = max(1, min(limit_per_group, 12))
    return [
        WebSearchGroup("pending", "待确认", _search_expenses(db, tenant_id, term, "pending", limit)),
        WebSearchGroup("confirmed", "已确认", _search_expenses(db, tenant_id, term, "confirmed", limit)),
        WebSearchGroup("rules", "规则", _search_rules(db, tenant_id, term, limit)),
        WebSearchGroup("goals", "目标", _search_goals(db, tenant_id, term, limit)),
    ]


def _clean_query(query: str) -> str:
    return (query or "").strip()[:MAX_QUERY_LENGTH]


def _like_pattern(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches_text(term: str, *columns) -> object:
    return _matches_any_text([term], *columns)


def _matches_any_text(terms: list[str], *columns) -> object:
    patterns = [_like_pattern(term) for term in terms if term]
    if not patterns:
        patterns = [_like_pattern("")]
    predicates = []
    for column in columns:
        lowered = func.lower(func.coalesce(column, ""))
        predicates.extend(lowered.like(pattern, escape="\\") for pattern in patterns)
    return or_(*predicates)


def _merchant_search_terms(db: Session, tenant_id: str, term: str) -> list[str]:
    terms = {term}
    needle = term.casefold()
    normalized = normalize_merchant(term)
    for alias in list_merchant_aliases(db, tenant_id):
        if not alias.enabled:
            continue
        alias_values = {
            alias.alias,
            alias.alias_key,
            alias.canonical_merchant,
            alias.canonical_key,
        }
        alias_values_folded = {value.casefold() for value in alias_values if value}
        if (
            any(needle in value for value in alias_values_folded)
            or normalized in {alias.alias_key, alias.canonical_key}
        ):
            terms.add(alias.alias)
            terms.add(alias.canonical_merchant)
    return sorted(term for term in terms if term)


def _matches_expense_search(db: Session, tenant_id: str, term: str) -> object:
    merchant_terms = _merchant_search_terms(db, tenant_id, term)
    return or_(
        _matches_any_text(merchant_terms, Expense.merchant),
        _matches_text(
            term,
            Expense.category,
            Expense.note,
            Expense.source,
            Expense.tags,
            Expense.raw_text,
        ),
    )


def _limited(statement: Select[tuple], limit: int) -> Select[tuple]:
    return statement.limit(limit)


def _search_expenses(
    db: Session,
    tenant_id: str,
    term: str,
    status: str,
    limit: int,
) -> list[WebSearchResult]:
    statement = (
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == status)
        .where(_matches_expense_search(db, tenant_id, term))
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )
    rows = db.scalars(_limited(statement, limit)).all()
    badge = "待确认" if status == "pending" else "已确认"
    return [
        WebSearchResult(
            group=status,
            title=expense.merchant or "未填写商家",
            subtitle=_expense_subtitle(expense),
            href=f"/web/expenses/{expense.id}/edit?{urlencode({'ledger_id': tenant_id})}",
            badge=badge,
            amount_cents=expense.amount_cents,
        )
        for expense in rows
    ]


def _expense_subtitle(expense: Expense) -> str:
    parts = [
        expense.category or "未分类",
        expense.source or "未知来源",
    ]
    if expense.expense_time:
        parts.append(expense.expense_time.strftime("%Y-%m-%d %H:%M"))
    elif expense.created_at:
        parts.append(expense.created_at.strftime("%Y-%m-%d %H:%M"))
    return " · ".join(parts)


def _search_rules(db: Session, tenant_id: str, term: str, limit: int) -> list[WebSearchResult]:
    statement = (
        select(CategoryRule)
        .where(CategoryRule.tenant_id == tenant_id)
        .where(
            _matches_text(
                term,
                CategoryRule.keyword,
                CategoryRule.category,
                CategoryRule.source_contains,
                CategoryRule.tag_contains,
            )
        )
        .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
    )
    return [
        WebSearchResult(
            group="rules",
            title=rule.keyword,
            subtitle=f"改写到 {rule.category} · 优先级 {rule.priority}",
            href=f"/web/rules?{urlencode({'ledger_id': tenant_id})}",
            badge="规则" if rule.enabled else "已停用",
        )
        for rule in db.scalars(_limited(statement, limit)).all()
    ]


def _search_goals(db: Session, tenant_id: str, term: str, limit: int) -> list[WebSearchResult]:
    statement = (
        select(Goal)
        .where(Goal.tenant_id == tenant_id)
        .where(_matches_text(term, Goal.name, Goal.category, Goal.month, Goal.status))
        .order_by(Goal.month.desc(), Goal.status.asc(), Goal.created_at.desc())
    )
    return [
        WebSearchResult(
            group="goals",
            title=goal.name,
            subtitle=f"{goal.month} · {goal.category or '总支出'}",
            href=f"/web/goals?{urlencode({'ledger_id': tenant_id, 'month': goal.month})}",
            badge="目标" if goal.status == "active" else "已归档",
            amount_cents=goal.target_amount_cents,
        )
        for goal in db.scalars(_limited(statement, limit)).all()
    ]
