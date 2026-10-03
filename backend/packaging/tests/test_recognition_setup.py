"""Use the real Owner form and local HTTP protocol without a financial database."""

from __future__ import annotations

import base64
import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.database import get_db
from app.middleware import csrf
from app.middleware.logging import SanitizedLoggingMiddleware
from app.routes.owner_console import _settings
from app.services import runtime_settings_service as runtime
from app.services.local_llm_vision import call_local_llm_vision, local_llm_slot


@pytest.fixture
def local_model():
    state = SimpleNamespace(requests=[], number=24, status=200)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state.requests.append((self.path, None))
            self.reply({"data": [{"id": "vision-one"}, {"id": "vision-two"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.path, body))
            self.reply({"choices": [{"message": {"content": json.dumps({"number": state.number})}}]})

        def reply(self, payload):
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = f"http://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


@pytest.fixture
def setup_page(tmp_path, monkeypatch):
    target = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(config, "RUNTIME_SETTINGS_PATH", target)
    monkeypatch.setattr(config, "_RUNTIME_SETTINGS_SERVICE_OWNED", False)
    monkeypatch.setattr(runtime, "_SETTINGS_PATH", target)
    monkeypatch.setattr(runtime, "_SERVICE_OWNED", False)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    config.reset_settings_cache()
    saved_form = runtime.RecognitionSettingsForm("empty", False, "empty", "0.65", "Asia/Shanghai",
                                                "http://127.0.0.1:1/v1", "saved-model", "60", "1", "5", "empty")
    runtime.update_recognition_settings(saved_form)
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"recognition-setup-test-secret")
    monkeypatch.setattr(_settings, "_base", lambda request, db: {"ui_theme": "paper", "asset_version": "test"})
    app = FastAPI()
    app.add_middleware(SanitizedLoggingMiddleware)
    app.include_router(_settings.router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client, target, asdict(saved_form)
    config.reset_settings_cache()


def test_reading_models_preserves_the_unsaved_form_and_effective_configuration(setup_page, local_model):
    client, target, form = setup_page
    before = target.read_bytes()
    result = client.post("/owner/settings/recognition", data={**form, "recognition_action": "models",
        "local_llm_base_url": local_model.url, "local_llm_model": "", "local_llm_timeout_seconds": "45"})
    assert target.read_bytes() == before
    assert config.get_settings().local_llm_model == "saved-model"
    assert result.status_code == 200 and "已读取 2 个模型" in result.text
    assert 'value="vision-two"' in result.text and 'value="45"' in result.text
    assert local_model.requests == [("/v1/models", None)]


def test_image_check_uses_draft_connection_and_only_a_fixed_test_image(setup_page, local_model):
    client, target, form = setup_page
    before = target.read_bytes()
    result = client.post("/owner/settings/recognition", data={**form, "recognition_action": "test",
        "local_llm_base_url": local_model.url, "local_llm_model": "vision-two"})
    assert result.status_code == 200 and "测试图片识别通过" in result.text
    assert target.read_bytes() == before
    path, body = local_model.requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "vision-two"
    content = body["messages"][0]["content"]
    assert "24" not in content[0]["text"]
    prefix, encoded = content[1]["image_url"]["url"].split(",", 1)
    assert prefix == "data:image/png;base64"
    with Image.open(BytesIO(base64.b64decode(encoded))) as sample:
        assert sample.size == (240, 120)


@pytest.mark.parametrize("status,number", [(200, 99), (503, 24)])
def test_failed_check_retains_draft_and_never_reports_success(setup_page, local_model, status, number, caplog):
    client, target, form = setup_page
    before = target.read_bytes()
    local_model.status, local_model.number = status, number
    result = client.post("/owner/settings/recognition", data={**form, "recognition_action": "test",
        "local_llm_base_url": local_model.url, "local_llm_model": "unverified-model"})
    assert result.status_code == 502
    assert "测试图片识别通过" not in result.text and 'value="unverified-model"' in result.text
    assert target.read_bytes() == before
    report = next(record for record in caplog.records if record.name == "ticketbox.http")
    assert result.headers["X-Request-Id"] in report.getMessage()
    assert report.exc_info and report.exc_info[1].error == "dependency_unavailable"
    if status == 503:
        assert report.exc_info[1].__cause__ is not None


def test_failed_save_keeps_draft_and_settings_with_reported_storage_cause(setup_page, monkeypatch, caplog):
    client, target, form = setup_page
    before = target.read_bytes()
    failure = OSError("synthetic storage unavailable")

    def fail_publication(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(runtime, "patch_runtime_settings", fail_publication)
    result = client.post("/owner/settings/recognition", data={**form, "local_llm_model": "unsaved-model"})
    assert result.status_code == 503
    assert 'value="unsaved-model"' in result.text and "操作未完成" in result.text
    assert "synthetic storage unavailable" not in result.text
    assert target.read_bytes() == before and config.get_settings().local_llm_model == "saved-model"
    report = next(record for record in caplog.records if record.name == "ticketbox.http")
    assert result.headers["X-Request-Id"] in report.getMessage()
    assert report.exc_info and report.exc_info[1] is failure


def test_nonlocal_address_is_rejected_before_any_connection(setup_page, local_model):
    client, target, form = setup_page
    before = target.read_bytes()
    result = client.post("/owner/settings/recognition", data={**form, "recognition_action": "models",
        "local_llm_base_url": "https://model.example/v1"})
    assert result.status_code == 422 and "本机" in result.text
    assert not local_model.requests and target.read_bytes() == before


def test_setup_check_respects_the_running_model_capacity(setup_page, local_model):
    client, target, form = setup_page
    before = target.read_bytes()
    with local_llm_slot(max_concurrent=1, queue_timeout_seconds=0):
        result = client.post("/owner/settings/recognition", data={**form, "recognition_action": "test",
            "local_llm_base_url": local_model.url, "local_llm_max_concurrent": "8"})
    assert result.status_code == 429 and "繁忙" in result.text
    assert not local_model.requests and target.read_bytes() == before


def test_explicit_save_publishes_the_checked_connection_to_real_vision_calls(setup_page, local_model):
    client, _, form = setup_page
    draft = {**form, "local_llm_base_url": local_model.url, "local_llm_model": "vision-two"}
    tested = client.post("/owner/settings/recognition", data={**draft, "recognition_action": "test"})
    assert "测试图片识别通过" in tested.text
    assert config.get_settings().local_llm_model == "saved-model"
    saved = client.post("/owner/settings/recognition", data={**draft, "recognition_action": "save"})
    assert "识别设置已保存" in saved.text
    config.reset_settings_cache()
    assert config.get_settings().local_llm_base_url == local_model.url
    call_local_llm_vision(b"test-only-image", "image/png", "test caller")
    assert local_model.requests[-1][1]["model"] == "vision-two"
