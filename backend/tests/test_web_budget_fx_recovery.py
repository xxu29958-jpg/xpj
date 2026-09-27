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


def test_repair_link_carries_editor_currency_separately_from_display_currency():
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    html = _budget_page(home_currency_code="USD", currency_input=currency_input_metadata("USD"),
        arrangement_currency_input=currency_input_metadata("JPY"), savings_target_yuan="1200",
        expected_row_version="3", idempotency_key="original-save-key")
    link = unescape(html.split('href="/web/budget-advise/rates?', 1)[1].split('"', 1)[0])
    params = parse_qs(urlsplit("/web/budget-advise/rates?" + link).query)
    assert params["home_currency_code"] == ["USD"]
    assert params["arrangement_currency_code"] == ["JPY"]
    assert params["savings_target_yuan"] == ["1200"]


def test_rate_return_keeps_report_currency_and_original_editor_currency():
    from app.routes.web_budget_fx import _TASK_FIELDS, _task_return

    values = dict.fromkeys(_TASK_FIELDS, "")
    values.update(month="2026-08", home_currency_code="USD", arrangement_currency_code="JPY",
        savings_target_yuan="1200", reserved_buffer_yuan="30", arrangement_version="3", arrangement_key="draft-key")
    path, params, _ = _task_return(values)
    assert path == "/web/budget-advise"
    assert params["home_currency_code"] == "USD"
    assert params["arrangement_currency_code"] == "JPY"
    assert params["savings_target_yuan"] == "1200"
    assert params["arrangement_version"] == "3" and params["arrangement_key"] == "draft-key"


def _render_task(monkeypatch, *, home="JPY", savings="150", gaps=(), arrangement_currency=None,
    method="POST", read_owner=None, reserved="3"):
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
    read = Mock(side_effect=read_owner) if read_owner else Mock(return_value=BudgetInputProjection("2026-08", home or "CNY", breakdown, gaps, None))
    outbound = Mock(return_value=(None, None, "live", None))
    monkeypatch.setattr(web, "read_budget_inputs", read)
    monkeypatch.setattr(web, "_budget_advice_response", outbound)
    monkeypatch.setattr(web, "templates", SimpleNamespace(TemplateResponse=lambda **k: k))
    request = Request({"type": "http", "method": method, "path": "/web/budget-advise"})
    result = web._render_budget_advise(request, db=Mock(), ledger_id="original", month="2026-08",
        savings_target_yuan=savings, reserved_buffer_yuan=reserved, run_advise=method == "POST", allow_outbound=method == "POST",
        home_currency_code=home, arrangement_currency_code=arrangement_currency)
    return result["context"], read, outbound


def test_jpy_editor_returns_from_rate_repair_to_usd_projection_without_reparsing(monkeypatch):
    from datetime import UTC, datetime

    from app.routes.web_budget_fx import _TASK_FIELDS, _task_return
    from app.services.budget_advisor_service import _inputs_builder as builder
    from app.services.money_projection_service import ProjectionGap
    from tests.test_budget_inputs_projection import seed_reads

    seed_reads(monkeypatch)
    saved = SimpleNamespace(home_currency_code="JPY", savings_target_cents=500, reserved_buffer_cents=100, row_version=3)
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(builder, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 9, 27, tzinfo=UTC))
    values = dict.fromkeys(_TASK_FIELDS, "")
    values.update(month="2026-08", home_currency_code="USD", arrangement_currency_code="JPY",
        savings_target_yuan="1200", reserved_buffer_yuan="30")
    _, params, _ = _task_return(values)
    missing = True

    def project(db, **kwargs):
        assert kwargs["source_currency"] == "JPY" and kwargs["home_currency"] == "USD"
        if missing:
            kwargs["missing_rates"].add(ProjectionGap("JPY", "USD", date(2026, 8, 31)))
            return None
        return kwargs["amount_minor"] * 2

    monkeypatch.setattr(builder, "project_recorded_amount", project)
    for is_missing in (True, False):
        missing = is_missing
        context, read, _ = _render_task(monkeypatch, home=params["home_currency_code"],
            arrangement_currency=params["arrangement_currency_code"], savings=params["savings_target_yuan"],
            reserved=params["reserved_buffer_yuan"], method="GET", read_owner=builder.read_budget_inputs)
        assert read.call_args.kwargs["savings_target_cents"] == 1200
        assert context["home_currency_code"] == "USD"
        assert context["arrangement_currency_input"]["currency_code"] == "JPY"
        assert context["savings_target_yuan"] == "1200" and context["reserved_buffer_yuan"] == "30"
        assert context["savings_yuan"] == (None if missing else "24.00")
        assert saved.savings_target_cents == 500 and saved.home_currency_code == "JPY"


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
