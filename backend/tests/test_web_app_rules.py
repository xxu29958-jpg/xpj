"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from api_contract_helpers import web_confirm_expense, web_save_expense
from fastapi.testclient import TestClient


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
    assert "分类规则" in resp.text


def _rule_token_for(page_html: str, rule_id: int, action: str) -> str:
    # ADR-0038 PR-1 (form-token): toggle/delete forms render the row's
    # current updated_at as a hidden ``expected_updated_at`` input.
    pattern = (
        rf"/web/rules/{rule_id}/{action}.*?expected_updated_at\"\s*value=\"([^\"]+)\""
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
        data={"ledger_id": "owner", "expected_updated_at": toggle_token},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    msg = parse_qs(urlparse(resp.headers["location"]).query)["msg"][0]
    assert msg == "规则 [测试关键词A] 已停用。"
    # Delete — refresh the page so the delete form's hidden token is
    # post-toggle and not stale.
    page = web_client.get("/web/rules?ledger_id=owner")
    delete_token = _rule_token_for(page.text, rule_id, "delete")
    resp = web_client.post(
        f"/web/rules/{rule_id}/delete",
        data={"ledger_id": "owner", "expected_updated_at": delete_token},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}


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
        data={"ledger_id": "owner", "expected_updated_at": delete_token},
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
    assert "历史账单规则预览" in preview.text
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
