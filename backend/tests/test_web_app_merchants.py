"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_web_merchants_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/merchants?ledger_id=owner")
    assert resp.status_code == 200
    assert "商家治理" in resp.text
    assert "不会覆盖原始账单商家" in resp.text


def test_web_merchants_alias_create_toggle_delete(web_client: TestClient) -> None:
    created = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner")
    assert page.status_code == 200
    assert "STARBUCKS 国贸店" in page.text
    assert "starbucks 国贸店" in page.text

    duplicate = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "另一家",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert "商家别名已指向其他商家" in duplicate.text

    import re as _re
    match = _re.search(r"/web/merchants/aliases/([^/]+)/delete", page.text)
    assert match, page.text[:500]
    public_id = match.group(1)
    # ADR-0038 PR-2e: /web mutate forms render the row's updated_at as a
    # hidden ``expected_updated_at`` token; the page already contains it
    # so pull it out instead of fetching the API directly.
    token_match = _re.search(
        rf"/web/merchants/aliases/{public_id}/toggle.*?expected_updated_at\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=_re.DOTALL,
    )
    assert token_match, page.text[:1000]
    token = token_match.group(1)

    toggled = web_client.post(
        f"/web/merchants/aliases/{public_id}/toggle",
        data={"ledger_id": "owner", "expected_updated_at": token},
        follow_redirects=False,
    )
    assert toggled.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "停用" in page.text

    delete_token_match = _re.search(
        rf"/web/merchants/aliases/{public_id}/delete.*?expected_updated_at\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=_re.DOTALL,
    )
    assert delete_token_match, page.text[:1000]
    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_updated_at": delete_token_match.group(1),
        },
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "还没有商家别名" in page.text


def test_web_merchant_alias_delete_then_undo_restores(web_client: TestClient) -> None:
    """ADR-0038 undo: /web delete offers a 5s 撤销 banner that restores the row."""
    import re as _re

    web_client.post(
        "/web/merchants/aliases/create",
        data={"canonical_merchant": "星巴克", "alias": "STARBUCKS 国贸店", "ledger_id": "owner"},
        follow_redirects=False,
    )
    page = web_client.get("/web/merchants?ledger_id=owner")
    public_id = _re.search(r"/web/merchants/aliases/([^/]+)/delete", page.text).group(1)
    delete_token = _re.search(
        rf"/web/merchants/aliases/{public_id}/delete.*?expected_updated_at\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=_re.DOTALL,
    ).group(1)

    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={"ledger_id": "owner", "expected_updated_at": delete_token},
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    # The redirect carries the undo handle and the page renders the 撤销 banner.
    assert f"undo={public_id}" in deleted.headers["location"]
    undo_page = web_client.get(deleted.headers["location"])
    assert "undo-banner" in undo_page.text
    assert f"/web/merchants/aliases/{public_id}/undo" in undo_page.text
    assert "撤销" in undo_page.text
    assert "还没有商家别名" in undo_page.text  # hidden from the live list while soft-deleted

    undone = web_client.post(
        f"/web/merchants/aliases/{public_id}/undo",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert undone.status_code in {303, 307}
    restored = web_client.get("/web/merchants?ledger_id=owner")
    assert "STARBUCKS 国贸店" in restored.text


def test_web_merchant_alias_undo_remote_returns_403(client: TestClient, *, identity) -> None:
    # ADR-0038: /web undo is loopback-gated like every other /web mutation.
    resp = client.post(
        "/web/merchants/aliases/some-public-id/undo",
        data={"ledger_id": "owner"},
    )
    assert resp.status_code == 403
