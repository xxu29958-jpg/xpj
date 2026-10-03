from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app.database import get_db
from app.errors import AppError
from app.middleware import csrf
from app.routes import web_settings
from app.services.admin_service._dtos import DeviceSummary
from app.services.owner_device_service import MyDevice
from app.tenants import SessionPrincipal


def test_account_menu_exposes_settings_to_viewers_and_writers():
    templates = Environment(loader=FileSystemLoader(Path(__file__).parents[2] / "app/templates/web"))
    for role in ("owner", "member", "viewer"):
        html = templates.get_template("_ledger_switcher.html").render(
            request=SimpleNamespace(state=SimpleNamespace(web_session_auth=object(), web_session_platform="")),
            selected_ledger_name="家庭账本", selected_ledger_id="family", selected_ledger_role=role,
            ledger_options=[], csrf_token="test-csrf", q="?ledger_id=family",
        )
        assert 'href="/web/settings"' in html
        assert "设置与设备" in html


@pytest.fixture
def settings_client(monkeypatch):
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"settings-unit-test-secret")
    app = FastAPI()
    app.include_router(web_settings.router)
    account = SimpleNamespace(public_id="account", display_name="自己", disabled_at=None)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(rollback=lambda: None, get=lambda *args, **kwargs: account)
    principal = SessionPrincipal(1, "account", "自己", 2, "current-browser", "浏览器", "app", 3, "test-hash")
    device = MyDevice(DeviceSummary("current-browser", "浏览器", "web", "自己", None, None, None, None, None), True)
    monkeypatch.setattr(web_settings.owner_device_service, "list_my_devices", lambda *args: [device])

    @app.middleware("http")
    async def bind_test_principal(request, call_next):
        request.state.web_session_principal = principal
        request.state.csrf_token = "test-csrf"
        return await call_next(request)

    client = TestClient(app)
    yield client
    client.close()


def test_settings_renders_own_devices_without_a_ledger(settings_client):
    page = settings_client.get("/web/settings")
    assert page.status_code == 200
    assert 'data-device-id="current-browser"' in page.text
    assert "当前设备" in page.text and "账户已连接" in page.text
    assert "生成新设备连接码" not in page.text
    assert "/current-browser/revoke" not in page.text


def test_service_refusal_keeps_rename_input_on_the_real_page(settings_client, monkeypatch):
    def refuse(*args, **kwargs):
        raise AppError("invalid_request", "这次没有保存，请修改后重试。", status_code=422)

    monkeypatch.setattr(web_settings.owner_device_service, "rename_my_device", refuse)
    page = settings_client.post("/web/settings/devices/current-browser/rename", data={"device_name": "未保存的名称"})
    assert page.status_code == 422
    assert 'value="未保存的名称"' in page.text
    assert "这次没有保存" in page.text and "设备名称已保存" not in page.text
    assert 'class="settings-device-actions" open' in page.text
