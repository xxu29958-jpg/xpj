"""Rule thresholds retain units, and unavailable conversion cannot choose a fallback."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import CategoryRule, Expense
from app.schemas import CategoryRuleCreateRequest, CategoryRuleUpdateRequest
from app.services import rule_service
from app.services.rule_application_service import _preview


@pytest.mark.parametrize("schema, fields", [
    (CategoryRuleCreateRequest, {"keyword": "store", "category": "购物"}),
    (CategoryRuleUpdateRequest, {"expected_row_version": 3}),
])
def test_monetary_rule_requires_explicit_units(schema, fields):
    with pytest.raises(ValidationError, match="home_currency_code"):
        schema(**fields, amount_min_cents=1200)
    request = schema(**fields, amount_min_cents=1200, home_currency_code="JPY")
    assert request.amount_min_cents == 1200 and request.home_currency_code == "JPY"


def test_nonmonetary_rule_can_remain_currencyless_and_clear_is_distinct_from_omitted():
    create = CategoryRuleCreateRequest(keyword="store", category="购物")
    assert create.home_currency_code is None
    toggle = CategoryRuleUpdateRequest(expected_row_version=3, enabled=False)
    assert "amount_min_cents" not in toggle.model_fields_set
    clear = CategoryRuleUpdateRequest(expected_row_version=3, amount_min_cents=None,
        amount_max_cents=None, home_currency_code=None)
    assert clear.model_dump(exclude_unset=True)["amount_min_cents"] is None


def _expense():
    return Expense(id=1, tenant_id="owner", category="其他", merchant="store", amount_cents=10000,
        home_currency_code="CNY", row_version=1, expense_time=datetime(2026, 9, 3, tzinfo=UTC),
        created_at=datetime(2026, 9, 3, tzinfo=UTC), updated_at=datetime(2026, 9, 3, tzinfo=UTC))


def _rules():
    return [CategoryRule(id=1, tenant_id="owner", keyword="store", category="购物", enabled=True,
        priority=1, amount_min_cents=5000, home_currency_code="JPY"),
        CategoryRule(id=2, tenant_id="owner", keyword="store", category="餐饮", enabled=True, priority=2)]


def _preview_with(monkeypatch, *, projected):
    expense, rules = _expense(), _rules()
    observed = []
    def project(_db, **kwargs):
        observed.append(kwargs)
        return projected
    monkeypatch.setattr(rule_service, "project_recorded_amount", project)
    monkeypatch.setattr(_preview, "_rule_application_candidates", lambda *a, **k: ([expense], False))
    monkeypatch.setattr(_preview, "_enabled_rules", lambda *a, **k: rules)
    monkeypatch.setattr(_preview, "enabled_merchant_alias_map", lambda *a, **k: {})
    monkeypatch.setattr(_preview, "_ocr_text_by_expense_id", lambda *a, **k: {})
    monkeypatch.setattr(_preview, "_non_auto_fillable_category_count", lambda *a, **k: 0)
    return _preview.preview_apply_rules_to_pending(SimpleNamespace(), tenant_id="owner"), observed


def test_bulk_rule_converts_to_recorded_threshold_units(monkeypatch):
    result, observed = _preview_with(monkeypatch, projected=2000)
    assert result["items"][0]["suggested_category"] == "餐饮"
    assert observed[0]["source_currency"] == "CNY"
    assert observed[0]["home_currency"] == "JPY"
    assert observed[0]["rate_date"].isoformat() == "2026-09-03"


def test_missing_conversion_stops_lower_priority_and_is_visible(monkeypatch):
    result, _ = _preview_with(monkeypatch, projected=None)
    assert result["changed_count"] == 0 and result["items"] == []
    assert result["no_match_count"] == 0
    assert result["unavailable_count"] == 1
    assert result["missing_currency_codes"] == ["CNY"]


def test_preview_token_binds_actual_conversion_even_before_threshold_crossing(monkeypatch):
    first, _ = _preview_with(monkeypatch, projected=2000)
    second, _ = _preview_with(monkeypatch, projected=2100)
    assert first["items"] == second["items"]
    assert first["preview_token"] != second["preview_token"]


def test_automatic_classification_preserves_category_on_unknown_conversion(monkeypatch):
    expense, rules = _expense(), _rules()
    monkeypatch.setattr(rule_service, "enabled_merchant_alias_map", lambda *a, **k: {})
    monkeypatch.setattr("app.services.learning_service.read_ocr_text", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "project_recorded_amount", lambda *a, **k: None)
    db = SimpleNamespace(scalars=lambda *a, **k: rules)
    assert rule_service.classify_expense(db, expense).category == "其他"


def test_edit_cannot_relabel_recorded_threshold_and_clear_keeps_units(monkeypatch):
    from app.errors import AppError

    rule = _rules()[0]
    with pytest.raises(AppError) as error:
        rule_service.update_rule(SimpleNamespace(), rule, expected_row_version=1,
            amount_min_cents=1200, home_currency_code="CNY")
    assert error.value.error == "rule_currency_mismatch"
    writes = []
    monkeypatch.setattr(rule_service, "_authorize_rule_write", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "ensure_rule_category_available", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "claim_row_with_token", lambda *a, **k: writes.append(k["set_values"]) or 1)
    monkeypatch.setattr(rule_service, "_refresh_updated_rule", lambda *a, **k: rule)
    rule_service.update_rule(SimpleNamespace(), rule, expected_row_version=1, amount_min_cents=None,
        amount_max_cents=None, home_currency_code="JPY", commit=False)
    assert writes[0]["amount_min_cents"] is None and writes[0]["amount_max_cents"] is None
    assert "home_currency_code" not in writes[0] and rule.home_currency_code == "JPY"


def test_keyword_rule_can_gain_explicit_units_and_metadata_toggle_preserves_them(monkeypatch):
    rule = _rules()[1]
    writes = []
    monkeypatch.setattr(rule_service, "_authorize_rule_write", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "ensure_rule_category_available", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "claim_row_with_token", lambda *a, **k: writes.append(k["set_values"]) or 1)
    monkeypatch.setattr(rule_service, "_refresh_updated_rule", lambda *a, **k: rule)
    rule_service.update_rule(SimpleNamespace(), rule, expected_row_version=1, amount_min_cents=1200,
        home_currency_code="JPY", commit=False)
    assert writes[0]["amount_min_cents"] == 1200 and writes[0]["home_currency_code"] == "JPY"
    rule.home_currency_code, rule.amount_min_cents = "JPY", 1200
    rule_service.update_rule(SimpleNamespace(), rule, expected_row_version=2, enabled=False, commit=False)
    assert "home_currency_code" not in writes[1] and "amount_min_cents" not in writes[1]


def test_core_create_has_no_runtime_currency_fallback(monkeypatch):
    from app.errors import AppError

    with pytest.raises(AppError) as error:
        rule_service.create_rule(SimpleNamespace(), "owner", "store", "购物", True, 1, amount_min_cents=1200)
    assert error.value.error == "rule_currency_required"
    monkeypatch.setattr(rule_service, "_authorize_rule_write", lambda *a, **k: None)
    monkeypatch.setattr(rule_service, "ensure_rule_category_available", lambda *a, **k: None)
    db = SimpleNamespace(add=lambda row: None, flush=lambda: None, refresh=lambda row: None)
    result = rule_service.create_rule(db, "owner", "store", "购物", True, 1,
        amount_min_cents=1200, home_currency_code="JPY", commit=False)
    assert result.amount_min_cents == 1200 and result.home_currency_code == "JPY"


def test_missing_date_cannot_select_a_runtime_fx_quote(monkeypatch):
    from app.services import money_projection_service

    monkeypatch.setattr(money_projection_service, "resolve_payload_rate",
        lambda *a, **k: pytest.fail("an undated expense cannot choose today's quote"))
    assert money_projection_service.project_recorded_amount(SimpleNamespace(), tenant_id="owner", amount_minor=1200,
        source_currency="CNY", home_currency="JPY", rate_date=None) is None
    assert money_projection_service.project_recorded_amount(SimpleNamespace(), tenant_id="owner", amount_minor=1200,
        source_currency="JPY", home_currency="JPY", rate_date=None) == 1200


def test_apply_rechecks_conversion_token_and_never_applies_unknown_fallback(monkeypatch):
    from app.errors import AppError
    from app.services.rule_application_service import _apply

    original, _ = _preview_with(monkeypatch, projected=None)
    for name in ("_rule_application_candidates", "_enabled_rules", "enabled_merchant_alias_map", "_ocr_text_by_expense_id"):
        monkeypatch.setattr(_apply, name, getattr(_preview, name))
    monkeypatch.setattr(_apply, "authorize_currency_metadata_write", lambda *a, **k: None)
    monkeypatch.setattr(_apply, "_try_apply_rule_category", lambda *a, **k: pytest.fail("unknown FX must not mutate category"))
    db = SimpleNamespace()
    result = _apply.apply_rules_to_pending(db, tenant_id="owner", preview_token=original["preview_token"])
    assert result == (1, 0, False)
    monkeypatch.setattr(rule_service, "project_recorded_amount", lambda *a, **k: 2000)
    with pytest.raises(AppError) as error:
        _apply.apply_rules_to_pending(db, tenant_id="owner", preview_token=original["preview_token"])
    assert error.value.error == "preview_stale"


def test_apply_retains_preview_occ_when_prior_correction_refreshes_other_rows(monkeypatch):
    from app.services.rule_application_service import _apply

    _preview_with(monkeypatch, projected=6000)
    first, second = _expense(), _expense()
    second.id, second.row_version = 2, 7
    monkeypatch.setattr(_preview, "_rule_application_candidates", lambda *a, **k: ([first, second], False))
    preview = _preview.preview_apply_rules_to_pending(SimpleNamespace(), tenant_id="owner")
    for name in ("_rule_application_candidates", "_enabled_rules", "enabled_merchant_alias_map", "_ocr_text_by_expense_id"):
        monkeypatch.setattr(_apply, name, getattr(_preview, name))
    monkeypatch.setattr(_apply, "authorize_currency_metadata_write", lambda *a, **k: None)
    observed = []
    def apply_one(_db, **kwargs):
        observed.append(kwargs["expected_row_version"])
        second.row_version = 8  # mirrors expire_all observing a peer's correction
        return None
    monkeypatch.setattr(_apply, "_try_apply_rule_category", apply_one)
    _apply.apply_rules_to_pending(SimpleNamespace(), tenant_id="owner", preview_token=preview["preview_token"])
    assert observed == [1, 7]
