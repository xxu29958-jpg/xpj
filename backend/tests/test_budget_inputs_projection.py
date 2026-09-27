"""The read-only input view and generation share complete projection admission."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.services.budget_advisor_service import _inputs_builder as builder
from app.services.budget_advisor_service import _runner
from app.services.budget_advisor_service._models import BudgetInputs
from app.services.budget_advisor_service._outbound_guard import to_outbound_dict
from app.services.money_projection_service import ProjectionGap, ProjectionReference
from app.services.monthly_report_service import CategoryRollup, MonthlyReport, compose_monthly_report


def seed_reads(monkeypatch, *, gap=None, references=()):
    report = MonthlyReport("2026-08", "JPY", 300, 1, [CategoryRollup("餐饮", 300, 1)])
    monkeypatch.setattr(builder, "compose_monthly_report", lambda *args, **kwargs: report)
    monkeypatch.setattr(builder, "compose_budget_explanation", lambda *args, **kwargs: SimpleNamespace(
        undated_expense_count=0, p50_cents=None if gap else 200, p75_cents=None if gap else 400, missing_rates=(gap,) if gap else (),
    ))
    plan = SimpleNamespace(source_type="private employer", pay_day=15)
    monkeypatch.setattr(builder, "income_forecast", lambda *args, **kwargs: SimpleNamespace(
        expected_amount_cents=2000, projected_entries=((plan, 2000),), reference_rates=references,
    ))
    monkeypatch.setattr(builder, "_active_recurring_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(builder, "recurring_monthly_total", lambda *args, **kwargs: 500)
    monkeypatch.setattr(builder, "total_outstanding_recurring_cents", lambda *args, **kwargs: 100, raising=False)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *args, **kwargs: None, raising=False)


def test_read_model_keeps_discretionary_known_when_only_history_has_gap(monkeypatch):
    gap = ProjectionGap("CNY", "JPY", date(2026, 7, 2))
    seed_reads(monkeypatch, gap=gap)
    result = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08",
        home_currency_code="JPY", savings_target_cents=20, reserved_buffer_cents=30)
    assert (result.month, result.home_currency_code) == ("2026-08", "JPY")
    assert result.breakdown.discretionary_cents == 1550
    assert result.missing_rates == (gap,)
    assert result.provider_inputs is None


def test_complete_projection_preserves_outbound_privacy_and_paid_reservation(monkeypatch):
    seed_reads(monkeypatch)
    result = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")
    assert result.arrangement_currency_code == "JPY"
    assert result.breakdown.fixed_expenses_cents == 100
    assert result.breakdown.discretionary_cents == 1600
    payload = to_outbound_dict(result.provider_inputs)
    assert payload["home_currency"] == "JPY"
    assert payload["recurring_total_monthly_cents"] == 500
    assert payload["income_plan"] == [{"source_type": "other", "amount_cents": 2000, "pay_day": 15}]
    assert "missing_rates" not in payload
    assert "private employer" not in repr(payload)


def test_reserve_trial_changes_the_advice_basis_and_exposes_the_shortfall(monkeypatch):
    seed_reads(monkeypatch)
    modest = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08",
        home_currency_code="JPY", savings_target_cents=20, reserved_buffer_cents=30)
    ambitious = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08",
        home_currency_code="JPY", savings_target_cents=1800, reserved_buffer_cents=30)

    assert modest.breakdown.discretionary_cents == 1550
    assert ambitious.breakdown.discretionary_cents == 0
    assert modest.inputs_fingerprint != ambitious.inputs_fingerprint
    for projection, savings, available, shortfall in ((modest, 20, 1550, 0), (ambitious, 1800, 0, 230)):
        payload = to_outbound_dict(projection.provider_inputs)
        assert payload["savings_target_cents"] == savings
        assert payload["reserved_buffer_cents"] == 30
        assert payload["outstanding_fixed_cents"] == 100
        assert payload["discretionary_cents"] == available
        assert payload["shortfall_cents"] == shortfall == projection.breakdown.shortfall_cents
        assert "private employer" not in repr(payload)


def test_budget_input_response_preserves_the_actual_reference_dates(monkeypatch):
    from app.schemas._budget_advisor import BudgetInputsResponse

    seed_reads(monkeypatch, references=(ProjectionReference("USD", "JPY", date(2026, 8, 28)),))
    projection = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")
    response = BudgetInputsResponse.model_validate(projection).model_dump(mode="json")
    assert response["reference_rates"] == [{"source_currency_code": "USD", "home_currency_code": "JPY",
        "rate_date": "2026-08-28"}]
    assert response["missing_rates"] == []
    assert "reference_rates" not in to_outbound_dict(projection.provider_inputs)


def test_saved_arrangement_is_used_across_reads_but_trial_does_not_replace_it(monkeypatch):
    seed_reads(monkeypatch)
    saved = SimpleNamespace(home_currency_code="JPY", savings_target_cents=500, reserved_buffer_cents=100)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    initial = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")
    assert initial.breakdown.discretionary_cents == 1000
    assert initial.saved_arrangement is saved and not initial.is_trial
    trial = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY",
        savings_target_cents=1800, reserved_buffer_cents=100)
    assert trial.breakdown.shortfall_cents == 300 and trial.is_trial
    assert trial.saved_arrangement is saved
    reopened = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")
    assert reopened.breakdown.discretionary_cents == 1000
    assert reopened.inputs_fingerprint == initial.inputs_fingerprint != trial.inputs_fingerprint


@pytest.mark.parametrize("implicit_home", [False, True])
def test_saved_original_currency_is_not_relabelled_or_zeroed_when_conversion_is_missing(monkeypatch, implicit_home):
    seed_reads(monkeypatch)
    saved = SimpleNamespace(home_currency_code="USD", savings_target_cents=500, reserved_buffer_cents=100)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(builder, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="Asia/Shanghai"))
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 9, 27, tzinfo=UTC))
    monkeypatch.setattr(builder, "require_runtime_home_currency_code", lambda db: "JPY")
    home_kwargs = {} if implicit_home else {"home_currency_code": "JPY"}

    def missing_projection(db, **kwargs):
        assert kwargs["source_currency"] == "USD" and kwargs["rate_date"] == date(2026, 8, 31)
        kwargs["missing_rates"].add(ProjectionGap("USD", "JPY", date(2026, 8, 31)))
        return None

    monkeypatch.setattr(builder, "project_recorded_amount", missing_projection)
    incomplete = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", **home_kwargs)
    assert incomplete.home_currency_code == "JPY"
    assert getattr(incomplete, "arrangement_currency_code", None) == "USD"
    assert incomplete.breakdown.savings_target_cents is incomplete.breakdown.reserved_buffer_cents is None
    assert incomplete.breakdown.discretionary_cents is incomplete.breakdown.shortfall_cents is None
    assert incomplete.provider_inputs is None and incomplete.inputs_fingerprint is None
    assert incomplete.saved_arrangement.home_currency_code == "USD"
    assert incomplete.saved_arrangement.savings_target_cents == 500
    monkeypatch.setattr(builder, "project_recorded_amount", lambda db, **kw: kw["amount_minor"] * 2)
    recovered = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", **home_kwargs)
    assert recovered.breakdown.savings_target_cents == 1000 and recovered.breakdown.discretionary_cents == 400
    assert recovered.saved_arrangement is saved and saved.savings_target_cents == 500
    if implicit_home:
        monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
            provider="empty", is_live=False, blocked_reason=lambda _: None))
        provider = Mock()
        provider.advise.return_value = None
        monkeypatch.setattr(_runner, "get_budget_advisor", lambda: provider)
        generated = _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1,
            actor_role="owner", month="2026-08", timezone_name="UTC")
        assert generated.home_currency_code == provider.advise.call_args.args[0].home_currency == "JPY"
        assert provider.advise.call_args.args[0].savings_target_cents == 1000
        assert saved.home_currency_code == "USD" and saved.savings_target_cents == 500


def test_generation_returns_the_same_trial_basis_that_reaches_the_provider(monkeypatch):
    seed_reads(monkeypatch)
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
        provider="empty", is_live=False, blocked_reason=lambda _: None))
    captured = []
    monkeypatch.setattr(_runner, "get_budget_advisor", lambda: SimpleNamespace(advise=lambda inputs: captured.append(inputs)))
    result = _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1, actor_role="owner",
        month="2026-08", timezone_name="UTC", home_currency_code="JPY", savings_target_cents=1800, reserved_buffer_cents=100)
    assert result.inputs.breakdown.shortfall_cents == 300
    assert result.inputs.provider_inputs is captured[0]
    assert to_outbound_dict(captured[0])["savings_target_cents"] == 1800
    assert to_outbound_dict(captured[0])["shortfall_cents"] == 300


@pytest.mark.parametrize("missing", [True, False])
def test_original_jpy_trial_projects_to_usd_without_replacing_saved_arrangement(monkeypatch, missing):
    seed_reads(monkeypatch)
    saved = SimpleNamespace(home_currency_code="JPY", savings_target_cents=500, reserved_buffer_cents=100)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(builder, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 9, 27, tzinfo=UTC))

    def project(db, **kwargs):
        assert kwargs["source_currency"] == "JPY" and kwargs["home_currency"] == "USD"
        if missing:
            kwargs["missing_rates"].add(ProjectionGap("JPY", "USD", date(2026, 8, 31)))
            return None
        return kwargs["amount_minor"] * 2

    monkeypatch.setattr(builder, "project_recorded_amount", project)
    result = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08",
        home_currency_code="USD", arrangement_currency_code="JPY", savings_target_cents=1200, reserved_buffer_cents=30)
    assert result.home_currency_code == "USD" and result.is_trial
    assert result.arrangement_currency_code == "JPY"
    assert result.saved_arrangement is saved and saved.savings_target_cents == 500
    assert result.breakdown.savings_target_cents == (None if missing else 2400)
    assert result.breakdown.reserved_buffer_cents == (None if missing else 60)
    if missing:
        assert result.provider_inputs is None and result.breakdown.discretionary_cents is None
    else:
        assert result.provider_inputs.home_currency == "USD" and result.breakdown.shortfall_cents == 860


def test_hidden_historical_rate_change_invalidates_advice_without_changing_month_totals(monkeypatch):
    from app.schemas._budget_advisor import BudgetInputsResponse

    seed_reads(monkeypatch)
    before = BudgetInputsResponse.model_validate(builder.read_budget_inputs(
        object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")).model_dump()
    repeated = BudgetInputsResponse.model_validate(builder.read_budget_inputs(
        object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")).model_dump()
    assert repeated == before
    monkeypatch.setattr(builder, "compose_budget_explanation", lambda *args, **kwargs: SimpleNamespace(
        undated_expense_count=0, p50_cents=250, p75_cents=500, missing_rates=()))
    after = BudgetInputsResponse.model_validate(builder.read_budget_inputs(
        object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")).model_dump()
    assert before.pop("inputs_fingerprint") != after.pop("inputs_fingerprint")
    assert before == after
    assert "provider_inputs" not in after


def test_generation_rechecks_gap_before_provider_quota_or_audit(monkeypatch):
    gap = ProjectionGap("CNY", "JPY", date(2026, 7, 2))
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
        provider="openai_compat", is_live=True, blocked_reason=lambda role: None,
    ))
    read = Mock(return_value=SimpleNamespace(home_currency_code="JPY", undated_expense_count=0, missing_rates=(gap,), provider_inputs=None))
    monkeypatch.setattr(_runner, "read_budget_inputs", read, raising=False)
    forbidden = Mock(side_effect=AssertionError("incomplete money must block first"))
    for name in ("get_budget_advisor", "_reserve_live_call", "compute_input_hash", "_complete_live_call"):
        monkeypatch.setattr(_runner, name, forbidden)
    with pytest.raises(AppError) as exc:
        _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1,
            actor_role="owner", month="2026-08", timezone_name="UTC")
    assert exc.value.error == "money_projection_unavailable"
    assert exc.value.status_code == 409
    assert read.call_args.kwargs["month"] == "2026-08"
    assert read.call_args.kwargs["tenant_id"] == "owner"
    forbidden.assert_not_called()


def test_unused_previous_comparison_does_not_block_advice(monkeypatch):
    from app.services import money_projection_service

    seed_reads(monkeypatch)
    monkeypatch.setattr(builder, "compose_monthly_report", compose_monthly_report)
    monkeypatch.setattr(money_projection_service, "resolve_payload_rate", lambda *args, **kwargs: (None, None, None, None))
    batches = iter([[], [SimpleNamespace(category="餐饮", amount_cents=10_000,
        home_currency_code="CNY", stream_date=date(2026, 7, 2))]])
    db = SimpleNamespace(execute=lambda query: () if [c.name for c in query.selected_columns] == ["category", "count"] else next(batches))
    result = builder.read_budget_inputs(db, tenant_id="owner", month="2026-08", home_currency_code="JPY")
    assert result.breakdown.spent_amount_cents == 0
    assert result.missing_rates == ()
    assert result.provider_inputs is not None


def test_generation_keeps_the_original_input_currency(monkeypatch):
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
        provider="empty", is_live=False, blocked_reason=lambda role: None,
    ))
    inputs = BudgetInputs(month="2026-08", home_currency="JPY")
    read = Mock(return_value=SimpleNamespace(home_currency_code="JPY", undated_expense_count=0, missing_rates=(), provider_inputs=inputs))
    monkeypatch.setattr(_runner, "read_budget_inputs", read)
    provider = Mock()
    provider.advise.return_value = None
    monkeypatch.setattr(_runner, "get_budget_advisor", lambda: provider)
    result = _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1, actor_role="owner",
        month="2026-08", timezone_name="UTC", home_currency_code="JPY")
    assert read.call_args.kwargs["home_currency_code"] == "JPY"
    assert result.home_currency_code == "JPY"
    provider.advise.assert_called_once_with(inputs)


def test_anonymous_category_group_checks_every_contributing_history(monkeypatch):
    report = MonthlyReport("2026-09", "JPY", 500, 2,
        [CategoryRollup("legacy-a", 200, 1), CategoryRollup("legacy-b", 300, 1)])
    gap = ProjectionGap("CNY", "JPY", date(2026, 8, 15))
    calls = []

    def explanation(*args, **kwargs):
        categories = kwargs.get("categories", {kwargs["category"]})
        calls.append(categories)
        return SimpleNamespace(undated_expense_count=0, p50_cents=None, p75_cents=None,
            missing_rates=(gap,) if "legacy-b" in categories else ())

    monkeypatch.setattr(builder, "compose_budget_explanation", explanation)
    gaps = set()
    rows, undated = builder._historical_baseline(object(), tenant_id="owner", month="2026-09",
        report=report, timezone_name="UTC", home="JPY", gaps=gaps)
    assert [(row.category, row.amount_cents, row.count) for row in builder._category_breakdown(report)] == [("其他", 500, 2)]
    assert calls == [{"legacy-a", "legacy-b"}]
    assert rows == [] and undated == 0
    assert gaps == {gap}


def test_undated_input_is_visible_without_provider_envelope_or_fake_fx_gap(monkeypatch):
    seed_reads(monkeypatch)
    report = MonthlyReport("2026-08", "JPY", None, 0, undated_expense_count=1)
    monkeypatch.setattr(builder, "compose_monthly_report", lambda *a, **kw: report)
    projection = builder.read_budget_inputs(object(), tenant_id="owner", month="2026-08", home_currency_code="JPY")
    assert projection.undated_expense_count == 1 and projection.missing_rates == ()
    assert projection.breakdown.discretionary_cents is None and projection.provider_inputs is None
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda: SimpleNamespace(
        provider="openai_compat", is_live=True, blocked_reason=lambda role: None))
    monkeypatch.setattr(_runner, "read_budget_inputs", lambda *a, **kw: projection)
    forbidden = Mock(side_effect=AssertionError("undated financial inputs cannot reach provider or quota"))
    monkeypatch.setattr(_runner, "get_budget_advisor", forbidden)
    monkeypatch.setattr(_runner, "_reserve_live_call", forbidden)
    with pytest.raises(AppError) as exc:
        _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1,
            actor_role="owner", month="2026-08", timezone_name="UTC")
    assert exc.value.error == "accounting_date_required" and exc.value.status_code == 409
    forbidden.assert_not_called()
