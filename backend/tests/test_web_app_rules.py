"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from api_contract_helpers import web_confirm_expense, web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import CategoryPreference


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
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


def _rule_id_for_keyword(page_html: str, keyword: str) -> int:
    marker = f"<code>{keyword}</code>"
    marker_at = page_html.find(marker)
    assert marker_at >= 0, page_html[:1000]
    row_start = page_html.rfind("<tr", 0, marker_at)
    row_end = page_html.find("</tr>", marker_at)
    assert row_start >= 0 and row_end >= 0, page_html[:1000]
    row_html = page_html[row_start:row_end]
    id_match = re.search(r'/web/rules/(\d+)/toggle', row_html)
    assert id_match, row_html
    return int(id_match.group(1))


def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试", *, identity) -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_rules_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/rules?ledger_id=owner")
    assert resp.status_code == 200
    assert "当前规则" in resp.text


def _rule_token_for(page_html: str, rule_id: int, action: str) -> str:
    # ADR-0038 PR-1 (form-token): toggle/delete forms render the row's
    # current updated_at as a hidden ``expected_row_version`` input.
    pattern = (
        rf'<form[^>]*action="/web/rules/{rule_id}/{action}"[^>]*>.*?'
        r'name="expected_row_version"\s+value="([^"]+)"'
    )
    match = re.search(pattern, page_html, flags=re.DOTALL)
    assert match, page_html[:1000]
    return match.group(1)


def test_web_rules_create_then_delete(web_client: TestClient) -> None:
    # Create
    resp = web_client.post(
        "/web/rules/create",
        data={"keyword": "测试关键词A", "category": "餐饮", "priority": "100",
              "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    page = web_client.get("/web/rules?ledger_id=owner")
    assert "测试关键词A" in page.text
    rule_id = _rule_id_for_keyword(page.text, "测试关键词A")
    # Toggle — ADR-0038 PR-1 form-token: pull the hidden value out of
    # the rendered page and ship it back, mirroring what the JS would
    # submit from the browser.
    toggle_token = _rule_token_for(page.text, rule_id, "toggle")
    resp = web_client.post(
        f"/web/rules/{rule_id}/toggle",
        data={"ledger_id": "owner", "expected_row_version": toggle_token},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    msg = parse_qs(urlparse(resp.headers["location"]).query)["msg"][0]
    assert msg == "规则「测试关键词A」已停用。"
    # Delete — refresh the page so the delete form's hidden token is
    # post-toggle and not stale.
    page = web_client.get("/web/rules?ledger_id=owner")
    delete_token = _rule_token_for(page.text, rule_id, "delete")
    resp = web_client.post(
        f"/web/rules/{rule_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": delete_token},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}


def test_web_rule_create_error_keeps_the_complete_draft(web_client: TestClient) -> None:
    draft = {
        "keyword": "Unicode 咖啡 🧾",
        "category": "餐饮",
        "priority": "7",
        "amount_min_yuan": "20",
        "amount_max_yuan": "10",
        "source_contains": "微信 手动记账",
        "tag_contains": "差旅",
        "ledger_id": "owner",
    }

    response = web_client.post(
        "/web/rules/create",
        data=draft,
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert 'data-body-stack="product"' in response.text
    assert 'id="rule-create-error"' in response.text
    assert 'role="alert"' in response.text
    assert "金额下限不能大于上限" in response.text
    for field in (
        "keyword",
        "category",
        "priority",
        "amount_min_yuan",
        "amount_max_yuan",
        "source_contains",
        "tag_contains",
    ):
        assert re.search(
            rf'<input[^>]*name="{field}"[^>]*value="{re.escape(draft[field])}"',
            response.text,
        )

    clean = web_client.get("/web/rules?ledger_id=owner")
    assert clean.status_code == 200
    assert draft["keyword"] not in clean.text


def _disabled_rule_with_recycled_category(
    web_client: TestClient,
    *,
    identity,
) -> tuple[int, str]:
    created_expense = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 2600,
            "merchant": "规则分类商家",
            "category": "烘焙",
            "client_ref": "web-rule-recycled-category",
        },
    )
    assert created_expense.status_code == 200, created_expense.text

    created_rule = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "bakery",
            "category": "烘焙",
            "priority": "10",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created_rule.status_code in {303, 307}

    rules_page = web_client.get("/web/rules?ledger_id=owner")
    rule_id = _rule_id_for_keyword(rules_page.text, "bakery")
    disabled = web_client.post(
        f"/web/rules/{rule_id}/toggle",
        data={
            "ledger_id": "owner",
            "expected_row_version": _rule_token_for(rules_page.text, rule_id, "toggle"),
        },
        follow_redirects=False,
    )
    assert disabled.status_code in {303, 307}

    with SessionLocal() as db:
        preference = db.scalar(
            select(CategoryPreference).where(
                CategoryPreference.tenant_id == "owner",
                CategoryPreference.name == "烘焙",
            )
        )
        assert preference is not None
        preference_public_id = preference.public_id
        preference_row_version = preference.row_version

    removed = web_client.post(
        f"/web/categories/preferences/{preference_public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(preference_row_version),
        },
        follow_redirects=False,
    )
    assert removed.status_code == 303

    disabled_page = web_client.get("/web/rules?ledger_id=owner")
    return rule_id, _rule_token_for(disabled_page.text, rule_id, "toggle")


def test_web_rule_cannot_enable_a_category_that_is_in_recycle_bin(
    web_client: TestClient,
    *,
    identity,
) -> None:
    rule_id, retry_token = _disabled_rule_with_recycled_category(
        web_client,
        identity=identity,
    )
    rejected = web_client.post(
        f"/web/rules/{rule_id}/toggle",
        data={
            "ledger_id": "owner",
            "expected_row_version": retry_token,
        },
        follow_redirects=False,
    )

    assert rejected.status_code == 422
    assert 'data-body-stack="product"' in rejected.text
    assert 'id="rule-toggle-error"' in rejected.text
    assert 'role="alert"' in rejected.text
    assert "目标分类「烘焙」已在回收站" in rejected.text
    assert "请先恢复分类，再重新启用这条规则" in rejected.text
    assert 'href="/web/recycle-bin?ledger_id=owner"' in rejected.text
    assert _rule_token_for(rejected.text, rule_id, "toggle") == retry_token

    clean = web_client.get("/web/rules?ledger_id=owner")
    assert clean.status_code == 200
    assert 'id="rule-toggle-error"' not in clean.text


def test_web_rule_cannot_create_for_a_category_that_is_in_recycle_bin(
    web_client: TestClient,
    *,
    identity,
) -> None:
    _disabled_rule_with_recycled_category(web_client, identity=identity)

    rejected = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "bakery-new",
            "category": "烘焙",
            "priority": "10",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )

    assert rejected.status_code == 422
    assert "目标分类「烘焙」已在回收站" in rejected.text
    assert "请先恢复分类，再创建规则" in rejected.text
    assert 'href="/web/recycle-bin?ledger_id=owner"' in rejected.text
    assert 'value="bakery-new"' in rejected.text
    assert 'value="烘焙"' in rejected.text

    clean = web_client.get("/web/rules?ledger_id=owner")
    assert "bakery-new" not in clean.text


def test_web_rule_undo_explains_restore_order_when_category_is_recycled(
    web_client: TestClient,
    *,
    monkeypatch,
) -> None:
    category = "烘焙撤销"
    def _blocked_restore(*_args, **_kwargs):
        raise AppError(
            "rule_category_deleted",
            f"目标分类「{category}」已在回收站。",
            status_code=409,
        )

    monkeypatch.setattr("app.routes.web_rules.undo_delete_rule", _blocked_restore)

    blocked = web_client.post(
        "/web/rules/42/undo",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )

    assert blocked.status_code in {303, 307}
    message = parse_qs(urlparse(blocked.headers["location"]).query)["msg"][0]
    assert message == (
        f"未能恢复规则：目标分类「{category}」已在回收站。"
        "请先在回收站恢复该分类，再恢复本规则。"
    )
    rendered = web_client.get(blocked.headers["location"])
    assert message in rendered.text


def test_web_rules_delete_then_undo(web_client: TestClient) -> None:
    # ADR-0038 undo: /web delete soft-deletes + redirects with ?undo=<id> so
    # the page renders a 撤销 banner; POSTing it restores the rule.
    resp = web_client.post(
        "/web/rules/create",
        data={"keyword": "测试撤销规则", "category": "餐饮", "priority": "100",
              "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    page = web_client.get("/web/rules?ledger_id=owner")
    rule_id = _rule_id_for_keyword(page.text, "测试撤销规则")
    delete_token = _rule_token_for(page.text, rule_id, "delete")

    deleted = web_client.post(
        f"/web/rules/{rule_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": delete_token},
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    # The redirect carries ?undo=<id> so the banner shows.
    undo_q = parse_qs(urlparse(deleted.headers["location"]).query).get("undo")
    assert undo_q == [str(rule_id)]

    # With msg + undo present, the page renders the 撤销 banner pointing at undo.
    banner = web_client.get(f"/web/rules?ledger_id=owner&msg=deleted&undo={rule_id}")
    assert banner.status_code == 200
    assert f"/web/rules/{rule_id}/undo" in banner.text
    assert "撤销" in banner.text

    # A clean reload (no flash) confirms the rule is hidden — soft-deleted.
    clean = web_client.get("/web/rules?ledger_id=owner")
    assert "测试撤销规则" not in clean.text

    # Undo restores it.
    restored = web_client.post(
        f"/web/rules/{rule_id}/undo",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert restored.status_code in {303, 307}
    page = web_client.get("/web/rules?ledger_id=owner")
    assert "测试撤销规则" in page.text


def test_web_rules_preview_does_not_mutate(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "星巴克 国贸店", identity=identity)
    resp = web_client.get(
        "/web/rules?ledger_id=owner&preview_keyword=星巴克&preview_category=餐饮"
    )
    assert resp.status_code == 200
    # Preview must list the expense.
    assert str(expense_id) in resp.text
    # And original expense category not yet changed (still "其他").
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text


def test_web_rules_apply_pending_audit_and_rollback_integration(
    web_client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "Starbucks 上海", identity=identity)
    created = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "Starbucks",
            "category": "餐饮",
            "priority": "1",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    direct = web_client.post(
        "/web/rules/apply-pending",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert direct.status_code in {303, 307}
    assert "apply_preview=1" in direct.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text

    preview = web_client.get("/web/rules?ledger_id=owner&apply_preview=1")
    assert preview.status_code == 200
    assert "将改写" in preview.text
    assert "Starbucks 上海" in preview.text
    assert "确认应用到待确认" in preview.text
    token_match = re.search(r'name="preview_token" value="([0-9a-f]+)"', preview.text)
    assert token_match, preview.text[:1000]

    stale = web_client.post(
        "/web/rules/apply-pending",
        data={"ledger_id": "owner", "preview_confirmed": "yes"},
        follow_redirects=False,
    )
    assert stale.status_code in {303, 307}
    assert "apply_preview=1" in stale.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text

    applied = web_client.post(
        "/web/rules/apply-pending",
        data={
            "ledger_id": "owner",
            "preview_confirmed": "yes",
            "preview_token": token_match.group(1),
        },
        follow_redirects=False,
    )
    assert applied.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "餐饮" in detail.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200
    assert "规则应用记录" in page.text
    assert "已应用" in page.text
    assert "回滚" in page.text
    batch_match = re.search(r"/web/rules/applications/([^/]+)/rollback", page.text)
    assert batch_match, page.text[:1000]

    rolled_back = web_client.post(
        f"/web/rules/applications/{batch_match.group(1)}/rollback",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert rolled_back.status_code in {303, 307}
    restored = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in restored.text


def test_web_rules_apply_confirmed_requires_preview_then_applies(
    web_client: TestClient, *, identity,
) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "Historical Starbucks", identity=identity)
    confirmed = web_confirm_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    assert confirmed.status_code in {303, 307}

    created = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "Historical Starbucks",
            "category": "餐饮",
            "priority": "1",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    direct = web_client.post(
        "/web/rules/apply-confirmed",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert direct.status_code in {303, 307}
    assert "confirmed_preview=1" in direct.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text

    preview = web_client.get("/web/rules?ledger_id=owner&confirmed_preview=1")
    assert preview.status_code == 200
    assert "已确认历史账单：规则预览" in preview.text
    assert "Historical Starbucks" in preview.text
    assert "确认应用到已确认" in preview.text
    token_match = re.search(r'name="preview_token" value="([0-9a-f]+)"', preview.text)
    assert token_match, preview.text[:1000]

    applied = web_client.post(
        "/web/rules/apply-confirmed",
        data={
            "ledger_id": "owner",
            "preview_confirmed": "yes",
            "preview_token": token_match.group(1),
        },
        follow_redirects=False,
    )
    assert applied.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "餐饮" in detail.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200
    assert "已应用历史" in page.text
