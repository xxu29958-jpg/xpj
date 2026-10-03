"""Real Owner routes: configure an existing capability, consent, test and recover."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app import config
from app.main import app
from app.routes.owner_console import _require_local
from app.services import integration_settings_service as integration
from app.services import operations_settings_service as operations
from app.services import runtime_settings_service as runtime
from app.services.budget_advisor_service._models import BudgetAdvice


@pytest.fixture
def integration_file(tmp_path, monkeypatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(runtime, "_SETTINGS_PATH", target)
    monkeypatch.setattr(runtime, "_SERVICE_OWNED", False)
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", target)
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    config.reset_settings_cache()
    yield target
    config.reset_settings_cache()


@pytest.fixture
def owner(client):
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _revision(html):
    match = re.search(r'name="connection_revision" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_owner_configures_model_without_env_and_never_receives_saved_secret(owner, integration_file, monkeypatch):
    page = owner.get("/owner/ai-advisor")
    assert page.status_code == 200
    assert 'action="/owner/ai-advisor/settings?ledger_id=owner"' in page.text
    form = {"provider": "openai_compat", "base_url": "https://model.example/v1", "model": "household-model",
            "key_action": "replace", "api_key": "private-model-key", "daily_call_limit": "12"}
    saved = owner.post("/owner/ai-advisor/settings", data=form)
    assert saved.status_code == 200, saved.text
    assert "已保存" in saved.text and "private-model-key" not in saved.text
    assert config.get_settings().budget_advisor_model == "household-model"
    assert config.get_settings().budget_advisor_live_daily_call_limit == 12
    assert config.get_settings().budget_advisor_owner_confirmed is False
    revision = _revision(saved.text)
    allowed = owner.post("/owner/ai-advisor/confirmation", data={"confirmed": "on", "connection_revision": revision}, follow_redirects=False)
    assert allowed.status_code == 303
    captures = []
    monkeypatch.setattr(integration, "get_budget_advisor", lambda **_: SimpleNamespace(
        advise=lambda inputs: captures.append(inputs) or BudgetAdvice(summary="示例", confidence=0.5)))
    tested = owner.post("/owner/ai-advisor/test")
    assert tested.status_code == 200 and "连接测试成功" in tested.text
    assert captures[0].month == "2026-01" and captures[0].category_breakdown[0].amount_cents == 1000
    changed = owner.post("/owner/ai-advisor/settings", data={**form, "model": "new-model", "key_action": "keep", "api_key": ""})
    assert changed.status_code == 200
    assert config.get_settings().budget_advisor_api_key == "private-model-key"
    assert config.get_settings().budget_advisor_owner_confirmed is False
    stale = owner.post("/owner/ai-advisor/confirmation", data={"confirmed": "on", "connection_revision": revision})
    assert stale.status_code == 409 and "模型配置已改变" in stale.text
    assert config.get_settings().budget_advisor_owner_confirmed is False
    before = integration_file.read_bytes()
    invalid = owner.post("/owner/ai-advisor/settings", data={**form, "base_url": "https://model.example/v1?key=url-private-key"})
    assert invalid.status_code == 422
    assert "url-private-key" not in invalid.text and "private-model-key" not in invalid.text
    assert 'value="household-model"' in invalid.text
    assert integration_file.read_bytes() == before


def test_owner_changes_fx_schedule_and_corrects_validation_without_losing_choices(owner, integration_file):
    page = owner.get("/owner/fx")
    assert page.status_code == 200 and 'action="/owner/fx/settings"' in page.text
    result = owner.post("/owner/fx/settings", data={"source": "ecb", "sync_times": "21:30,08:30", "timezone": "UTC"})
    assert result.status_code == 200 and "汇率设置已保存" in result.text
    assert (config.get_settings().fx_rate_auto_sync_enabled, config.get_settings().fx_rate_sync_times) == (False, "08:30,21:30")
    before = integration_file.read_bytes()
    invalid = owner.post("/owner/fx/settings", data={"auto_enabled": "on", "source": "ecb", "sync_times": "25:00", "timezone": "UTC"})
    assert invalid.status_code == 422 and 'value="25:00"' in invalid.text
    assert integration_file.read_bytes() == before
    corrected = owner.post("/owner/fx/settings", data={"auto_enabled": "on", "source": "ecb", "sync_times": "10:00", "timezone": "UTC"})
    assert corrected.status_code == 200
    assert config.get_settings().fx_rate_auto_sync_enabled is True
    assert config.get_settings().fx_rate_sync_times == "10:00"


@pytest.mark.parametrize("path", ["/owner/ai-advisor/settings", "/owner/ai-advisor/test", "/owner/fx/settings",
                                  "/owner/settings/uploads", "/owner/settings/maintenance"])
def test_public_requests_cannot_configure_host_integrations(client, integration_file, path):
    response = client.post(path, headers={"Host": "api.example.com"})
    assert response.status_code == 403
    assert not integration_file.exists()


def test_owner_configures_upload_defaults_and_recovers_a_failed_form(owner, integration_file):
    page = owner.get("/owner/settings/uploads")
    assert page.status_code == 200 and 'action="/owner/settings/uploads"' in page.text
    form = {"max_upload_size_mb": "20", "upload_link_ttl_days": "30", "daily_budget_mb": "50",
            "upload_link_default_per_remote_interval_seconds": "3"}
    saved = owner.post("/owner/settings/uploads", data=form)
    assert saved.status_code == 200 and "上传设置已保存" in saved.text
    assert config.get_settings().upload_link_ttl_days == 30
    assert config.get_settings().upload_link_default_daily_byte_budget == 50 * 1024 * 1024
    before = integration_file.read_bytes()
    invalid = owner.post("/owner/settings/uploads", data={**form, "max_upload_size_mb": "-1"})
    assert invalid.status_code == 422 and 'value="30"' in invalid.text
    assert integration_file.read_bytes() == before
    corrected = owner.post("/owner/settings/uploads", data={**form, "max_upload_size_mb": "25"})
    assert corrected.status_code == 200 and config.get_settings().max_upload_size_mb == 25


def test_owner_sees_cleanup_impact_and_must_confirm_before_enabling(owner, integration_file):
    page = owner.get("/owner/settings/maintenance")
    assert page.status_code == 200 and "已有记录仍按创建时" in page.text
    form = {name: value for name, value in operations.maintenance_form().items() if not isinstance(value, bool)}
    form.update(learning_cleanup_auto_enabled="on", learning_cleanup_daily_at="05:30")
    denied = owner.post("/owner/settings/maintenance", data=form)
    assert denied.status_code == 422 and "确认清理影响" in denied.text
    assert config.get_settings().learning_cleanup_auto_enabled is False
    saved = owner.post("/owner/settings/maintenance", data={**form, "confirm_cleanup": "on"})
    assert saved.status_code == 200 and "维护设置已保存" in saved.text
    assert config.get_settings().learning_cleanup_auto_enabled is True
    before = integration_file.read_bytes()
    invalid = owner.post("/owner/settings/maintenance", data={**form, "confirm_cleanup": "on", "device_cleanup_timezone": "invalid/zone"})
    assert invalid.status_code == 422 and 'value="05:30"' in invalid.text
    assert integration_file.read_bytes() == before
    stopped = owner.post("/owner/settings/maintenance", data={name: value for name, value in form.items() if not name.endswith("_enabled")})
    assert stopped.status_code == 200 and config.get_settings().learning_cleanup_auto_enabled is False
