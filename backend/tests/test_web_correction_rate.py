"""Native FX recovery preserves the correction while invoking only the rate owner."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.routes import web_expense_correction_rate as web


def test_gap_context_uses_only_server_pair_and_date(monkeypatch):
    read = Mock(return_value=[])
    monkeypatch.setattr(web, "list_exchange_rates", read)
    details = {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-05-04"}
    context = web.correction_rate_context(object(), "original", details)
    assert {key: context[key] for key in details} == details
    assert context["expected_row_version"] == "0" and context["idempotency_key"]
    assert read.call_args.kwargs == {"tenant_id": "original", "currency_code": "USD",
        "home_currency_code": "JPY", "rate_date": date(2026, 5, 4)}


@pytest.mark.parametrize("details", [None, {}, {"currency_code": "USD", "home_currency_code": "JPY"},
    {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "not-a-date"},
    {"currency_code": "JPY", "home_currency_code": "JPY", "rate_date": "2026-05-04"}])
def test_unknown_gap_cannot_offer_a_guessed_manual_rate(monkeypatch, details):
    read = Mock()
    monkeypatch.setattr(web, "list_exchange_rates", read)
    assert web.correction_rate_context(object(), "original", details) is None
    read.assert_not_called()


def test_rate_conflict_preserves_original_rate_key_version_and_value(monkeypatch):
    from app.errors import AppError

    values = {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-05-04",
        "rate_to_cny": "150.00", "expected_row_version": "0", "idempotency_key": "original-rate"}
    before = dict(values)
    command = Mock(side_effect=AppError("state_conflict", status_code=409))
    monkeypatch.setattr(web, "set_exchange_rate_idempotently", command)
    monkeypatch.setattr(web, "resolve_web_actor_account_id", lambda *_: 7)
    result = web.submit_correction_rate(Mock(), object(), "original", values)
    assert result["error"] and result["conflict"] and result["status_code"] == 409
    assert values == before
    assert command.call_args.kwargs["idempotency_key"] == "original-rate"
    assert command.call_args.kwargs["payload"].expected_row_version == 0


def test_success_reports_original_receipt_without_running_correction(monkeypatch):
    values = {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-05-04",
        "rate_to_cny": "150", "expected_row_version": "0", "idempotency_key": "original-rate"}
    command = Mock(return_value=SimpleNamespace(currency_code="USD", home_currency_code="JPY",
        rate_date=date(2026, 5, 4), rate_to_cny="150", row_version=1))
    monkeypatch.setattr(web, "set_exchange_rate_idempotently", command)
    monkeypatch.setattr(web, "resolve_web_actor_account_id", lambda *_: 7)
    result = web.submit_correction_rate(Mock(), object(), "original", values)
    assert result["status_code"] == 200 and result["saved"]
    assert "尚未保存" in result["message"]
    assert values["idempotency_key"] == "original-rate" and values["expected_row_version"] == "0"


def test_original_ledger_recovery_preserves_repeated_child_fields_and_scalar_text():
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"),
    ]))
    html = env.get_template("original_ledger_form.html").render(
        original_fields={"ledger_id": "original", "item_name": ["first", "second & last"],
            "idempotency_key": "same-key", "expected_row_version": "7"},
        original_ledger_id="original", original_task="更正", csrf_field="",
        request=SimpleNamespace(url=SimpleNamespace(path="/web/expenses/1/correction-rate"),
            state=SimpleNamespace(web_session_platform="desktop")))
    assert html.count('name="item_name"') == 2
    assert 'name="item_name" value="first"' in html
    assert 'name="item_name" value="second &amp; last"' in html
    assert 'name="idempotency_key" value="same-key"' in html
    assert 'name="expected_row_version" value="7"' in html


def test_rate_review_displays_the_current_value_before_authorizing_a_replacement(monkeypatch):
    values = {"currency_code": "USD", "home_currency_code": "JPY", "rate_date": "2026-05-04",
        "rate_to_cny": "150", "expected_row_version": "0", "idempotency_key": "original-rate"}
    monkeypatch.setattr(web, "list_exchange_rates", Mock(return_value=[SimpleNamespace(rate_to_cny="140", row_version=4)]))
    command = Mock()
    monkeypatch.setattr(web, "set_exchange_rate_idempotently", command)
    result = web.submit_correction_rate(Mock(), object(), "original", values, review_latest=True)
    assert "140" in result["message"] and "USD" in result["message"] and "JPY" in result["message"]
    assert values["rate_to_cny"] == "150" and values["expected_row_version"] == "4"
    assert values["idempotency_key"] != "original-rate"
    command.assert_not_called()


@pytest.mark.parametrize("member_id", [17, "unknown-member"])
def test_original_split_member_missing_from_current_options_keeps_its_selected_identity(member_id):
    env = Environment(autoescape=True, loader=FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"))
    html = env.get_template("_expense_splits_table.html").render(
        split_rows={"rows": [{"public_id": "original-split", "member_id": member_id,
            "amount_yuan": "0.20", "note": "original", "errors": {}, "disabled": False}]},
        split_members=[{"member_id": 7, "account_name": "Current member"}],
        can_write=True, correction_mode=True, currency_input={})
    assert f'value="{member_id}" selected' in html
    assert 'name="split_public_id" value="original-split"' in html


def test_rate_rerender_cannot_replace_missing_original_identity_with_current_fact(monkeypatch):
    from app.routes import _web_correction_page as page

    context = {"expense": {"row_version": 9, "merchant": "old submitted value",
        "is_split_received": False, "original_currency_code": "USD"},
        "confirm_idempotency_key": "new-generated-key", "edit_return_fields": {}, "conflict_current": None}
    monkeypatch.setattr(page, "web_edit_context", Mock(return_value=context))
    monkeypatch.setattr(page, "require_runtime_home_currency_code", lambda _: "JPY")
    result = page.web_correction_context(Mock(), object(), [], "original", 1,
        form_values={"expected_row_version": "", "idempotency_key": ""})
    assert result["expense"]["row_version"] == ""
    assert result["confirm_idempotency_key"] == ""


@pytest.mark.parametrize("key", ["", "  "])
def test_missing_original_key_cannot_admit_a_new_correction(monkeypatch, key):
    from app.routes import web_expense_correction as correction

    writer = Mock()
    monkeypatch.setattr(correction, "claim_web_correction", writer)
    monkeypatch.setattr(correction, "web_correction_idempotency_body", lambda _: {})
    _, claimed = correction._claim_correction_submission(Mock(), object(), selected_id="original", expense_id=1,
        form=SimpleNamespace(idempotency_key=key, expected_row_version="9"))
    assert claimed is None
    writer.assert_not_called()
