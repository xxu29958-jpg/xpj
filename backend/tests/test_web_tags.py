from __future__ import annotations

from html.parser import HTMLParser

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
    assert "标签：Shared" in owner_page.text
    assert "Owner Shared" in owner_page.text
    assert "Owner Other" not in owner_page.text
    assert "Gray Shared" not in owner_page.text
    assert 'aria-label="批量修改分类"' in owner_page.text
    assert 'aria-label="批量修改标签"' in owner_page.text

    gray_page = web_client.get(
        "/web/confirmed?ledger_id=tester_1&month=2026-05&tag=Shared"
    )
    assert gray_page.status_code == 200
    assert "Gray Shared" in gray_page.text
    assert "Owner Shared" not in gray_page.text


def test_web_confirmed_tag_filter_has_a_clear_return_to_the_same_month(
    web_client: TestClient,
    *,
    identity,
) -> None:
    _manual(
        web_client,
        headers=identity.app_headers,
        amount_cents=2100,
        merchant="Owner Shared",
        tags="Shared",
    )

    page = web_client.get(
        "/web/confirmed?ledger_id=owner&month=2026-05&tag=Shared"
    )

    assert page.status_code == 200
    assert "标签：Shared" in page.text
    assert "当前只显示带这个标签的账单。" in page.text
    assert 'href="/web/confirmed?ledger_id=owner&amp;month=2026-05"' in page.text
    assert ">清除筛选，查看全部</a>" in page.text


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

    form = _CsvExportForm(web_client.get("/web/import?ledger_id=owner").text)
    assert {"ledger_id", "month", "category", "tag"} <= form.fields.keys()
    form.fields.update(month="2026-05", category="餐饮", tag="Shared")
    response = web_client.get("/web/export.csv", params=form.fields)
    assert response.status_code == 200
    assert "Owner Shared" in response.text
    assert "Owner Other" not in response.text
    assert "Gray Shared" not in response.text


class _CsvExportForm(HTMLParser):
    """Submit the controls the rendered native GET form actually exposes."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}
        self.in_export = False
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            self.in_export = values.get("action") == "/web/export.csv" and values.get("method") == "get"
        if self.in_export and tag == "input" and values.get("name") and "disabled" not in values:
            self.fields[values["name"]] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.in_export = False


# UI/UX 批 14: /web/stats 页删除。原 test_web_stats_uses_tag_filter 覆盖的「按标签
# 看统计」已由 test_web_confirmed_tag_filter_is_ledger_scoped(本文件,/web/confirmed
# ?tag=)+ test_web_app_tags.test_web_tags_local_returns_200(看账单链接 → /web/confirmed
# ?tag=)联合接管,不再单测已删除的统计页。
