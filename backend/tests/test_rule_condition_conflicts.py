"""A keyword alone cannot prove that an amount-bearing rule is redundant."""

from types import SimpleNamespace

import pytest

from app.models import CategoryRule
from app.services.rule_conflict_service import find_rule_conflicts


def _rule(rule_id, **fields):
    return CategoryRule(id=rule_id, **{
        "keyword": "store", "category": "购物", "enabled": True, "priority": rule_id, **fields,
    })


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


@pytest.mark.parametrize(("high", "low", "covered"), [
    ({"source_contains": "Wallet"}, {"source_contains": "Travel WALLET"}, True),
    ({"source_contains": "wallet"}, {}, False),
    ({"tag_contains": "Trip"}, {"tag_contains": "trip"}, True),
    ({"tag_contains": "trip"}, {"tag_contains": "trip-2026"}, False),
    ({"tag_contains": "trip"}, {}, False),
    ({}, {"amount_min_cents": 100, "home_currency_code": "JPY"}, True),
    ({"amount_min_cents": 100}, {"amount_min_cents": 200}, False),
    ({"amount_max_cents": 500, "home_currency_code": "JPY"}, {"amount_max_cents": 400}, False),
    ({"amount_min_cents": 0}, {"amount_min_cents": 0}, False),
])
def test_text_tag_and_unknown_currency_coverage_boundaries(high, low, covered):
    rules = [_rule(1, **high), _rule(2, **low)]
    findings = find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner")
    assert bool(findings) is covered


@pytest.mark.parametrize(("high_range", "low_range", "covered"), [
    ((100, 500), (100, 500), True),
    ((100, 500), (200, 400), True),
    ((100, 500), (99, 400), False),
    ((100, 500), (200, 501), False),
    ((100, None), (None, 500), False),
    ((None, 500), (100, None), False),
    ((0, None), (0, None), True),
    ((None, None), (None, None), True),
])
def test_same_currency_coverage_requires_inclusive_range_containment(high_range, low_range, covered):
    rules = [_rule(index, amount_min_cents=bounds[0], amount_max_cents=bounds[1], home_currency_code="JPY")
        for index, bounds in enumerate((high_range, low_range), 1)]
    findings = find_rule_conflicts(SimpleNamespace(scalars=lambda *a: rules), tenant_id="owner")
    assert bool(findings) is covered


@pytest.mark.parametrize(("low_keyword", "low_category", "kind"), [
    ("store", "购物", "redundant"), ("store", "交通", "conflict"), ("travel store", "交通", "shadow"),
])
def test_all_finding_kinds_require_every_condition_to_cover(low_keyword, low_category, kind):
    high = _rule(1, source_contains="Wallet", tag_contains="Trip", amount_min_cents=100, home_currency_code="JPY")
    low = _rule(2, keyword=low_keyword, category=low_category, source_contains="Travel Wallet",
        tag_contains="trip", amount_min_cents=200, home_currency_code="JPY")
    db = SimpleNamespace(scalars=lambda *a: [high, low])
    assert [finding.kind for finding in find_rule_conflicts(db, tenant_id="owner")] == [kind]
    low.tag_contains = "other"
    assert find_rule_conflicts(db, tenant_id="owner") == []
