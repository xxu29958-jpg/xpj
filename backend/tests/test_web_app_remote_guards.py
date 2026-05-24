"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app


def test_web_pending_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/pending")
    assert resp.status_code == 403


def test_web_dashboard_data_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/dashboard/data")
    assert resp.status_code == 403


def test_web_root_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web")
    assert resp.status_code == 403


def test_web_confirm_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/confirm").status_code == 403


def test_web_reject_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/reject").status_code == 403


def test_web_pending_batch_reject_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/pending/batch-reject").status_code == 403


def test_web_confirmed_batch_update_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/confirmed/batch-update").status_code == 403


def test_web_search_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/search").status_code == 403


def test_web_image_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/expenses/1/image").status_code == 403


def test_web_thumbnail_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/expenses/1/thumbnail").status_code == 403


def test_web_save_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/save", data={"amount_yuan": "1.00"}).status_code == 403


def test_web_local_post_rejects_cross_site_origin(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53001),
    ) as local_client:
        resp = local_client.post(
            "/web/confirmed/batch-update",
            headers={"Origin": "https://evil.example"},
            data={"action": "set_category", "ledger_id": "owner"},
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"


def test_web_local_post_accepts_same_origin_source(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53002),
    ) as local_client:
        form = local_client.get("/web/confirmed")
        assert form.status_code == 200
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', form.text)
        assert match is not None, form.text
        resp = local_client.post(
            "/web/confirmed/batch-update",
            headers={"Origin": "http://127.0.0.1:8000"},
            data={
                "action": "set_category",
                "ledger_id": "owner",
                "csrf_token": match.group(1),
            },
            follow_redirects=False,
        )
    assert resp.status_code in {303, 307}


def test_owner_local_post_rejects_cross_site_fetch_metadata(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53003),
    ) as local_client:
        resp = local_client.post(
            "/owner/backups",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"
