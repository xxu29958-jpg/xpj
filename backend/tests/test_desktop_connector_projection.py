"""Connector authority is readable only by the paired loopback Desktop bridge."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import desktop
from tests.desktop_activation_support import LOOPBACK_BASE_URL, _bridge_headers, _desktop_session


@pytest.fixture
def loopback_client(identity):
    del identity
    with TestClient(app, base_url=LOOPBACK_BASE_URL, client=("127.0.0.1", 51011)) as value:
        yield value


def test_connector_projection_uses_live_desktop_auth_and_reports_unsupported_host(client, identity, loopback_client):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    response = loopback_client.get("/desktop/public-connectivity", headers=_bridge_headers(token))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "schema": "ticketbox-connector-projection-v1", "supported": False,
        "binding": None, "public_origin_revision": 0, "state": None,
        "operation": None, "lifecycle_busy": False,
    }
    assert token not in response.text
    assert loopback_client.get("/desktop/public-connectivity").status_code == 401


@pytest.mark.parametrize("case,expected", [
    ("anonymous", 401), ("android", 401), ("missing_bridge", 401),
    ("public_host", 403), ("remote_peer", 403),
])
def test_connector_projection_rejects_wrong_consumer_before_reading_authority(
    client, identity, loopback_client, monkeypatch, case, expected,
):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    bridge = _bridge_headers(token)
    if case == "anonymous":
        bridge.pop("Authorization")
    elif case == "android":
        bridge.update(identity.app_headers)
    elif case == "missing_bridge":
        bridge = headers
    elif case == "public_host":
        bridge["Host"] = "public.example.com"
    monkeypatch.setattr(desktop, "connector_projection", lambda: pytest.fail("unauthorized authority read"))
    if case == "remote_peer":
        with TestClient(app, base_url=LOOPBACK_BASE_URL, client=("203.0.113.7", 51011)) as remote:
            response = remote.get("/desktop/public-connectivity", headers=bridge)
    else:
        response = loopback_client.get("/desktop/public-connectivity", headers=bridge)
    assert response.status_code == expected, response.text


def test_connector_projection_read_failure_has_one_safe_error(client, identity, loopback_client, monkeypatch, caplog):
    _, headers = _desktop_session(client, identity.pairing_code)
    token = headers["Authorization"].removeprefix("Bearer ")
    secret = "private-connector-record-must-not-reach-the-response"

    def fail():
        raise OSError(secret)

    monkeypatch.setattr(desktop, "connector_projection", fail)
    response = loopback_client.get("/desktop/public-connectivity", headers=_bridge_headers(token))
    assert response.status_code == 503
    assert response.json()["error"] == "connector_projection_unavailable"
    assert "刷新" in response.json()["message"]
    assert secret not in response.text + caplog.text and token not in response.text + caplog.text
