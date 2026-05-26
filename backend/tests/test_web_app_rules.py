"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

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
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_rules_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/rules?ledger_id=owner")
    assert resp.status_code == 200
    assert "分类规则" in resp.text


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
    # Toggle
    resp = web_client.post(
        f"/web/rules/{rule_id}/toggle",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    msg = parse_qs(urlparse(resp.headers["location"]).query)["msg"][0]
    assert msg == "规则 [测试关键词A] 已停用。"
    # Delete
    resp = web_client.post(
        f"/web/rules/{rule_id}/delete",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert resp.status_code in {303, 307}


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
    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
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
