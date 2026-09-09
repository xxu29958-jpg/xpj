"""Read-only category-rule matching shared by classification and bulk consent."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import CategoryRule, Expense
from app.services.category_service import normalize_category
from app.services.merchant_alias_service import canonical_merchant_for
from app.services.money_projection_service import project_recorded_amount
from app.services.tag_service import parse_tags, tag_key


def casefold_join(parts: list[str]) -> str:
    return " ".join(part for part in parts if part).casefold()


def merchant_context(expense: Expense, alias_map: dict[str, str]) -> list[str]:
    raw = expense.merchant or ""
    canonical = canonical_merchant_for(raw, alias_map=alias_map)
    return [raw, canonical] if canonical and canonical != raw else [raw]


@dataclass(frozen=True)
class RuleMatch:
    rule_id: int | None = None
    matched_keyword: str = ""
    category: str | None = None
    unavailable: bool = False
    # Actual projected integers, including unavailable attempts, bind bulk
    # preview consent. An FX correction must invalidate the old preview.
    money_evidence: tuple[tuple[int, int | None], ...] = ()


def _nonmonetary_conditions_match(expense: Expense, rule: CategoryRule) -> bool:
    if rule.source_contains and rule.source_contains.casefold() not in (expense.source or "").casefold():
        return False
    if rule.tag_contains:
        wanted = tag_key(rule.tag_contains)
        if wanted not in {tag_key(tag) for tag in parse_tags(expense.tags)}:
            return False
    return True


def _rule_amount(db: Session, expense: Expense, rule: CategoryRule) -> int | None:
    from app.services.spending_contract_service import accounting_zone, stat_time

    if expense.amount_cents is None:
        return None
    instant = stat_time(expense)
    rate_date = instant.astimezone(accounting_zone()).date() if instant else None
    return project_recorded_amount(db, tenant_id=expense.tenant_id, amount_minor=expense.amount_cents,
        source_currency=expense.home_currency_code, home_currency=rule.home_currency_code, rate_date=rate_date)


def match_category_rule(db: Session, expense: Expense, rules: list[CategoryRule], *, haystack: str) -> RuleMatch:
    evidence: list[tuple[int, int | None]] = []
    for rule in rules:
        if rule.keyword.casefold() not in haystack or not _nonmonetary_conditions_match(expense, rule):
            continue
        if rule.amount_min_cents is not None or rule.amount_max_cents is not None:
            amount = _rule_amount(db, expense, rule)
            evidence.append((rule.id, amount))
            if amount is None:
                return RuleMatch(rule_id=rule.id, matched_keyword=rule.keyword,
                    unavailable=True, money_evidence=tuple(evidence))
            if rule.amount_min_cents is not None and amount < rule.amount_min_cents:
                continue
            if rule.amount_max_cents is not None and amount > rule.amount_max_cents:
                continue
        return RuleMatch(rule_id=rule.id, matched_keyword=rule.keyword,
            category=normalize_category(rule.category) or None, money_evidence=tuple(evidence))
    return RuleMatch(money_evidence=tuple(evidence))
