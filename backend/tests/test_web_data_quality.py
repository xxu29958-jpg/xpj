"""/web/data-quality page (slice 2 / T20)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api_contract_helpers import upload_png
from app.main import app
from app.routes.web_app import _require_local as _web_require_local
from conftest import app_headers


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_web_data_quality_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/data-quality")
    assert resp.status_code == 403


def test_web_data_quality_empty_renders(web_client: TestClient) -> None:
    resp = web_client.get("/web/data-quality")
    assert resp.status_code == 200
    assert "数据体检" in resp.text
    # All 8 counter labels render.
    for label in (
        "待确认总数",
        "缺金额",
        "缺商家",
        "未分类",
        "疑似重复",
        "已确认无图",
        "可一键确认",
        "最久待确认",
    ):
        assert label in resp.text


def test_web_data_quality_action_links_appear(web_client: TestClient) -> None:
    # Seed a pending row with no amount + no merchant — triggers action items.
    upload_png(web_client)

    resp = web_client.get("/web/data-quality")
    assert resp.status_code == 200
    # Action list contains the missing_amount / missing_merchant action.
    assert "filter=missing_amount" in resp.text
    assert "filter=missing_merchant" in resp.text


def test_web_data_quality_local_uses_app_headers(client: TestClient) -> None:
    """A baseline check that the /api endpoint backing this page is reachable."""
    resp = client.get("/api/insights/data-quality", headers=app_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_total"] >= 0
