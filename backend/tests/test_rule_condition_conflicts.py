"""A keyword alone cannot prove that an amount-bearing rule is redundant."""

from types import SimpleNamespace

from app.models import CategoryRule
from app.services.rule_conflict_service import find_rule_conflicts


def _rule(rule_id, **fields):
    return CategoryRule(id=rule_id, keyword="store", category="购物", enabled=True, priority=rule_id, **fields)


def test_different_recorded_currencies_are_not_declared_redundant():
    rules = [_rule(1, amount_min_cents=5000, home_currency_code="JPY"),
        _rule(2, amount_min_cents=5000, home_currency_code="CNY")]
    assert find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner") == []


def test_disjoint_thresholds_and_sources_do_not_hide_each_other():
    rules = [_rule(1, amount_min_cents=5000, home_currency_code="JPY"),
        _rule(2, amount_max_cents=4000, home_currency_code="JPY")]
    assert find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner") == []
    rules = [_rule(1, source_contains="alipay"), _rule(2, source_contains="wechat")]
    assert find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner") == []


def test_proven_superset_still_reports_redundancy():
    rules = [_rule(1, amount_min_cents=1000, home_currency_code="JPY"),
        _rule(2, amount_min_cents=5000, home_currency_code="JPY")]
    findings = find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner")
    assert len(findings) == 1 and findings[0].kind == "redundant"
