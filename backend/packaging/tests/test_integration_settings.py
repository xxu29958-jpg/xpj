from __future__ import annotations

import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app import config
from app.errors import AppError
from app.services import integration_settings_service as integration
from app.services import runtime_settings_service as runtime
from app.services import runtime_settings_store as store
from app.services.budget_advisor_service import _runner
from app.services.budget_advisor_service._models import BudgetAdvice, BudgetInputs
from app.services.budget_advisor_service._providers import OpenAiCompatBudgetAdvisor
from app.services.runtime_integration_settings import AdvisorSettingsProjection, FxSettingsProjection
from app.services.runtime_settings_store import RuntimeSettingsProjection, write_runtime_settings


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", target)
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    monkeypatch.setattr(runtime, "_SETTINGS_PATH", target)
    monkeypatch.setattr(runtime, "_SERVICE_OWNED", False)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "empty")
    monkeypatch.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "false")
    config.reset_settings_cache()
    yield target
    config.reset_settings_cache()


def test_saved_advisor_and_fx_are_used_after_process_settings_reload(settings_file):
    write_runtime_settings(settings_file, RuntimeSettingsProjection(
        public_base_url="https://receipts.example", budget_advisor_owner_confirmed=False,
        advisor=AdvisorSettingsProjection("openai_compat", "http://127.0.0.1:1234/v1", "", "home-model", 25, 15, 30),
        fx=FxSettingsProjection(False, "ecb", "08:20,20:20", "UTC"),
    ), service_owned=False)
    config.reset_settings_cache()
    saved = config.get_settings()
    assert (saved.budget_advisor_provider, saved.budget_advisor_model) == ("openai_compat", "home-model")
    assert (saved.budget_advisor_timeout_seconds, saved.budget_advisor_live_daily_call_limit) == (25, 30)
    assert (saved.fx_rate_auto_sync_enabled, saved.fx_rate_source, saved.fx_rate_sync_times) == (False, "ecb", "08:20,20:20")


def _local_form(**changes):
    return replace(integration.AdvisorSettingsForm(provider="openai_compat", base_url="http://127.0.0.1:1234/v1",
                                                   model="home-model"), **changes)


def test_save_confirm_change_and_clear_secret_keep_other_settings(settings_file):
    runtime.update_public_base_url("https://receipts.example")
    integration.save_advisor(_local_form(), api_key="test-private-key", key_action="replace")
    revision = integration.advisor_connection_revision()
    assert config.get_settings().budget_advisor_owner_confirmed is False
    integration.confirm_advisor(confirmed=True, revision=revision)
    integration.save_advisor(_local_form(daily_call_limit="8"), api_key="", key_action="keep")
    assert config.get_settings().budget_advisor_owner_confirmed is True
    assert config.get_settings().budget_advisor_api_key == "test-private-key"
    integration.save_fx(integration.FxSettingsForm(False, "ecb", "20:15,08:15", "UTC"))
    integration.save_advisor(_local_form(model="other-model"), api_key="", key_action="clear")
    assert config.get_settings().budget_advisor_api_key == ""
    assert config.get_settings().budget_advisor_owner_confirmed is False
    with pytest.raises(AppError, match="模型配置已改变"):
        integration.confirm_advisor(confirmed=True, revision=revision)
    assert config.get_settings().budget_advisor_owner_confirmed is False
    assert config.get_settings().public_base_url == "https://receipts.example"
    assert config.get_settings().fx_rate_sync_times == "08:15,20:15"


@pytest.mark.parametrize("changed", [
    {"provider": "empty", "base_url": "http://127.0.0.1:4321/v1"},
    {"base_url": "http://cloud.example/v1"}, {"base_url": "https://user:pass@cloud.example/v1"},
    {"model": ""}, {"model": "model\nsecret"}, {"timeout_seconds": "zero"}, {"daily_call_limit": "-1"},
])
def test_invalid_connection_keeps_saved_choices_and_permission(settings_file, changed):
    integration.save_advisor(_local_form(), api_key="test-private-key", key_action="replace")
    integration.confirm_advisor(confirmed=True, revision=integration.advisor_connection_revision())
    before = settings_file.read_bytes()
    with pytest.raises(AppError):
        integration.save_advisor(_local_form(**changed), api_key="", key_action="keep")
    assert settings_file.read_bytes() == before
    assert config.get_settings().budget_advisor_owner_confirmed is True


def test_failed_publication_keeps_effective_configuration(settings_file, monkeypatch):
    integration.save_advisor(_local_form(), api_key="", key_action="clear")
    before = settings_file.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("write denied")
    monkeypatch.setattr(store, "write_protected_file_replace", fail)
    with pytest.raises(AppError, match="设置未保存"):
        integration.save_advisor(_local_form(model="replacement"), api_key="", key_action="keep")
    assert settings_file.read_bytes() == before
    assert config.get_settings().budget_advisor_model == "home-model"


def test_old_recognition_projection_can_gain_integration_settings_without_losing_values(settings_file):
    write_runtime_settings(settings_file, RuntimeSettingsProjection("https://receipts.example", True), service_owned=False)
    old = json.loads(settings_file.read_bytes())
    old.pop("uploads")
    old.pop("maintenance")
    old.pop("advisor")
    old.pop("fx")
    old["schema"] = "ticketbox-runtime-settings-v2"
    settings_file.write_text(json.dumps(old, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="")
    config.reset_settings_cache()
    integration.save_fx(integration.FxSettingsForm())
    assert config.get_settings().public_base_url == "https://receipts.example"
    assert config.get_settings().budget_advisor_owner_confirmed is True


def test_connection_check_uses_saved_model_and_only_fixed_example(settings_file, caplog):
    requests = []
    reject = False
    test_key = "example-private-key-for-connection-test"
    class ModelHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            if reject:
                self.send_response(401, test_key)
                self.end_headers()
                self.wfile.write(test_key.encode())
                return
            body = json.dumps({"choices": [{"message": {"content": json.dumps({"summary": "示例建议", "suggestions": [], "confidence": 0.5})}}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        form = _local_form(base_url=f"http://127.0.0.1:{server.server_port}/v1")
        integration.save_advisor(form, api_key=test_key, key_action="replace")
        with pytest.raises(AppError, match="先允许"):
            integration.test_advisor_connection()
        assert requests == []
        integration.confirm_advisor(confirmed=True, revision=integration.advisor_connection_revision())
        assert "测试成功" in integration.test_advisor_connection()
        path, body = requests[0]
        assert path == "/v1/chat/completions" and body["model"] == "home-model"
        sent = json.loads(body["messages"][1]["content"])
        assert sent["month"] == "2026-01" and sent["home_currency"] == "CNY"
        assert sent["category_breakdown"] == [{"category": "餐饮", "amount_cents": 1000, "count": 1}]
        reject = True
        saved = settings_file.read_bytes()
        with pytest.raises(AppError, match="测试失败"):
            integration.test_advisor_connection()
        assert settings_file.read_bytes() == saved
        assert test_key not in caplog.text
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_configuration_changed_during_inputs_cannot_send_facts_to_the_new_unapproved_model(settings_file, monkeypatch):
    integration.save_advisor(_local_form(), api_key="", key_action="clear")
    integration.confirm_advisor(confirmed=True, revision=integration.advisor_connection_revision())
    def build_inputs(*args, **kwargs):
        integration.save_advisor(_local_form(base_url="http://127.0.0.1:5678/v1", model="different-model"), api_key="", key_action="clear")
        return SimpleNamespace(undated_expense_count=0, missing_rates=[], home_currency_code="CNY",
                               provider_inputs=BudgetInputs(month="2026-10", home_currency="CNY"))
    calls = []
    monkeypatch.setattr(_runner, "read_budget_inputs", build_inputs)
    monkeypatch.setattr(_runner, "compute_input_hash", lambda *_: "test-input-hash")
    monkeypatch.setattr(_runner, "_reserve_live_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(_runner, "_complete_live_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(OpenAiCompatBudgetAdvisor, "advise", lambda self, inputs: calls.append((self._base_url, self._model)) or BudgetAdvice(summary="ok", confidence=0.5))
    _runner.run_budget_advisor(object(), tenant_id="owner", actor_account_id=1, actor_role="owner", month="2026-10", timezone_name="UTC")
    assert calls == [("http://127.0.0.1:1234/v1", "home-model")]
    assert config.get_settings().budget_advisor_owner_confirmed is False


def test_stale_confirmation_is_rejected_inside_the_atomic_write(settings_file, monkeypatch):
    integration.save_advisor(_local_form(), api_key="", key_action="clear")
    revision = integration.advisor_connection_revision()
    real_patch = runtime.patch_runtime_settings
    def interleaved_patch(*args, **kwargs):
        if kwargs["mutation"].check_advisor:
            snapshot = replace(store.read_runtime_settings(settings_file, service_owned=False).advisor, model="changed-between-check-and-write")
            real_patch(*args, **{**kwargs, "mutation": store.RuntimeSettingsMutation("advisor", snapshot)})
        return real_patch(*args, **kwargs)
    monkeypatch.setattr(runtime, "patch_runtime_settings", interleaved_patch)
    with pytest.raises(AppError, match="模型配置已改变"):
        integration.confirm_advisor(confirmed=True, revision=revision)
    config.reset_settings_cache()
    assert config.get_settings().budget_advisor_owner_confirmed is False
