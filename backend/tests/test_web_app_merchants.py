"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_web_merchants_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/merchants?ledger_id=owner")
    assert resp.status_code == 200
    assert "商家治理" in resp.text
    assert "不会覆盖原始账单商家" in resp.text


def test_web_merchants_catalog_and_alias_create_toggle_delete(web_client: TestClient) -> None:
    import re as _re

    _exercise_web_catalog_create_toggle_delete(web_client, _re)
    _exercise_web_alias_create_toggle_delete(web_client, _re)


def test_web_merchant_catalog_rename_conflict_points_to_merge(web_client: TestClient) -> None:
    import re as _re

    _create_web_catalog(web_client, "Merge Source")
    _create_web_catalog(web_client, "Merge Target")
    page = web_client.get("/web/merchants?ledger_id=owner")
    source_id = _catalog_public_id_for_name(page.text, "Merge Source", _re)
    source_rv = _catalog_action_token(page.text, source_id, "rename", _re)

    conflict = web_client.post(
        f"/web/merchants/catalog/{source_id}/rename",
        data={
            "ledger_id": "owner",
            "expected_row_version": source_rv,
            "display_name": "Merge Target",
        },
        follow_redirects=True,
    )

    assert conflict.status_code == 200
    assert "商家名已被「Merge Target」占用" in conflict.text
    assert "如需归并请使用『合并』" in conflict.text
    assert f"/web/merchants/catalog/{source_id}/merge" in conflict.text


def test_web_merchant_catalog_merge_creates_alias_without_rewriting_history(
    web_client: TestClient,
) -> None:
    import re as _re

    _create_web_catalog(web_client, "Old Shop")
    _create_web_catalog(web_client, "New Shop")
    page = web_client.get("/web/merchants?ledger_id=owner")
    source_id = _catalog_public_id_for_name(page.text, "Old Shop", _re)
    target_id = _catalog_public_id_for_name(page.text, "New Shop", _re)
    source_rv = _catalog_action_token(page.text, source_id, "merge", _re)
    target_rv = _catalog_action_token(page.text, target_id, "rename", _re)

    merged = web_client.post(
        f"/web/merchants/catalog/{source_id}/merge",
        data={
            "ledger_id": "owner",
            "expected_row_version": source_rv,
            "target": f"{target_id}:{target_rv}",
            "alias_policy": "create_source_alias",
        },
        follow_redirects=True,
    )

    assert merged.status_code == 200
    assert "历史账单不会改写" in merged.text
    assert "已创建来源别名" in merged.text
    assert "已合并" in merged.text
    assert "Old Shop" in merged.text
    assert "New Shop" in merged.text
    assert "<code>old shop</code>" in merged.text
    assert "<code>new shop</code>" in merged.text
    assert f"/web/merchants/catalog/{source_id}/toggle" not in merged.text
    assert f"/web/merchants/catalog/{source_id}/rename" not in merged.text


def _create_web_catalog(web_client: TestClient, display_name: str) -> None:
    created = web_client.post(
        "/web/merchants/catalog/create",
        data={"display_name": display_name, "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}


def _catalog_public_id_for_name(html: str, display_name: str, re_module) -> str:
    for row in html.split("<tr>"):
        if f"<td>{display_name}</td>" not in row:
            continue
        match = re_module.search(r"/web/merchants/catalog/([^/]+)/rename", row)
        assert match, row[:1000]
        return match.group(1)
    raise AssertionError(f"catalog row not found: {display_name}")


def _catalog_action_token(html: str, public_id: str, action: str, re_module) -> str:
    match = re_module.search(
        rf"/web/merchants/catalog/{public_id}/{action}.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        html,
        flags=re_module.DOTALL,
    )
    assert match, html[:1500]
    return match.group(1)


def _exercise_web_catalog_create_toggle_delete(web_client: TestClient, re_module) -> None:
    catalog_created = web_client.post(
        "/web/merchants/catalog/create",
        data={"display_name": "星巴克", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert catalog_created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner")
    assert page.status_code == 200
    assert "商家目录（1 个）" in page.text
    assert "星巴克" in page.text
    assert "<code>星巴克</code>" in page.text

    catalog_match = re_module.search(r"/web/merchants/catalog/([^/]+)/delete", page.text)
    assert catalog_match, page.text[:1000]
    catalog_public_id = catalog_match.group(1)
    catalog_toggle_token = re_module.search(
        rf"/web/merchants/catalog/{catalog_public_id}/toggle.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=re_module.DOTALL,
    )
    assert catalog_toggle_token, page.text[:1500]
    hidden = web_client.post(
        f"/web/merchants/catalog/{catalog_public_id}/toggle",
        data={"ledger_id": "owner", "expected_row_version": catalog_toggle_token.group(1)},
        follow_redirects=False,
    )
    assert hidden.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "隐藏" in page.text

    catalog_delete_token = re_module.search(
        rf"/web/merchants/catalog/{catalog_public_id}/delete.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=re_module.DOTALL,
    )
    assert catalog_delete_token, page.text[:1500]
    catalog_deleted = web_client.post(
        f"/web/merchants/catalog/{catalog_public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": catalog_delete_token.group(1),
        },
        follow_redirects=False,
    )
    assert catalog_deleted.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "还没有商家目录" in page.text


def _exercise_web_alias_create_toggle_delete(web_client: TestClient, re_module) -> None:
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

    match = re_module.search(r"/web/merchants/aliases/([^/]+)/delete", page.text)
    assert match, page.text[:500]
    public_id = match.group(1)
    # ADR-0038 PR-2e: /web mutate forms render the row's updated_at as a
    # hidden ``expected_row_version`` token; the page already contains it
    # so pull it out instead of fetching the API directly.
    token_match = re_module.search(
        rf"/web/merchants/aliases/{public_id}/toggle.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=re_module.DOTALL,
    )
    assert token_match, page.text[:1000]
    token = token_match.group(1)

    toggled = web_client.post(
        f"/web/merchants/aliases/{public_id}/toggle",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert toggled.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "停用" in page.text

    delete_token_match = re_module.search(
        rf"/web/merchants/aliases/{public_id}/delete.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=re_module.DOTALL,
    )
    assert delete_token_match, page.text[:1000]
    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": delete_token_match.group(1),
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
        rf"/web/merchants/aliases/{public_id}/delete.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page.text,
        flags=_re.DOTALL,
    ).group(1)

    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": delete_token},
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
