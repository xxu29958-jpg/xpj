"""Inbox-domain page contracts for the Web UI/IA rebuild (218-D S4, 移植自产品矿并适配 main).

S4 落「收件域正文」: pending/duplicates 两页换 product 新标记, 经
base.html 的 _product_body_domains 开关断旧栈、挂 domains/inbox.css; /web 根
303→/web/pending (矿 IA 收件首域)。壳层合同 (五域 IA/月选器/角色壳/CSS token)
在 test_web_product_rebuild.py, 本文件只钉收件域页面正文。
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from _web_bulk_test_support import row_version as _row_version
from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from api_contract_helpers import web_save_expense
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


def test_web_pending_bulk_selection_markup_and_js_field_name(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    assert f'data-expense-id="{eid}"' in resp.text
    # 218-D S4-R1 行结构 (#218 同构): 原生 checkbox 是容器内兄弟槽,
    # 行链接 a.exp-row-detail 子树零交互控件；表单关联保留无 JS 路径。
    assert 'aria-selected="false"' in resp.text
    assert ('<button class="product-button" type="button" data-bulk-clear>取消选择</button>') in resp.text
    assert f'aria-label="选择账单 #{eid}"' in resp.text
    assert 'type="checkbox"' in resp.text
    assert 'role="checkbox"' not in resp.text
    assert 'name="expense_snapshot"' in resp.text
    assert 'form="bulk-form"' in resp.text
    assert 'data-row-version="' in resp.text
    assert "exp-row-detail" in resp.text
    assert 'name="category"' in resp.text
    assert 'name="merchant"' in resp.text

    js_path = Path(__file__).resolve().parents[1] / "app/static/web/desktop/bulk-bar.js"
    js = js_path.read_text(encoding="utf-8")
    assert 'h.name = "expense_ids";' in js
    assert 'token.name = "expected_row_version";' in js
    assert "token.value = entry.rowVersion;" in js
    assert "if (entry.rowVersion)" not in js
    assert 'document.querySelectorAll(".row-check:checked")' in js
    assert "isNativeBox" not in js
    assert 'classList.toggle("checked", on);' not in js
    assert 'row.setAttribute("aria-disabled", "true");' in js
    assert 'row.setAttribute("tabindex", "-1");' in js
    assert "setBatchNavigationMode(entries.length > 0);" in js
    assert "e.stopPropagation();" in js

    drawer_js = js_path.with_name("drawer.js").read_text(encoding="utf-8")
    hotkeys_js = js_path.with_name("review-hotkeys.js").read_text(encoding="utf-8")
    assert 'row.getAttribute("aria-disabled") === "true"' in drawer_js
    assert 'getAttribute("aria-disabled") !== "true"' in hotkeys_js
    assert 'classList.toggle("is-current", r === row);' in hotkeys_js
    inbox_css = js_path.parents[1] / "product" / "domains" / "inbox.css"
    assert inbox_css.read_text(encoding="utf-8").count(".exp-row.is-current") >= 1

    # 原生 checkbox 自带 id:row_version，无 JS 仍提交相同 OCC 快照。
    token = _row_version(web_client, eid, identity=identity)
    no_js = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_snapshot": f"{eid}:{token}",
            "category": "无 JS 分类",
            "filter": "all",
        },
        follow_redirects=False,
    )
    assert no_js.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner")
    assert "无 JS 分类" in detail.text


@pytest.mark.parametrize(
    ("path", "page_level", "copy"),
    [
        ("/web/pending?ledger_id=owner", "primary", "把新账单整理清楚"),
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


def test_inbox_pending_rows_keep_checkbox_outside_row_link(
    web_client: TestClient, *, identity
) -> None:
    """S4-R1 行格钉: 勾选控件是 .exp-row 容器内的兄弟节点 (选择槽), 行链接
    a.exp-row-detail 子树内零交互控件 (HTML 禁嵌, JS 未载时嵌套点击会穿透
    　跳转); 原生控件保留 label 与 main 的批量 OCC token，并关联
    bulk-form。表头不做整树 aria-hidden，只对纯展示列标签隐藏。"""
    expense_id = _create_pending(web_client, identity=identity)
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    row = re.search(
        rf'<div class="exp-row" data-expense-id="{expense_id}">.*?</a>\s*</div>',
        body,
        re.S,
    )
    assert row is not None
    row_html = row.group(0)
    link = re.search(r'<a class="exp-row-detail".*?</a>', row_html, re.S)
    assert link is not None
    link_html = link.group(0)
    assert f'href="/web/expenses/{expense_id}/edit?ledger_id=owner"' in link_html
    assert "data-fragment-url=" in link_html
    assert 'aria-selected="false"' in link_html
    # 行链接子树内零交互控件 (R1-5 结构钉): 剥掉起始标签后无 role=checkbox /
    # input / button / 嵌套 a。
    link_inner = re.sub(r"^<a [^>]*>", "", link_html)
    assert 'role="checkbox"' not in link_inner
    assert "<input" not in link_inner
    assert "<button" not in link_inner
    assert "<a " not in link_inner
    # 原生勾选控件在容器内、链接外 (兄弟位), 保留 OCC token，
    # 并关联 bulk-form，无 JS 仍可提交同一快照。
    check = re.search(
        r'<input class="checkbox row-check"[^>]+type="checkbox"[^>]*>', row_html
    )
    assert check is not None
    assert row_html.index('class="checkbox row-check"') < row_html.index('class="exp-row-detail"')
    assert 'name="expense_snapshot"' in check.group(0)
    assert 'form="bulk-form"' in check.group(0)
    assert f'value="{expense_id}:' in check.group(0)
    assert 'data-row-version="' in check.group(0)
    assert f'aria-label="选择账单 #{expense_id}"' in check.group(0)
    assert body.count('type="checkbox"') >= 2

    # R1-3: 表头无整树 aria-hidden; 全选控件暴露 label/state; 列标签单独隐藏。
    head = re.search(r'<div class="exp-head".*?</div>\s*<div class="exp-row"', body, re.S)
    assert head is not None
    head_html = head.group(0)
    assert '<div class="exp-head" aria-hidden="true">' not in head_html
    assert '<div class="exp-head">' in head_html
    select_all = re.search(
        r'<input class="checkbox" id="check-all"[^>]*>', head_html
    )
    assert select_all is not None
    assert 'type="checkbox"' in select_all.group(0)
    assert 'aria-label="选择全部账单"' in select_all.group(0)
    assert head_html.count('aria-hidden="true"') == 6  # 六个纯展示列标签

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


def test_inbox_thumbnail_materialization_does_not_bump_occ_token(
    web_client: TestClient, *, identity
) -> None:
    """S4-R1: 派生缩略图物化不进 OCC 版本语义 — 有原图无缩略图的行, GET
    thumbnail 物化后 row_version 不变; 页面渲染时嵌入的批量 token 在物化
    后依然可用 (物化路径曾 bump_row_version, 任何批量动作 409)。"""
    expense_id = _create_pending(web_client, identity=identity)
    saved = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "9.00", "merchant": "盒马", "category": "餐饮",
              "note": "", "ledger_id": "owner"},
    )
    assert saved.status_code in {303, 307}, saved.text
    # 模拟迁移行: 有原图、无缩略图产物。
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        assert row is not None
        row.thumbnail_path = None
        db.commit()
    before = _row_version(web_client, expense_id, identity=identity)

    page = web_client.get("/web/pending?ledger_id=owner")
    assert page.status_code == 200
    thumb = web_client.get(f"/web/expenses/{expense_id}/thumbnail?ledger_id=owner")
    assert thumb.status_code == 200
    assert _row_version(web_client, expense_id, identity=identity) == before

    # 用页面渲染时嵌入的 token 批量确认 → 不得 409。
    check = re.search(
        rf'<input class="checkbox row-check"[^>]+data-id="{expense_id}"[^>]*>', page.text
    )
    assert check is not None
    token = re.search(r'data-row-version="([^"]+)"', check.group(0))
    assert token is not None
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "confirm_ready",
            "ledger_id": "owner",
            "expense_ids": [str(expense_id)],
            "expected_row_version": [token.group(1)],
            "filter": "all",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    payload = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    assert payload["status"] == "confirmed"


def test_inbox_drawer_surfaces_missing_category_and_blocks_confirm(
    web_client: TestClient, *, identity
) -> None:
    """S4-R1/R2: 缺类信号进抽屉 — 脏分类行 (none/未分类 族) 在抽屉里只有警示条、
    无绿徽, facts 格显示「待分类」而非脏 token; 单行确认与队列 ready 门同义。
    R2: 缺类门下沉 confirm_expense 服务层, API 直调同 422, 不随传输层漂移。"""
    with SessionLocal() as db:
        dirty = Expense(
            tenant_id="owner", amount_cents=500, merchant="星巴克", category="none",
            source="pytest", status="pending", duplicate_status="none",
        )
        db.add(dirty)
        db.commit()
        expense_id = dirty.id

    drawer = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1")
    assert drawer.status_code == 200
    body = drawer.text
    assert "product-feedback--warning" in body
    assert "分类待补" in body
    assert "product-status--success" not in body
    assert "<dd>none</dd>" not in body
    assert "<dd>待分类</dd>" in body

    token = _row_version(web_client, expense_id, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner", "expected_row_version": str(token), "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 422, resp.text
    assert "请先填写分类" in resp.text

    # S4-R2: 同一不变量服务层守门 — API 直调 confirm 缺类行同 422。
    api = web_client.post(
        f"/api/expenses/{expense_id}/confirm",
        headers={
            **identity.app_headers,
            "Idempotency-Key": str(uuid4()),
        },
        json={"expected_row_version": _row_version(web_client, expense_id, identity=identity)},
    )
    assert api.status_code == 422, api.text
    assert "请先填写分类" in api.text

    payload = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    assert payload["status"] == "pending"
