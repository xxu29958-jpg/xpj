"""Bounded search for the loopback-only /web surface."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import CategoryRule, Expense, Goal
from app.services.expense_search_query import matches_expense_search, matches_text
from app.services.spending_contract_service import (
    accounting_datetime_label,
    stat_time,
)
from app.services.web_stats_service import source_label

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
    currency_code: str | None = None


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


def _limited(statement: Select[tuple], limit: int) -> Select[tuple]:
    return statement.limit(limit)


def _expense_edit_href(expense_id: int, tenant_id: str, term: str) -> str:
    params = {
        "ledger_id": tenant_id,
        "return_to": "search",
        "return_query": term,
    }
    return f"/web/expenses/{expense_id}/edit?{urlencode(params)}"


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
        .where(matches_expense_search(db, tenant_id, term))
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )
    rows = db.scalars(_limited(statement, limit)).all()
    badge = "待确认" if status == "pending" else "已确认"
    return [
        WebSearchResult(
            group=status,
            title=expense.merchant or "未填写商家",
            subtitle=_expense_subtitle(expense),
            href=_expense_edit_href(expense.id, tenant_id, term),
            badge=badge,
            amount_cents=expense.amount_cents,
            currency_code=expense.home_currency_code,
        )
        for expense in rows
    ]


def _expense_subtitle(expense: Expense) -> str:
    parts = [
        expense.category or "未分类",
        source_label(expense.source, "未知来源"),
    ]
    when = stat_time(expense)
    if expense.accounting_date is not None:
        parts.append(expense.accounting_date.isoformat())
    elif expense.status == "confirmed":
        parts.append("账务日期待核对")
    elif when:
        parts.append("发生时刻 " + accounting_datetime_label(when))
    elif expense.created_at:
        parts.append("录入于 " + accounting_datetime_label(expense.created_at))
    return " · ".join(parts)


def _search_rules(db: Session, tenant_id: str, term: str, limit: int) -> list[WebSearchResult]:
    statement = (
        select(CategoryRule)
        .where(CategoryRule.tenant_id == tenant_id)
        .where(
            matches_text(
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
        .where(matches_text(term, Goal.name, Goal.category, Goal.month, Goal.status))
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
            currency_code=goal.home_currency_code,
        )
        for goal in db.scalars(_limited(statement, limit)).all()
    ]
