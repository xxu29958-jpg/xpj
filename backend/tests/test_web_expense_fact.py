"""A1: /web confirmed 事实详情 + 显式更正 + 旧命令失权 + 批量 reason（最小证据集）。

后端 owner 已有 correction/permission/OCC/idempotency/items-splits 的精确测试
（test_expense_corrections.py、test_confirmed_batch_update_optimistic_concurrency.py
等）；本文件只证明 Web 消费者接线的可判决行为，不复制后端语义断言。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.web_expense_fact_test_support import create_confirmed as _create_confirmed
from tests.web_expense_fact_test_support import owner_member_id as _owner_member_id
from tests.web_expense_fact_test_support import row_version as _row_version


def _create_pending(client: TestClient, *, identity) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_confirmed_fact_page_read_first_and_pending_keeps_edit(web_client: TestClient, *, identity) -> None:
    confirmed_id = _create_confirmed(web_client, identity=identity)
    page = web_client.get(f"/web/expenses/{confirmed_id}/edit?ledger_id=owner")
    assert page.status_code == 200
    assert "更正这笔账单" in page.text
    assert "变更记录" in page.text
    # 事实页是三级详情工作区：detail.css 恰好装配一次（无重复链接）。
    assert page.text.count("/static/web/product/detail.css") == 1
    assert page.text.count("/static/web/pages/expense-fact.css") == 1
    # 明细/拆账堆叠为全宽卡片（不硬并排挤压六列表格）。
    assert 'class="grid two-col detail-sections"' not in page.text
    assert f'action="/web/expenses/{confirmed_id}/save"' not in page.text
    assert f'action="/web/expenses/{confirmed_id}/items/save"' not in page.text
    assert f'action="/web/expenses/{confirmed_id}/splits/save"' not in page.text
    assert f'formaction="/web/expenses/{confirmed_id}/reject"' not in page.text

    pending_id = _create_pending(web_client, identity=identity)
    pending_page = web_client.get(f"/web/expenses/{pending_id}/edit?ledger_id=owner")
    assert pending_page.status_code == 200
    assert pending_page.text.count("/static/web/product/detail.css") == 1
    assert f'action="/web/expenses/{pending_id}/save"' in pending_page.text
    assert "更正这笔账单" not in pending_page.text


def test_composite_correction_closes_scalar_items_and_splits(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    member_id = _owner_member_id()
    form = web_client.get(f"/web/expenses/{expense_id}/correct?ledger_id=owner")
    assert form.status_code == 200
    # 更正表单页：页级 CSS 恰好装配一次，无重复链接。
    assert form.text.count("/static/web/pages/expense-fact.css") == 1
    # 可编辑行表的每行/每列控件都有可辨识标签（placeholder 不冒充标签）。
    assert 'aria-label="明细第 1 行：名称"' in form.text
    assert 'aria-label="明细第 3 行：名称"' in form.text
    assert 'aria-label="拆账第 1 行：成员"' in form.text
    assert 'aria-label="拆账第 3 行：成员"' in form.text
    assert 'data-label="金额"' in form.text
    # 更正页币种可变，不能让初始币种的 step 在浏览器层拦截合法的新币种金额。
    assert 'step="any" inputmode="decimal"' in form.text
    resp = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "小票商家和明细看错了",
            "merchant": "更正后的商家",
            "expected_row_version": str(_row_version(web_client, expense_id, identity)),
            "item_name": ["苹果"],
            "item_kind": ["product"],
            "item_quantity": ["2个"],
            "item_unit_price_yuan": ["3.00"],
            "item_amount_yuan": ["6.00"],
            "item_category": ["餐饮"],
            "split_member_id": [str(member_id)],
            "split_amount_yuan": ["6.17"],
            "split_note": ["家人AA"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    fact = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert fact.status_code == 200
    assert "更正后的商家" in fact.text
    assert "小票商家和明细看错了" in fact.text
    assert "苹果" in fact.text
    # 只读行带窄屏标签（data-label 驱动行卡模式，真实数据行验证）。
    assert 'data-label="名称"' in fact.text
    assert 'data-label="成员"' in fact.text

    revisions = web_client.get(f"/api/expenses/{expense_id}/revisions", headers=identity.app_headers)
    assert revisions.status_code == 200
    latest = revisions.json()["items"][0]
    assert latest["change_kind"] == "correction"
    assert latest["reason"] == "小票商家和明细看错了"
    assert set(latest["changed_fields"]) >= {"merchant", "items", "splits"}


@pytest.mark.parametrize(
    ("invalid_rows", "section_title"),
    [
        (
            {
                "item_name": ["苹果"],
                "item_kind": ["product"],
                "item_quantity": [""],
                "item_unit_price_yuan": [""],
                "item_amount_yuan": ["不是金额"],
                "item_category": [""],
            },
            "小票明细",
        ),
        (
            {
                "split_member_id": ["owner-member"],
                "split_amount_yuan": ["不是金额"],
                "split_note": [""],
            },
            "家庭拆账",
        ),
    ],
)
def test_correction_row_errors_open_the_fold_for_no_js_recovery(
    web_client: TestClient,
    *,
    identity,
    invalid_rows: dict[str, list[str]],
    section_title: str,
) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    if "split_member_id" in invalid_rows:
        invalid_rows = {
            **invalid_rows,
            "split_member_id": [str(_owner_member_id())],
        }

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "验证错误恢复路径",
            "original_currency": "CNY",
            "expected_row_version": str(_row_version(web_client, expense_id, identity)),
            **invalid_rows,
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert section_title in response.text
    assert '<details class="dt-card correction-fold" open>' in response.text
    assert "行需要修正，请检查后重新提交" in response.text


def test_web_correction_can_change_original_currency_through_existing_fx_owner(
    web_client: TestClient, *, identity
) -> None:
    rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7.0000",
            "source": "manual",
        },
    )
    assert rate.status_code == 200, rate.text
    expense_id = _create_confirmed(web_client, identity=identity)

    form = web_client.get(f"/web/expenses/{expense_id}/correct?ledger_id=owner")
    assert form.status_code == 200
    assert '<select id="correct-currency" name="original_currency"' in form.text
    assert '<option value="USD"' in form.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "账单实际以美元支付",
            "original_currency": "USD",
            "amount_yuan": "10.00",
            "expected_row_version": str(_row_version(web_client, expense_id, identity)),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    current = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert current.status_code == 200, current.text
    assert current.json()["original_currency_code"] == "USD"
    assert current.json()["original_amount_minor"] == 1000
    assert current.json()["amount_cents"] == 7000


def test_correction_blank_reason_shows_validation_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "",
            "merchant": "想改但没写原因",
            "expected_row_version": str(_row_version(web_client, expense_id, identity)),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "请说明这次更正的原因" in resp.text


def test_web_correction_preserves_absent_and_clears_blank_time_and_scores(web_client: TestClient, *, identity) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "待清空附加事实",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
            "value_score": 5,
            "regret_score": 2,
        },
    )
    assert created.status_code == 200, created.text
    expense = created.json()

    merchant_only = web_client.post(
        f"/web/expenses/{expense['id']}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "只修正商家",
            "merchant": "正确商家",
            "expected_row_version": str(expense["row_version"]),
        },
        follow_redirects=False,
    )
    assert merchant_only.status_code == 303, merchant_only.text
    preserved = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers)
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["expense_time"] is not None
    assert preserved.json()["value_score"] == 5
    assert preserved.json()["regret_score"] == 2

    response = web_client.post(
        f"/web/expenses/{expense['id']}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "时间与评分不应保留",
            "expense_time": "",
            "value_score": "",
            "regret_score": "",
            "expected_row_version": str(preserved.json()["row_version"]),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    current = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers)
    assert current.status_code == 200, current.text
    assert current.json()["expense_time"] is None
    assert current.json()["value_score"] is None
    assert current.json()["regret_score"] is None


def test_correction_stale_token_shows_conflict_with_fresh_values(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    stale_token = _row_version(web_client, expense_id, identity)
    first = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "第一次更正",
            "merchant": "第一次的值",
            "expected_row_version": str(stale_token),
        },
        follow_redirects=False,
    )
    assert first.status_code == 303, first.text

    conflict = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "拿着旧页面再改",
            "merchant": "过期页面提交的值",
            "expected_row_version": str(stale_token),
        },
        follow_redirects=False,
    )
    assert conflict.status_code == 409
    assert "刚在其它端被修改" in conflict.text
    # 冲突页不能把过期标量与服务器最新 token 组合起来，否则二次提交会
    # 静默覆盖另一端事实。表单回到 current fact，并要求用户重新应用修改。
    assert 'value="第一次的值"' in conflict.text
    assert 'value="过期页面提交的值"' not in conflict.text
    assert "表单已载入最新基本信息" in conflict.text
    fresh_token = _row_version(web_client, expense_id, identity)
    assert f'name="expected_row_version" value="{fresh_token}"' in conflict.text
    assert f'name="expected_row_version" value="{stale_token}"' not in conflict.text


def test_web_correction_replay_hits_claim_before_current_state_diff(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    submitted = {
        "ledger_id": "owner",
        "reason": "修正商家并验证重放",
        "merchant": "重放后的商家",
        "expected_row_version": str(_row_version(web_client, expense_id, identity)),
        "idempotency_key": "web-correction-replay-key",
    }
    first = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=submitted,
        follow_redirects=False,
    )
    replay = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=submitted,
        follow_redirects=False,
    )

    assert first.status_code == 303, first.text
    assert replay.status_code == 303, replay.text
    history = web_client.get(f"/api/expenses/{expense_id}/revisions", headers=identity.app_headers)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 2


def test_web_acknowledges_confirmed_mismatch_through_revision_owner(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    before = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    corrected = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": "web-mismatch-setup"},
        json={
            "expected_row_version": before["row_version"],
            "reason": "补录金额不一致的原小票明细",
            "items": [{"name": "原小票项目", "kind": "product", "amount_cents": 1000}],
        },
    )
    assert corrected.status_code == 201, corrected.text
    current = corrected.json()["expense"]
    current_items = web_client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers).json()
    assert current_items["items_sum_status"] == "mismatch_known"

    response = web_client.post(
        f"/web/expenses/{expense_id}/items/acknowledge-mismatch",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(current["row_version"]),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    latest = web_client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers).json()
    assert latest["items_sum_status"] == "mismatch_acknowledged"
    history = web_client.get(f"/api/expenses/{expense_id}/revisions", headers=identity.app_headers).json()
    assert history["total"] == 3
    assert history["items"][0]["changed_fields"] == ["items_sum_status"]


@pytest.mark.parametrize("path", ["save", "items/save", "splits/save", "reject"])
def test_legacy_confirmed_web_mutations_are_rejected(web_client: TestClient, *, identity, path: str) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/{path}",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(_row_version(web_client, expense_id, identity)),
            "merchant": "旧路径直写",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 409, resp.text
    assert ("更正" in resp.text) or ("回收站" in resp.text)
    # 409 重渲与正常 GET 共享同一装配事实（page_surface 显式声明，不靠 URL
    # 子串）：事实页依赖的 detail.css 必须实际装配且恰好一次。
    assert resp.text.count("/static/web/product/detail.css") == 1


def test_batch_update_requires_reason_and_applies(web_client: TestClient, *, identity) -> None:
    expense_id = _create_confirmed(web_client, identity=identity)
    snapshot = f"{expense_id}:{_row_version(web_client, expense_id, identity)}"

    missing = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_snapshot": [snapshot],
            "category": "居家",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 422
    assert "请说明这次批量更正的原因" in missing.text

    applied = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_snapshot": [snapshot],
            "category": "居家",
            "reason": "统一整理分类",
            "idempotency_key": "web-fact-batch-category",
        },
        follow_redirects=False,
    )
    assert applied.status_code == 303, applied.text
    detail = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.json()["category"] == "居家"
