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
            if high_kw and high_kw in low_kw:
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
