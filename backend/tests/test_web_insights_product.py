"""W3 洞察片: reports / data-quality / dashboard/cards 正文迁 product 洞察域的契约测试。

只钉装配与真实协议 —— body 栈分流、域 CSS 挂载、旧栈断开、JS 钩子 id、
表单协议字段 (ledger_id/csrf_token)、GET 筛选保留; 不把装饰性 class 精确串
当产品正确性。真浏览器 POST/drag/API 后置条件由 test_web_dashboard_cards.py
(Codex owns) 与 tmp/w3-*.cjs 探针承担。
"""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

_PRODUCT_PAGES = (
    "/web/reports?ledger_id=owner",
    "/web/data-quality?ledger_id=owner",
    "/web/dashboard/cards?ledger_id=owner",
    "/web/overview?ledger_id=owner",
)


def _assert_product_body(body: str) -> None:
    body_tag = re.search(r"<body [^>]+>", body)
    assert body_tag is not None
    assert 'data-body-stack="product"' in body_tag.group(0)
    assert "desktop-shell-active" not in body_tag.group(0)
    assert "/static/web/product/domains/insights.css" in body
    # 断旧栈 + 页级 overview.css 物理退役。
    assert "/static/web/web.css" not in body
    assert "/static/web/pages/overview.css" not in body


@pytest.mark.parametrize("url", _PRODUCT_PAGES)
def test_insights_pages_use_product_stack(web_client: TestClient, url: str) -> None:
    resp = web_client.get(url)
    assert resp.status_code == 200
    _assert_product_body(resp.text)


def test_reports_page_keeps_js_hooks_and_nojs_data(web_client: TestClient) -> None:
    resp = web_client.get("/web/reports?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    _assert_product_body(body)
    # reports.js / trend-chart.js 的运行时钩子。
    for hook in (
        'id="reports-overview-data"',
        'id="reports-trend-chart"',
        'id="reports-merchant-chart"',
        'id="reports-category-chart"',
        'id="reports-export-png"',
        'id="chart-trend"',
        'id="reports-export-dialog"',
    ):
        assert hook in body
    # 无 JS 数据诚实: 每个图表面板带 details 数据表。
    assert body.count('class="report-data-disclosure"') >= 4
    # GET 分段控件仍是整页刷新链接。
    assert 'aria-current="page"' in body


def test_reports_segments_preserve_merchant_category(web_client: TestClient) -> None:
    """w3-reports-journey 反例: 带 merchant_category 进入后切换粒度/口径不得丢筛选。"""
    resp = web_client.get("/web/reports?ledger_id=owner&month=2026-05&merchant_category=餐饮")
    assert resp.status_code == 200
    seg_links = re.findall(
        r'href="(/web/reports\?[^"]*granularity=[^"]*)"', resp.text
    )
    assert seg_links, "分段控件链接缺失"
    for link in seg_links:
        query = parse_qs(urlsplit(unescape(link)).query)
        assert query["merchant_category"] == ["餐饮"]
        assert query["ledger_id"] == ["owner"]
        assert query["month"] == ["2026-05"]

    followed = web_client.get(unescape(seg_links[0]))
    assert followed.status_code == 200
    report_data = re.search(
        r'<script type="application/json" id="reports-overview-data">(.*?)</script>',
        followed.text,
        re.DOTALL,
    )
    assert report_data is not None
    report = json.loads(report_data.group(1))
    assert report["merchant_category"] == "餐饮"
    assert report["month"] == "2026-05"


def _form_block(body: str, action: str) -> str:
    m = re.search(
        r'<form[^>]*action="' + re.escape(action) + r'"[\s\S]*?</form>', body
    )
    assert m is not None, f"缺少表单 {action}"
    return m.group(0)


def test_dashboard_cards_forms_carry_csrf_and_ledger(web_client: TestClient) -> None:
    """noJS 原生 POST 403 反例: save/reset 两表单必须自带 csrf hidden 字段。"""
    resp = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    _assert_product_body(body)
    for action in ("/web/dashboard/cards/save", "/web/dashboard/cards/reset"):
        form = _form_block(body, action)
        assert 'name="csrf_token"' in form
        assert 'name="ledger_id"' in form
    # 拖排位置同步脚本外迁为 CSP 合规外部文件 (原内联脚本在 script-src 'self' 下不执行)。
    assert "/static/web/desktop/dashboard-cards.js" in body
    # 内部协议 key 只在 hidden 字段, 不作为可见文本展示。
    assert 'name="card_key" value="monthly_spend"' in body
    assert '>monthly_spend<' not in body
