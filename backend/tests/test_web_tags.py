from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _manual(
    client: TestClient,
    *,
    headers: dict[str, str],
    amount_cents: int,
    merchant: str,
    tags: str,
) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-02T00:00:00Z",
            "tags": tags,
        },
    )
    assert response.status_code == 200, response.text


def test_web_confirmed_tag_filter_is_ledger_scoped(web_client: TestClient, *, identity) -> None:
    _manual(
        web_client,
        headers=identity.app_headers,
        amount_cents=2100,
        merchant="Owner Shared",
        tags="Shared",
    )
    _manual(
        web_client,
        headers=identity.app_headers,
        amount_cents=900,
        merchant="Owner Other",
        tags="Other",
    )
    _manual(
        web_client,
        headers=identity.gray_app_headers,
        amount_cents=3100,
        merchant="Gray Shared",
        tags="Shared",
    )

    owner_page = web_client.get(
        "/web/confirmed?ledger_id=owner&month=2026-05&tag=Shared"
    )
    assert owner_page.status_code == 200
    assert 'name="tag" value="Shared"' in owner_page.text
    assert "当前仅显示标签「Shared」" in owner_page.text
    assert "Owner Shared" in owner_page.text
    assert "Owner Other" not in owner_page.text
    assert "Gray Shared" not in owner_page.text

    gray_page = web_client.get(
        "/web/confirmed?ledger_id=tester_1&month=2026-05&tag=Shared"
    )
    assert gray_page.status_code == 200
    assert "Gray Shared" in gray_page.text
    assert "Owner Shared" not in gray_page.text


def test_web_export_csv_uses_tag_filter(web_client: TestClient, *, identity) -> None:
    _manual(
        web_client,
        headers=identity.app_headers,
        amount_cents=2100,
        merchant="Owner Shared",
        tags="Shared",
    )
    _manual(
        web_client,
        headers=identity.app_headers,
        amount_cents=900,
        merchant="Owner Other",
        tags="Other",
    )
    _manual(
        web_client,
        headers=identity.gray_app_headers,
        amount_cents=3100,
        merchant="Gray Shared",
        tags="Shared",
    )

    response = web_client.get(
        "/web/export.csv?ledger_id=owner&month=2026-05&tag=Shared"
    )
    assert response.status_code == 200
    assert "Owner Shared" in response.text
    assert "Owner Other" not in response.text
    assert "Gray Shared" not in response.text


# UI/UX 批 14: /web/stats 页删除。原 test_web_stats_uses_tag_filter 覆盖的「按标签
# 看统计」已由 test_web_confirmed_tag_filter_is_ledger_scoped(本文件,/web/confirmed
# ?tag=)+ test_web_app_tags.test_web_tags_local_returns_200(看账单链接 → /web/confirmed
# ?tag=)联合接管,不再单测已删除的统计页。
