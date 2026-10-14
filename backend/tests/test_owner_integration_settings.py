"""Real Owner routes: configure an existing capability, consent, test and recover."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app import config
from app.database import SessionLocal
from app.main import app
from app.models import ExchangeRate, Expense
from app.routes.owner_console import _require_local
from app.services import fx_rate_provider as provider
from app.services import integration_settings_service as integration
from app.services import operations_settings_service as operations
from app.services import runtime_settings_service as runtime
from app.services.budget_advisor_service._models import BudgetAdvice
from app.services.exchange_rate_service import resolve_payload_rate
from tests._runtime_protocol import negotiated_headers
from tests.test_exchange_rates import _demote_owner_ledger_to_viewer


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
            "api_key": "private-model-key", "daily_call_limit": "12"}
    saved = owner.post("/owner/ai-advisor/settings", data=form)
    assert saved.status_code == 200, saved.text
    assert "已保存" in saved.text and "private-model-key" not in saved.text
    assert config.get_settings().budget_advisor_model == "household-model"
    assert config.get_settings().budget_advisor_live_daily_call_limit == 12
    assert config.get_settings().budget_advisor_owner_confirmed is False
    revision = _revision(saved.text)
    captures = []
    monkeypatch.setattr(integration, "get_budget_advisor", lambda **_: SimpleNamespace(
        advise=lambda inputs: captures.append(inputs) or BudgetAdvice(summary="示例", confidence=0.5)))
    tested = owner.post("/owner/ai-advisor/confirmation", data={"confirmed": "on", "connection_revision": revision, "action": "test"})
    assert tested.status_code == 200 and "连接测试成功" in tested.text
    assert config.get_settings().budget_advisor_owner_confirmed is True
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
    off = owner.post("/owner/ai-advisor/settings", data={"provider": "empty", "base_url": "invalid draft"})
    assert off.status_code == 200
    assert config.get_settings().budget_advisor_provider == "empty"
    assert config.get_settings().budget_advisor_api_key == "private-model-key"


def test_reading_models_does_not_save_or_send_a_saved_key_to_a_new_destination(owner, integration_file, monkeypatch):
    form = {"provider": "openai_compat", "base_url": "https://model.example/v1", "api_key": "private-model-key"}
    calls = []
    stream = MagicMock()
    stream.__enter__.return_value = stream
    stream.read.return_value = b'{"data":[{"id":"household-model"}]}'
    monkeypatch.setattr(integration.request, "build_opener", lambda *handlers: SimpleNamespace(
        open=lambda req, **kwargs: calls.append((req.full_url, req.get_header("Authorization"))) or stream))
    response = owner.post("/owner/ai-advisor/settings", data={**form, "advisor_action": "models"}, headers={"Accept": "application/json"})
    assert response.json()["models"] == ["household-model"]
    assert calls == [("https://model.example/v1/models", "Bearer private-model-key")]
    assert "private-model-key" not in response.text and not integration_file.exists()
    assert owner.post("/owner/ai-advisor/settings", data={**form, "model": "household-model"}).status_code == 200
    before = integration_file.read_bytes()
    conflicting_key = owner.post("/owner/ai-advisor/settings", data={
        **form, "model": "household-model", "clear_key": "on"})
    assert conflicting_key.status_code == 422 and "清除原密钥" in conflicting_key.text
    assert integration_file.read_bytes() == before
    refused = owner.post("/owner/ai-advisor/settings", data={
        "provider": "openai_compat", "base_url": "https://different.example/v1", "advisor_action": "models"}, headers={"Accept": "application/json"})
    assert refused.status_code == 422 and "接口地址已改变" in refused.json()["error"]
    assert len(calls) == 1 and integration_file.read_bytes() == before


def test_recognition_test_then_save_keeps_the_old_setup_until_the_picture_passes(owner, integration_file, monkeypatch):
    from app.services import recognition_setup_service as setup

    monkeypatch.setattr(setup, "list_local_llm_models", lambda _: ("tested-vision-model",))
    monkeypatch.setattr(setup, "call_local_llm_vision", lambda *args, **kwargs: {"number": "wrong"})
    form = {"ocr_provider": "local_llm", "ocr_auto_run": "on", "local_llm_base_url": "http://127.0.0.1:1234/v1",
            "recognition_action": "test_save"}
    failed = owner.post("/owner/settings/recognition", data=form)
    assert failed.status_code == 502 and "没有正确读出测试图片" in failed.text
    assert 'value="http://127.0.0.1:1234/v1"' in failed.text
    assert not integration_file.exists() and config.get_settings().ocr_provider == "empty"
    monkeypatch.setattr(setup, "call_local_llm_vision", lambda *args, **kwargs: {"number": "24"})
    saved = owner.post("/owner/settings/recognition", data=form)
    assert saved.status_code == 200 and "图片识别通过" in saved.text
    assert config.get_settings().local_llm_model == "tested-vision-model"
    assert config.get_settings().ocr_auto_run is True


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


def test_saved_fx_source_supplies_desktop_and_api_without_creating_a_manual_override(owner, integration_file, identity, monkeypatch):
    import json
    from datetime import date
    from decimal import Decimal
    from unittest.mock import MagicMock

    from app.database import SessionLocal
    from app.services import fx_rate_provider as provider
    from app.services.exchange_rate_service import list_exchange_rates, resolve_payload_rate
    from app.services.money_projection_service import project_recorded_amount
    from tests._runtime_protocol import negotiated_headers

    requested_urls = []
    available = True
    def response(request, **_):
        requested_urls.append(request.full_url)
        if not available:
            raise provider.FxFetchError("private transport details")
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = json.dumps({"amount": 1, "base": "EUR", "date": "2026-05-29",
            "rates": {"USD": 1.2, "CNY": 8.4, "GBP": 0.8, "JPY": 180, "HKD": 9, "KRW": 1700}}).encode()
        return stream
    monkeypatch.setattr(provider, "urlopen", response)
    saved = owner.post("/owner/fx/settings", data={"source": "frankfurter", "url": "https://rates.example/v1/latest",
        "auto_enabled": "on", "sync_times": "09:10", "timezone": "UTC", "action": "refresh"})
    assert saved.status_code == 200 and "已取得参考汇率" in saved.text
    assert requested_urls == ["https://rates.example/v1/latest"]
    assert config.get_settings().fx_rate_frankfurter_url == requested_urls[0]
    params = {"currency_code": "USD", "home_currency_code": "CNY", "rate_date": "2026-05-31"}
    before = owner.get("/api/exchange-rates/reference", params=params, headers=identity.app_headers)
    assert before.status_code == 200 and before.json()["effective"] is None
    fetched = owner.post("/api/exchange-rates/reference", json=params, headers=negotiated_headers(owner, identity.app_headers))
    assert fetched.status_code == 200, fetched.text
    assert requested_urls[-1] == "https://rates.example/v1/2026-05-31?base=EUR&amount=1"
    assert fetched.json()["effective"]["rate_date"] == "2026-05-29"
    assert Decimal(fetched.json()["effective"]["rate_to_home"]) == Decimal("7")
    with SessionLocal() as db:
        assert list_exchange_rates(db, tenant_id="owner") == []
        assert project_recorded_amount(db, tenant_id="owner", amount_minor=1200, source_currency="USD",
            home_currency="CNY", rate_date=date(2026, 5, 31)) == 8400
    available = False
    failed = owner.post("/api/exchange-rates/reference", json=params, headers=negotiated_headers(owner, identity.app_headers))
    assert failed.status_code == 502 and "private transport details" not in failed.text
    with SessionLocal() as db:
        assert resolve_payload_rate(db, tenant_id="owner", currency_code="USD", home_currency_code="CNY",
            rate_date=date(2026, 5, 31))[0] == Decimal("7")
        assert list_exchange_rates(db, tenant_id="owner") == []


def test_fx_settings_upgrade_preserves_old_source_schedule_and_other_groups(integration_file):
    import json

    from app.services.runtime_integration_settings import FxSettingsProjection
    from app.services.runtime_settings_store import RuntimeSettingsProjection, _encode, read_runtime_settings
    from app.services.secure_file import write_protected_file_no_replace

    old = json.loads(_encode(RuntimeSettingsProjection(public_base_url="https://household.example",
        budget_advisor_owner_confirmed=False, fx=FxSettingsProjection(False, "ecb", "10:30", "UTC"))))
    old["schema"] = "ticketbox-runtime-settings-v3"
    old["fx"].pop("url")
    write_protected_file_no_replace(integration_file,
        json.dumps(old, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", service_owned=False)
    saved = read_runtime_settings(integration_file, service_owned=False)
    assert saved.fx.source == "ecb" and saved.fx.url is None
    integration.save_fx(integration.FxSettingsForm(False, "ecb", "10:30", "UTC"))
    upgraded = read_runtime_settings(integration_file, service_owned=False)
    assert upgraded.public_base_url == "https://household.example"
    assert upgraded.fx.auto_enabled is False and upgraded.fx.sync_times == "10:30"
    assert upgraded.fx.url.endswith("eurofxref-daily.xml")


def test_first_scheduled_fetch_claims_lease_after_currency_read(monkeypatch):
    from app.services import fx_rate_scheduler as scheduler

    calls = []
    monkeypatch.setattr(scheduler, "refresh_ecb_fx_rates", lambda db, **kw: calls.append(kw) or [])
    assert scheduler._run_scheduled_fx_sync() is True
    assert calls == [{"home_currency_code": "CNY"}]


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


def test_lower_upload_limit_keeps_existing_original_readable(owner, integration_file, monkeypatch, tmp_path):
    import hashlib
    from io import BytesIO
    from random import Random

    from PIL import Image

    from app.errors import AppError
    from app.services import file_service, original_read_service

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    config.reset_settings_cache()
    image = BytesIO()
    Image.frombytes("RGB", (768, 768), Random(1).randbytes(768 * 768 * 3)).save(image, format="PNG")
    data = image.getvalue()
    form = {"max_upload_size_mb": "5", "daily_budget_mb": "20", "upload_link_ttl_days": "30",
            "upload_link_default_per_remote_interval_seconds": "0"}
    assert owner.post("/owner/settings/uploads", data=form).status_code == 200
    saved = file_service.save_upload_bytes(data, tenant_id="owner", filename="receipt.png", content_type="image/png")
    assert saved.size_bytes > 1024 * 1024
    assert owner.post("/owner/settings/uploads", data={**form, "max_upload_size_mb": "1"}).status_code == 200
    with pytest.raises(AppError) as rejected:
        file_service.save_upload_bytes(data, tenant_id="owner", filename="new.png", content_type="image/png")
    assert rejected.value.status_code == 413
    with original_read_service.read_original_snapshot(
        relative_path=saved.relative_path, tenant_id="owner", expected_sha256=saved.image_hash,
    ) as snapshot:
        assert snapshot.size_bytes == saved.size_bytes
        assert hashlib.sha256(snapshot.path.read_bytes()).hexdigest() == saved.image_hash
        assert snapshot.verified is True


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
    adjusted = owner.post("/owner/settings/maintenance", data={**form, "learning_cleanup_daily_at": "06:45"})
    assert adjusted.status_code == 200 and config.get_settings().learning_cleanup_daily_at == "06:45"
    assert config.get_settings().learning_cleanup_auto_enabled is True
    shortened = owner.post("/owner/settings/maintenance", data={**form, "recycle_bin_retention_days": "1"})
    assert shortened.status_code == 422
    assert config.get_settings().recycle_bin_retention_days != 1
    stopped = owner.post("/owner/settings/maintenance", data={name: value for name, value in form.items() if not name.endswith("_enabled")})
    assert stopped.status_code == 200 and config.get_settings().learning_cleanup_auto_enabled is False


_WIDE_PAIRS = [
    {"base": "CNY", "quote": "TWD", "rate": "4", "date": "2026-05-29"},
    {"base": "CNY", "quote": "VND", "rate": "4000", "date": "2026-05-28"},
    {"base": "CNY", "quote": "KWD", "rate": "0.04", "date": "2026-05-29"},
]


def test_wide_default_reaches_consumers_with_real_pair_dates_and_manual_priority(
    owner, identity, integration_file, monkeypatch,
):
    calls = []
    def response(request, **_):
        calls.append(request.full_url)
        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = json.dumps(_WIDE_PAIRS).encode()
        return stream
    monkeypatch.setattr(provider, "urlopen", response)
    for key in ("FX_RATE_SOURCE", "FX_RATE_FRANKFURTER_URL"):
        monkeypatch.delenv(key, raising=False)
    config.reset_settings_cache()
    assert config.get_settings().fx_rate_source == "frankfurter_v2"
    saved = owner.post("/owner/fx/settings", data={"source": "frankfurter_v2", "action": "refresh",
        "auto_enabled": "on", "sync_times": "09:10", "timezone": "UTC"})
    assert saved.status_code == 200 and "已取得参考汇率" in saved.text
    assert calls == ["https://api.frankfurter.dev/v2/rates?base=CNY"]
    assert "Frankfurter 广覆盖（公开机构参考价）" in saved.text
    headers = negotiated_headers(owner, identity.app_headers)
    observed = owner.get("/api/exchange-rates/reference", params={"home_currency_code": "CNY"}, headers=headers)
    assert {r["currency_code"]: r["rate_date"] for r in observed.json()["items"]} == {
        "TWD": "2026-05-29", "VND": "2026-05-28", "KWD": "2026-05-29"}
    facts = []
    for code, amount, expected in (("TWD", 12050, 3013), ("VND", 120000, 3000), ("KWD", 1234, 3085)):
        params = {"home_currency_code": "CNY", "currency_code": code, "rate_date": "2026-05-31"}
        fetched = owner.post("/api/exchange-rates/reference", json=params, headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["effective"]["source"] == "frankfurter"
        assert parse_qs(urlsplit(calls[-1]).query) == {"base": ["CNY"], "date": ["2026-05-31"]}
        created = owner.post("/api/expenses/manual", headers=headers, json={"client_ref": str(uuid4()),
            "original_currency_code": code, "original_amount_minor": amount, "spent_at": "2026-05-31T12:00:00Z"})
        assert created.status_code == 200, created.text
        fact = created.json()
        assert (fact["amount_cents"], fact["fx_status"], fact["exchange_rate_source"]) == (expected, "ready", "frankfurter")
        assert fact["exchange_rate_date"] == ("2026-05-28" if code == "VND" else "2026-05-29")
        facts.append((fact["id"], expected, fact["exchange_rate_date"]))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExchangeRate)) == 0
    override = owner.put("/api/exchange-rates/TWD/2026-05-31", headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0, "home_currency_code": "CNY", "currency_code": "TWD",
            "rate_date": "2026-05-31", "rate_to_cny": "0.2"})
    assert override.status_code == 200, override.text
    owner.post("/owner/fx/settings", data={"source": "ecb", "sync_times": "10:00", "timezone": "UTC"})
    with SessionLocal() as db:
        assert resolve_payload_rate(db, tenant_id="owner", currency_code="TWD", home_currency_code="CNY",
            rate_date=date(2026, 5, 31))[:2] == (Decimal("0.2"), "manual")
        assert resolve_payload_rate(db, tenant_id="owner", currency_code="VND", home_currency_code="CNY",
            rate_date=date(2026, 5, 31))[1] == "frankfurter"
        for fact_id, amount, day in facts:
            fact = db.get(Expense, fact_id)
            assert (fact.amount_cents, str(fact.exchange_rate_date), fact.exchange_rate_source) == (amount, day, "frankfurter")


@pytest.mark.parametrize("change", [{"base": "USD"}, {"date": "2026-06-01"}, {"rate": "NaN"}, {"rate": "0"}])
def test_wide_response_rejects_wrong_base_future_or_nonpositive_quotes(change):
    with pytest.raises(ValueError):
        daily = provider.parse_frankfurter_v2_rates(json.dumps([{**_WIDE_PAIRS[0], **change}]), home_currency_code="CNY")
        provider._validate_dated_rates(daily, date(2026, 5, 31))


def test_reference_fetch_requires_writer_and_current_protocol_before_network(client, identity, monkeypatch):
    def forbidden(**_):
        pytest.fail("Rejected requests must not reach the reference provider")
    monkeypatch.setattr(provider, "fetch_reference_rates", forbidden)
    params = {"home_currency_code": "CNY", "currency_code": "TWD"}
    assert client.get("/api/exchange-rates/reference", params=params).status_code == 401
    assert client.post("/api/exchange-rates/reference", json=params).status_code == 401
    headers = negotiated_headers(client, identity.app_headers)
    stale = client.post("/api/exchange-rates/reference", json=params,
        headers={**headers, "Ticketbox-Api-Version": "stale"})
    assert stale.status_code == 409
    _demote_owner_ledger_to_viewer()
    assert client.get("/api/exchange-rates/reference", params=params, headers=headers).status_code == 200
    assert client.post("/api/exchange-rates/reference", json=params, headers=headers).status_code == 403
