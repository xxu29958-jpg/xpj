"""Budget inputs stay unknown until missing conversion can be repaired in the original month."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.services.currency_common import currency_input_metadata


def _budget_page(**changes):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"),
    ]))
    context = {"month": "2026-09", "selected_ledger_id": "owner", "can_write": True,
        "home_currency_code": "JPY", "home_currency_symbol": "¥", "currency_input": currency_input_metadata("JPY"),
        "income_yuan": "1200", "fixed_yuan": "0", "spent_yuan": None, "savings_yuan": "0", "reserved_yuan": "0",
        "discretionary_yuan": None, "savings_target_yuan": "0", "reserved_buffer_yuan": "0", "run_advise": False,
        "advisor_can_request": True, "provider_enabled": False, "advice": None, "missing_rates": [
            SimpleNamespace(source_currency_code="CNY", home_currency_code="JPY", rate_date=date(2026, 9, 5)),
        ]}
    context.update(changes)
    return env.get_template("budget_advise.html").render(**context)


def test_missing_fx_keeps_unknown_amounts_and_disables_paid_generation():
    html = _budget_page()
    assert "None" not in html
    assert "待补汇率" in html and "CNY" in html and "JPY" in html and "2026-09-05" in html
    assert 'name="run_advise"' not in html
    assert "上方结果照常可用" not in html
    assert 'name="home_currency_code" value="JPY"' in html


def test_unknown_historical_currency_is_reviewable_without_a_guessed_rate_pair():
    html = _budget_page(missing_rates=[
        SimpleNamespace(source_currency_code=None, home_currency_code="JPY", rate_date=None),
    ])
    assert "原币种或日期" in html
    assert 'value="None"' not in html and "None → JPY" not in html
    assert 'name="run_advise"' not in html


def _render_task(monkeypatch, *, home="JPY", savings="150", gaps=()):
    from starlette.requests import Request

    from app.routes import web_budget_advise as web
    from app.services.budget_advisor_service._inputs_builder import BudgetInputProjection
    from app.services.budget_baseline_service import compute_monthly_discretionary

    monkeypatch.setattr(web, "_list_ledger_options", lambda _: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **k: "original")
    monkeypatch.setattr(web, "preserve_original_ledger_form", lambda *a, **k: None)
    monkeypatch.setattr(web, "_base_ctx", lambda *a, **k: {})
    monkeypatch.setattr(web, "require_runtime_home_currency_code", lambda _: "CNY")
    monkeypatch.setattr(web, "_advisor_readiness_context", lambda *a, **k: {"provider_name": "live"})
    breakdown = compute_monthly_discretionary(monthly_income_cents=1000, fixed_expenses_cents=0,
        spent_amount_cents=0, savings_target_cents=0, reserved_buffer_cents=0)
    read = Mock(return_value=BudgetInputProjection("2026-08", home or "CNY", breakdown, gaps, None))
    outbound = Mock(return_value=(None, None, "live"))
    monkeypatch.setattr(web, "read_budget_inputs", read)
    monkeypatch.setattr(web, "_budget_advice_response", outbound)
    monkeypatch.setattr(web, "templates", SimpleNamespace(TemplateResponse=lambda **k: k))
    request = Request({"type": "http", "method": "POST", "path": "/web/budget-advise"})
    result = web._render_budget_advise(request, db=Mock(), ledger_id="original", month="2026-08",
        savings_target_yuan=savings, reserved_buffer_yuan="3", run_advise=True, allow_outbound=True,
        home_currency_code=home)
    return result["context"], read, outbound


def test_native_budget_preserves_original_month_and_home_through_generation(monkeypatch):
    context, read, outbound = _render_task(monkeypatch)
    assert read.call_args.kwargs["home_currency_code"] == "JPY"
    assert read.call_args.kwargs["savings_target_cents"] == 150
    assert read.call_args.kwargs["month"] == outbound.call_args.kwargs["month_label"] == "2026-08"
    assert outbound.call_args.kwargs["home_currency_code"] == context["home_currency_code"] == "JPY"


def test_missing_rate_stops_native_generation_before_provider(monkeypatch):
    _, _, outbound = _render_task(monkeypatch, gaps=(SimpleNamespace(source_currency_code="CNY"),))
    outbound.assert_not_called()


def test_legacy_raw_amount_without_currency_is_retained_and_never_relabelled(monkeypatch):
    context, read, outbound = _render_task(monkeypatch, home=None)
    assert context["savings_target_yuan"] == "150"
    assert context["currency_choice_required"] is True
    assert context["discretionary_yuan"] is None
    assert read.call_args.kwargs["savings_target_cents"] == 0
    outbound.assert_not_called()


def test_invalid_raw_reserve_does_not_show_complete_advice_or_drop_text(monkeypatch):
    context, _, outbound = _render_task(monkeypatch, savings="abc")
    assert context["savings_target_yuan"] == "abc" and context["form_error"]
    assert context["discretionary_yuan"] is None
    outbound.assert_not_called()
