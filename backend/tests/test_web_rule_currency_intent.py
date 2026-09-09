"""Real rule forms retain their original money context across default changes."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.errors import AppError
from app.routes import web_rules
from app.routes.web_rule_forms import rule_amount_label
from app.services.currency_common import currency_input_metadata


def _render(**context):
    context.setdefault("rule_currency_input", {})
    loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app" / "templates" / "web")])
    return Environment(loader=loader, autoescape=True).get_template("rules.html").render(
        can_write=True, currency_input=currency_input_metadata("CNY"),
        home_currency_symbol="¥", home_currency_code="CNY", selected_ledger_id="owner",
        rule_amount_label=rule_amount_label, new_rule_key=lambda: "visible-command-key",
        minor_amount_label=lambda value: str(value / 100), **context)


@pytest.mark.parametrize("currency", ["JPY", None])
def test_rule_list_uses_captured_currency_and_exposes_edit(currency):
    rule = SimpleNamespace(id=3, keyword="测试规则", category="购物", priority=10,
        enabled=True, row_version=1, amount_min_cents=5000, amount_max_cents=None,
        home_currency_code=currency, source_contains=None, tag_contains=None)
    html = _render(rules=[rule])
    assert "50.0" not in html
    assert 'href="/web/rules/3/edit' in html
    assert "JPY" in html if currency else "5000 最小单位 · 币种待确认" in html


def test_rule_create_form_retains_raw_values_currency_and_retry_key():
    html = _render(rules=[], rule_form_draft={"amount_min_yuan": " 01200.00 ",
        "home_currency_code": "JPY", "idempotency_key": "original-rule-key"},
        rule_currency_input=currency_input_metadata("JPY"))
    assert 'name="home_currency_code" value="JPY"' in html
    assert 'name="idempotency_key" value="original-rule-key"' in html
    assert 'type="text" name="amount_min_yuan"' in html
    assert 'value=" 01200.00 "' in html


def test_create_passes_captured_currency_to_command_without_reading_new_default(monkeypatch):
    db = Mock()
    monkeypatch.setattr(web_rules, "_list_ledger_options", lambda db: [])
    monkeypatch.setattr(web_rules, "_resolve_selected_ledger_id", lambda *a, **k: "owner")
    monkeypatch.setattr(web_rules, "_require_selected_ledger_write", lambda *a: None)
    command = Mock(return_value=SimpleNamespace(keyword="Shop", category="购物"))
    monkeypatch.setattr(web_rules, "create_rule_idempotently", command, raising=False)
    response = web_rules.web_rules_create(Mock(), keyword="Shop", category="购物",
        priority="10", amount_min_yuan="1200", amount_max_yuan="", source_contains="",
        tag_contains="", ledger_id="owner", home_currency_code="JPY",
        idempotency_key="same-original-key", review_new=False, _local=None, db=db)
    assert response.status_code == 303
    payload = command.call_args.kwargs["payload"]
    assert payload.home_currency_code == "JPY" and payload.amount_min_cents == 1200
    assert command.call_args.kwargs["idempotency_key"] == "same-original-key"


@pytest.mark.parametrize("rule_exists", [True, False])
def test_rule_edit_refusal_retains_raw_amount_original_currency_key_and_occ(monkeypatch, rule_exists):
    from app.routes import web_rule_edit as editor

    rule = SimpleNamespace(id=3, home_currency_code="JPY", row_version=9) if rule_exists else None
    monkeypatch.setattr(editor, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(editor, "_resolve_selected_ledger_id", lambda *a, **k: "owner")
    monkeypatch.setattr(editor, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(editor, "find_rule_for_tenant", lambda *a, **k: rule)
    command = Mock(side_effect=AppError("state_conflict" if rule else "rule_not_found", status_code=409 if rule else 404))
    monkeypatch.setattr(editor, "update_rule_idempotently", command)
    render = Mock(return_value="retained")
    monkeypatch.setattr(editor, "_render_editor", render)
    fields = {"keyword": "Shop", "category": "购物", "priority": "10", "amount_min_yuan": "1200",
        "amount_max_yuan": "", "source_contains": "", "tag_contains": "", "home_currency_code": "JPY",
        "expected_row_version": "2", "idempotency_key": "original-rule-key", "review_latest": False}
    assert editor.web_rule_save(Mock(), 3, ledger_id="owner", _local=None, db=Mock(), **fields) == "retained"
    values = render.call_args.kwargs["values"]
    for name in ("amount_min_yuan", "home_currency_code", "expected_row_version", "idempotency_key"):
        assert values[name] == fields[name]
    fields["review_latest"] = True
    editor.web_rule_save(Mock(), 3, ledger_id="owner", _local=None, db=Mock(), **fields)
    assert command.call_count == 1
    reviewed = render.call_args.kwargs["values"]
    if rule:
        assert reviewed["expected_row_version"] == "9"
        assert reviewed["idempotency_key"] != "original-rule-key"
    else:
        assert reviewed == values


@pytest.mark.parametrize("rule_exists", [True, False])
def test_rule_toggle_replays_requested_state_without_inverting_current_record(monkeypatch, rule_exists):
    monkeypatch.setattr(web_rules, "_list_ledger_options", lambda db: [])
    monkeypatch.setattr(web_rules, "_resolve_selected_ledger_id", lambda *a, **k: "owner")
    monkeypatch.setattr(web_rules, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web_rules, "_get_rule", lambda *a: SimpleNamespace(id=3, enabled=False) if rule_exists else None)
    command = Mock(return_value=SimpleNamespace(keyword="Shop", enabled=False))
    monkeypatch.setattr(web_rules, "update_rule_idempotently", command)
    response = web_rules.web_rules_toggle(Mock(), 3, ledger_id="owner", expected_row_version="1",
        enabled=False, idempotency_key="same-toggle", _local=None, db=Mock())
    assert response.status_code == 303
    assert command.call_args.kwargs["payload"].enabled is False
    assert command.call_args.kwargs["idempotency_key"] == "same-toggle"
