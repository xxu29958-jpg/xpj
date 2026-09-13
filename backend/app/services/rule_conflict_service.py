"""v1.2 P2 — detect conflicts and shadowing in the user's category rules.

Three classes of issue:

* ``conflict`` — two enabled rules share the same keyword but target
  different categories. The user almost certainly intended one of
  them; we report the pair so the UI can prompt for resolution.
* ``redundant`` — two enabled rules share the same keyword AND target
  category. The lower-priority rule never fires; safe to delete.
* ``shadow`` — a higher-priority rule's keyword is a strict substring
  of a lower-priority rule's keyword. Because ``classify_expense``
  uses substring match, the broader (high-priority) rule always wins
  and the narrower rule never gets a turn.

The service is read-only; it never disables or modifies rules. The UI
surfaces findings; the user clicks "fix" which routes to the regular
rule mutation endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategoryRule
from app.services.tag_service import tag_key

ConflictKind = Literal["conflict", "redundant", "shadow"]


@dataclass(frozen=True)
class RuleConflictFinding:
    kind: ConflictKind
    primary_rule_id: int
    primary_keyword: str
    secondary_rule_id: int
    secondary_keyword: str
    detail: str


def _enabled_rules(db: Session, tenant_id: str) -> list[CategoryRule]:
    return list(
        db.scalars(
            select(CategoryRule)
            .where(CategoryRule.tenant_id == tenant_id)
            .where(CategoryRule.enabled == True)  # noqa: E712
            .where(CategoryRule.deleted_at.is_(None))
            .order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())
        )
    )


def _conditions_cover(high: CategoryRule, low: CategoryRule) -> bool:
    """Prove static coverage; never compare threshold integers across currencies."""
    return (
        _source_condition_covers(high.source_contains, low.source_contains)
        and _tag_condition_covers(high.tag_contains, low.tag_contains)
        and _amount_range_covers(high, low)
    )


def _source_condition_covers(high: str | None, low: str | None) -> bool:
    return not high or high.casefold() in (low or "").casefold()


def _tag_condition_covers(high: str | None, low: str | None) -> bool:
    return not high or tag_key(high) == tag_key(low or "")


def _amount_range_covers(high: CategoryRule, low: CategoryRule) -> bool:
    """An unconstrained rule covers all amounts; bounded rules need the same currency."""
    if high.amount_min_cents is None and high.amount_max_cents is None:
        return True
    if high.home_currency_code is None or high.home_currency_code != low.home_currency_code:
        return False
    if high.amount_min_cents is not None and (low.amount_min_cents is None or low.amount_min_cents < high.amount_min_cents):
        return False
    return high.amount_max_cents is None or (
        low.amount_max_cents is not None and low.amount_max_cents <= high.amount_max_cents
    )


def find_rule_conflicts(
    db: Session, *, tenant_id: str
) -> list[RuleConflictFinding]:
    """Return every (rule, rule) pair that triggers one of the three
    issue classes. Pairs are not de-duplicated across kinds — a true
    conflict between A and B always shows up exactly once."""

    rules = _enabled_rules(db, tenant_id=tenant_id)
    findings: list[RuleConflictFinding] = []

    by_keyword: dict[str, list[CategoryRule]] = {}
    for rule in rules:
        by_keyword.setdefault(rule.keyword.casefold(), []).append(rule)
    for _keyword_cf, bucket in by_keyword.items():
        if len(bucket) < 2:
            continue
        # Sort by (priority asc, id asc) so the "winner" is bucket[0].
        winner = bucket[0]
        for other in bucket[1:]:
            if not _conditions_cover(winner, other):
                continue
            if winner.category == other.category:
                findings.append(
                    RuleConflictFinding(
                        kind="redundant",
                        primary_rule_id=winner.id,
                        primary_keyword=winner.keyword,
                        secondary_rule_id=other.id,
                        secondary_keyword=other.keyword,
                        detail=(
                            f"同关键词 '{winner.keyword}' 同分类 "
                            f"'{winner.category}'，第 2 条规则永远不会触发。"
                        ),
                    )
                )
            else:
                findings.append(
                    RuleConflictFinding(
                        kind="conflict",
                        primary_rule_id=winner.id,
                        primary_keyword=winner.keyword,
                        secondary_rule_id=other.id,
                        secondary_keyword=other.keyword,
                        detail=(
                            f"同关键词 '{winner.keyword}' 命中不同分类 "
                            f"({winner.category} vs {other.category})，"
                            "高优先级先赢。"
                        ),
                    )
                )

    # Shadowing: for each pair (high_prio, low_prio) where the high
    # priority rule's keyword is a strict substring of the low
    # priority rule's keyword, the high priority rule always fires
    # first and the more specific rule never runs.
    for i, rule_high in enumerate(rules):
        for rule_low in rules[i + 1 :]:
            if rule_high.id == rule_low.id:
                continue
            high_kw = rule_high.keyword.casefold()
            low_kw = rule_low.keyword.casefold()
            if high_kw == low_kw:
                continue  # handled by the same-keyword bucket above
            if high_kw and high_kw in low_kw and _conditions_cover(rule_high, rule_low):
                findings.append(
                    RuleConflictFinding(
                        kind="shadow",
                        primary_rule_id=rule_high.id,
                        primary_keyword=rule_high.keyword,
                        secondary_rule_id=rule_low.id,
                        secondary_keyword=rule_low.keyword,
                        detail=(
                            f"高优先级关键词 '{rule_high.keyword}' 是 "
                            f"'{rule_low.keyword}' 的子串，后者不会触发。"
                        ),
                    )
                )
    return findings


__all__ = ["ConflictKind", "RuleConflictFinding", "find_rule_conflicts"]
