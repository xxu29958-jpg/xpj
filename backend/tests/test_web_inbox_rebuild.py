"""Inbox-domain page contracts for the Web UI/IA rebuild (218-D S4, 移植自产品矿并适配 main).

S4 落「收件域正文」: pending/tasks/duplicates 三页换 product 新标记, 经
base.html 的 _product_body_domains 开关断旧栈、挂 domains/inbox.css; /web 根
303→/web/pending (矿 IA 收件首域)。壳层合同 (五域 IA/月选器/角色壳/CSS token)
在 test_web_product_rebuild.py, 本文件只钉收件域页面正文。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense
from app.version import STATIC_ASSET_VERSION
from tests._infra.assets import PNG_BYTES

_RETIRED_GLOBAL_STACK = (
    "/static/web/web.css",
    "/static/web/_base.css",
    "/static/web/_shell.css",
    "/static/web/_misc.css",
    "/static/web/components/",
)


def _create_pending(client: TestClient, *, identity) -> int:
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


@pytest.mark.parametrize(
    ("path", "page_level", "copy"),
    [
        ("/web/pending?ledger_id=owner", "primary", "把新账单整理清楚"),
        ("/web/tasks?ledger_id=owner", "secondary", "跟踪导入、迁移等耗时操作"),
        ("/web/duplicates?ledger_id=owner", "secondary", "逐组核对相似账单"),
    ],
)
def test_inbox_pages_render_new_modular_product_shell(
    web_client: TestClient,
    path: str,
    page_level: str,
    copy: str,
) -> None:
    """S4 (矿页面断言族回收): 收件域三页正文已是新标记 — 挂壳+组件+inbox 域模块,
    退役旧栈 (含页级 pages/pending.css / pages/duplicates.css) 不得回流,
    body hook 换 data-body-stack="product", 全页零内联样式。"""
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="inbox"' in body
    assert f'data-page="inbox" data-page-level="{page_level}"' in body
    assert copy in body
    assert re.search(
        r'href="/web/pending\?ledger_id=owner"[^>]+aria-current="location"', body
    )

    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/domains/inbox.css?v={STATIC_ASSET_VERSION}" in body

    for retired in _RETIRED_GLOBAL_STACK:
        assert retired not in body
    for retired_page in (
        "/static/web/pages/pending.css",
        "/static/web/pages/duplicates.css",
        "/static/web/pages/dashboard.css",
    ):
        assert retired_page not in body

    body_tag = re.search(r"<body [^>]+>", body)
    assert body_tag is not None
    assert "desktop-shell-active" not in body_tag.group(0)
    assert 'data-body-stack="product"' in body_tag.group(0)

    assert 'style="' not in body
    assert "<style" not in body


@pytest.mark.parametrize(
    "path",
    [
        "/web/pending?ledger_id=owner",
        "/web/tasks?ledger_id=owner",
        "/web/duplicates?ledger_id=owner",
    ],
)
def test_inbox_pages_have_no_legacy_presentation_dom(
    web_client: TestClient,
    path: str,
) -> None:
    """S4 (矿 test_high_risk_task_pages 回收): 收件域页面不得残留旧 dt-* 展示
    标记; 每个 POST 表单都带真 CSRF token (新栈页不再依赖 csrf.js 兜底注入)。"""
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'class="dt-' not in body
    assert "dt-card" not in body
    assert 'style="' not in body
    assert "<style" not in body

    for form_html in re.findall(r'<form method="post".*?</form>', body, re.S):
        assert 'name="csrf_token"' in form_html


def test_inbox_empty_state_matches_real_ingestion_routing(
    web_client: TestClient,
) -> None:
    """S4 (矿回收 + main 保留): 空队列文案反映真实 ingest 路径; main 的首日
    上传入口 (/owner/upload-links + 从 CSV 导入) 保留在空态里。"""
    pending = web_client.get("/web/pending?ledger_id=owner")

    assert pending.status_code == 200
    body = pending.text
    assert "新上传的截图、OCR 识别结果和导入草稿会出现在这里" in body
    assert "手动记账可直接在流水中查看" in body
    assert "手动记录和导入草稿会出现在这里" not in body
    # main 保留 (矿无): 空态给上传入口直达。
    assert 'href="/owner/upload-links"' in body
    assert "从 CSV 导入" in body


def test_inbox_pending_rows_use_whole_row_anchor_structure(
    web_client: TestClient, *, identity
) -> None:
    """S4 行格钉: 整行即链接 (a.exp-row + data-fragment-url + aria-selected),
    勾选控件是行内 data-stop 槽的 div[role=checkbox] (键盘可达, aria-checked),
    且带 main 的批量 OCC token (data-row-version)。旧嵌套标记
    (input[type=checkbox] / a.exp-row-detail) 不得回流。"""
    expense_id = _create_pending(web_client, identity=identity)
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    row = re.search(
        rf'<a class="exp-row"[^>]+data-expense-id="{expense_id}".*?</a>', body, re.S
    )
    assert row is not None
    row_html = row.group(0)
    assert f'href="/web/expenses/{expense_id}/edit?ledger_id=owner"' in row_html
    assert "data-fragment-url=" in row_html
    assert 'aria-selected="false"' in row_html
    check = re.search(
        r'<div class="checkbox row-check"[^>]+role="checkbox"[^>]*>', row_html
    )
    assert check is not None
    assert 'aria-checked="false"' in check.group(0)
    assert 'tabindex="0"' in check.group(0)
    assert 'data-row-version="' in check.group(0)
    assert f'aria-label="选择账单 #{expense_id}"' in check.group(0)
    assert "exp-row-detail" not in body
    assert 'type="checkbox"' not in body
    # 表头全选同为 ARIA checkbox。
    assert re.search(
        r'<div class="checkbox" id="check-all" role="checkbox" aria-checked="false" tabindex="0"',
        body,
    )
    # 批量条在(data-bulk), 且保留 main 的 OCC 隐藏字段装配与取消选择按钮。
    assert 'id="bulk-form"' in body
    assert "data-bulk-clear" in body


def test_inbox_pending_drawer_uses_product_markup(
    web_client: TestClient, *, identity
) -> None:
    """S4 drawer 范围裁决 (矿版含新 drawer 标记 → 一并移植): fragment=1 返回的
    抽屉本体是 product-drawer 新标记 (样式由 domains/inbox.css 的 product-drawer
    族供给), 旧 dt-*/drawer-head 标记不得残留; 批10 合同字段 (return_to=pending,
    OCC token, data-drawer-form) 保持。"""
    expense_id = _create_pending(web_client, identity=identity)
    drawer = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1"
    )

    assert drawer.status_code == 200
    body = drawer.text
    assert "product-drawer-editor" in body
    assert "product-drawer-evidence" in body
    assert "data-drawer-form" in body
    assert 'name="return_to" value="pending"' in body
    assert 'name="expected_row_version"' in body
    assert 'name="csrf_token"' in body
    assert 'class="drawer-head"' not in body
    assert 'class="drawer-receipt"' not in body
    assert "dt-" not in body
    assert 'style="' not in body


def test_inbox_duplicates_pair_renders_side_by_side_product_markup(
    web_client: TestClient, *, identity
) -> None:
    """S4 疑似重复并排钉: 参考记录/当前记录并排 (duplicate-compare), 状态 chip
    与判定原因走 glue 文案 (status_label/reason_label), 三个判定动作表单带
    CSRF + OCC token; viewer 无路可走时动作区不渲染写按钮。"""
    first = _create_pending(web_client, identity=identity)
    second = _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "suspected"
        assert row.duplicate_of_id == first

    response = web_client.get("/web/duplicates?ledger_id=owner")
    assert response.status_code == 200
    body = response.text
    assert "duplicate-compare" in body
    assert "参考记录" in body
    assert "当前待核对记录" in body
    assert f"#{second}" in body
    assert f"#{first}" in body
    assert "待确认" in body  # cur.status_label (pending)
    for action in ("keep", "reject-original", "reject-current"):
        form_html = re.search(
            rf'<form method="post" action="/web/duplicates/{second}/{action}".*?</form>',
            body,
            re.S,
        )
        assert form_html is not None, action
        assert 'name="csrf_token"' in form_html.group(0)
        assert 'name="expected_row_version"' in form_html.group(0)
