"""Configuration readiness is observable without building inputs or calling AI."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.config import reset_settings_cache
from app.errors import AppError
from app.services.budget_advisor_service import _audit, _runner


@contextmanager
def _configured(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Iterator[None]:
    values = {
        "PROVIDER": "openai_compat", "BASE_URL": "https://advisor.example.invalid/v1",
        "MODEL": "test-model", "API_KEY": "synthetic-key", "OWNER_CONFIRMED": "true",
        **overrides,
    }
    for key, value in values.items():
        monkeypatch.setenv(f"BUDGET_ADVISOR_{key}", value)
    reset_settings_cache()
    try:
        yield
    finally:
        reset_settings_cache()


def _render_owner(status: object) -> str:
    owner_templates = Path(__file__).resolve().parents[1] / "app/templates/owner"
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(owner_templates),
    ]), autoescape=True)
    environment.filters["owner_datetime"] = lambda value: value or "无记录"
    return environment.get_template("ai_advisor.html").render(status=status, audit_rows=[])


@pytest.mark.parametrize(("field", "value"), [
    ("MODEL", ""), ("BASE_URL", ""), ("API_KEY", ""),
    ("BASE_URL", "https://advisor.example.invalid/v1?key=private-sentinel"),
    ("BASE_URL", "http://[private-sentinel"), ("PROVIDER", "private-sentinel"),
])
def test_invalid_configuration_never_looks_callable(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setattr(_audit, "latest_audit_row", lambda *args, **kwargs: None)
    with _configured(monkeypatch, **{field: value}):
        status = _audit.advisor_status_for_tenant(object(), tenant_id="test")
        html = _render_owner(status)
        assert "可调用外部 AI" not in html
        assert "配置不完整或无效" in html
        assert "private-sentinel" not in html
        assert status.configuration_valid is False
        assert status.can_request is False
        assert status.last_success is None


def test_valid_configuration_preserves_confirmation_and_role_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_audit, "latest_audit_row", lambda *args, **kwargs: None)
    with _configured(monkeypatch):
        owner = _audit.advisor_status_for_tenant(object(), tenant_id="test", actor_role="owner")
        member = _audit.advisor_status_for_tenant(object(), tenant_id="test", actor_role="member")
        assert owner.configuration_valid is True
        assert owner.can_request is True
        assert owner.last_success is None
        assert member.can_request is False
    with _configured(monkeypatch, OWNER_CONFIRMED="false"):
        unconfirmed = _audit.advisor_status_for_tenant(object(), tenant_id="test")
        assert unconfirmed.configuration_valid is True
        assert unconfirmed.needs_confirmation is True
        assert unconfirmed.can_request is False


def test_invalid_configuration_refuses_before_inputs_or_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = Mock(side_effect=AssertionError("Invalid configuration must not build financial inputs"))
    quota = Mock(side_effect=AssertionError("Invalid configuration must not reserve a call"))
    monkeypatch.setattr(_runner, "read_budget_inputs", inputs)
    monkeypatch.setattr(_runner, "_reserve_live_call", quota)
    with _configured(monkeypatch, MODEL=""):
        with pytest.raises(AppError) as error:
            _runner.run_budget_advisor(
                object(), tenant_id="test", actor_account_id=1, actor_role="owner",
                month="2026-09", timezone_name="UTC",
            )
        assert error.value.error == "ai_advisor_configuration_invalid"
        assert error.value.status_code == 503
    inputs.assert_not_called()
    quota.assert_not_called()
