"""v1.2 P2 — rule conflict / shadowing detection contract."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import CategoryRule
from app.services.rule_conflict_service import find_rule_conflicts


def _add_rule(
    *,
    tenant_id: str = "owner",
    keyword: str,
    category: str,
    priority: int,
    enabled: bool = True,
) -> int:
    with SessionLocal() as db:
        rule = CategoryRule(
            tenant_id=tenant_id,
            keyword=keyword,
            category=category,
            enabled=enabled,
            priority=priority,
        )
        db.add(rule)
        db.commit()
        return rule.id


def test_no_findings_with_orthogonal_rules(*, identity) -> None:
    _add_rule(keyword="xpj_test_burger", category="餐饮", priority=10)
    _add_rule(keyword="xpj_test_coffee", category="餐饮", priority=10)
    with SessionLocal() as db:
        assert find_rule_conflicts(db, tenant_id="owner") == []


def test_same_keyword_different_category_is_conflict(*, identity) -> None:
    winner_id = _add_rule(keyword="xpj_test_canteen", category="餐饮", priority=10)
    loser_id = _add_rule(keyword="xpj_test_canteen", category="其他", priority=20)
    with SessionLocal() as db:
        findings = find_rule_conflicts(db, tenant_id="owner")
        assert len(findings) == 1
        f = findings[0]
        assert f.kind == "conflict"
        assert f.primary_rule_id == winner_id
        assert f.secondary_rule_id == loser_id


def test_same_keyword_same_category_is_redundant(*, identity) -> None:
    a = _add_rule(keyword="xpj_test_starb", category="餐饮", priority=10)
    b = _add_rule(keyword="xpj_test_starb", category="餐饮", priority=20)
    with SessionLocal() as db:
        findings = find_rule_conflicts(db, tenant_id="owner")
        assert len(findings) == 1
        assert findings[0].kind == "redundant"
        assert findings[0].primary_rule_id == a
        assert findings[0].secondary_rule_id == b


def test_substring_keyword_shadows_longer_one(*, identity) -> None:
    short = _add_rule(keyword="cafe", category="餐饮", priority=10)
    long = _add_rule(keyword="cafe latte", category="餐饮", priority=20)
    with SessionLocal() as db:
        findings = find_rule_conflicts(db, tenant_id="owner")
        # Same category + different keyword = shadow, not redundant.
        assert any(f.kind == "shadow" for f in findings)
        shadow = next(f for f in findings if f.kind == "shadow")
        assert shadow.primary_rule_id == short
        assert shadow.secondary_rule_id == long


def test_disabled_rules_excluded(*, identity) -> None:
    _add_rule(keyword="xpj_test_canteen", category="餐饮", priority=10)
    _add_rule(keyword="xpj_test_canteen", category="其他", priority=20, enabled=False)
    with SessionLocal() as db:
        # The disabled rule doesn't count — no conflict to report.
        assert find_rule_conflicts(db, tenant_id="owner") == []


def test_tenant_isolation(*, identity) -> None:
    _add_rule(tenant_id="owner", keyword="xpj_test_canteen", category="餐饮", priority=10)
    _add_rule(tenant_id="tester_1", keyword="xpj_test_canteen", category="其他", priority=10)
    with SessionLocal() as db:
        owner_findings = find_rule_conflicts(db, tenant_id="owner")
        tester_findings = find_rule_conflicts(db, tenant_id="tester_1")
        # Each tenant has exactly one rule of its own; no conflict
        # within either tenant.
        assert owner_findings == []
        assert tester_findings == []
