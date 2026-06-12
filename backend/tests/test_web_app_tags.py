"""Tests for the /web 标签管理 UI (ADR-0043 slice C).

Mirrors test_web_app_merchants.py: seed tags implicitly via /api/expenses/manual,
then drive the /web surface. OCC tokens are scraped from the rendered HTML (the
real carrier the browser submits), not read from the DB.
"""

from __future__ import annotations

import re as _re

from fastapi.testclient import TestClient

from tests._infra.tag_helpers import manual_expense, tag_index


def _row_version_for(page_text: str, public_id: str, action: str) -> str:
    """Pull the hidden expected_row_version from the {action} form of a tag row."""
    m = _re.search(
        rf"/web/tags/{public_id}/{action}.*?expected_row_version\"\s*value=\"([^\"]+)\"",
        page_text,
        flags=_re.DOTALL,
    )
    assert m, page_text[:1500]
    return m.group(1)


def test_web_tags_local_returns_200(web_client: TestClient, *, identity) -> None:
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    resp = web_client.get("/web/tags?ledger_id=owner")
    assert resp.status_code == 200
    assert "标签管理" in resp.text
    assert "出差" in resp.text
    # UI/UX 批 14: 旧「按标签看统计」(跳已删除的 /web/stats) 改成行级「看账单」,
    # 跳已确认账单页并按本标签过滤(tag 经 urlencode;& 写字面量,不经 autoescape)。
    assert "看账单" in resp.text
    assert (
        "/web/confirmed?ledger_id=owner&tag=%E5%87%BA%E5%B7%AE" in resp.text
    )
    assert "/web/stats" not in resp.text


def test_web_tag_rename(web_client: TestClient, *, identity) -> None:
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]

    page = web_client.get("/web/tags?ledger_id=owner")
    token = _row_version_for(page.text, public_id, "rename")

    renamed = web_client.post(
        f"/web/tags/{public_id}/rename",
        data={"ledger_id": "owner", "expected_row_version": token, "name": "差旅"},
        follow_redirects=False,
    )
    assert renamed.status_code in {303, 307}
    page = web_client.get("/web/tags?ledger_id=owner")
    assert "差旅" in page.text
    # The denormalised tag on the expense was rewritten too.
    assert tag_index(web_client, identity.app_headers).keys() == {"差旅"}


def test_web_tag_rename_conflict_points_to_merge(web_client: TestClient, *, identity) -> None:
    """契约 5: renaming onto an existing key fails with a 合并 hint."""
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    manual_expense(web_client, identity.app_headers, tags="差旅", merchant="B")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]
    page = web_client.get("/web/tags?ledger_id=owner")
    token = _row_version_for(page.text, public_id, "rename")

    resp = web_client.post(
        f"/web/tags/{public_id}/rename",
        data={"ledger_id": "owner", "expected_row_version": token, "name": "差旅"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "合并" in resp.text
    # Both tags still exist — nothing silently merged.
    assert set(tag_index(web_client, identity.app_headers)) == {"出差", "差旅"}


def test_web_tag_delete_then_undo_restores(web_client: TestClient, *, identity) -> None:
    """ADR-0043 undo: /web delete offers a 5s 撤销 banner that restores the tag."""
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]

    page = web_client.get("/web/tags?ledger_id=owner")
    token = _row_version_for(page.text, public_id, "delete")
    deleted = web_client.post(
        f"/web/tags/{public_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    # The redirect carries the mutation handle (not the tag public_id) + token.
    assert "undo=" in deleted.headers["location"]
    assert "undo_rv=" in deleted.headers["location"]

    undo_page = web_client.get(deleted.headers["location"])
    assert "undo-banner" in undo_page.text
    assert "/web/tags/mutations/" in undo_page.text
    assert "撤销" in undo_page.text
    # Soft-deleted tag is hidden from the live list.
    assert "出差" not in tag_index(web_client, identity.app_headers)

    # Pull the undo handle + token out of the rendered banner and POST it.
    m = _re.search(
        r"/web/tags/mutations/([^/]+)/undo\".*?expected_row_version\"\s*value=\"([^\"]+)\"",
        undo_page.text,
        flags=_re.DOTALL,
    )
    assert m, undo_page.text[:1500]
    mutation_id, undo_token = m.group(1), m.group(2)
    undone = web_client.post(
        f"/web/tags/mutations/{mutation_id}/undo",
        data={"ledger_id": "owner", "expected_row_version": undo_token},
        follow_redirects=False,
    )
    assert undone.status_code in {303, 307}
    assert "出差" in tag_index(web_client, identity.app_headers)


def test_web_tag_merge(web_client: TestClient, *, identity) -> None:
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    manual_expense(web_client, identity.app_headers, tags="差旅", merchant="B")
    idx = tag_index(web_client, identity.app_headers)
    source_id = idx["出差"]["public_id"]
    target_id = idx["差旅"]["public_id"]

    page = web_client.get("/web/tags?ledger_id=owner")
    source_token = _row_version_for(page.text, source_id, "merge")
    # The merge target rides the <option value="public_id:row_version">.
    opt = _re.search(rf"value=\"({target_id}:[0-9]+)\"", page.text)
    assert opt, page.text[:1500]

    merged = web_client.post(
        f"/web/tags/{source_id}/merge",
        data={
            "ledger_id": "owner",
            "expected_row_version": source_token,
            "target": opt.group(1),
        },
        follow_redirects=False,
    )
    assert merged.status_code in {303, 307}
    idx = tag_index(web_client, identity.app_headers)
    assert "出差" not in idx  # source soft-deleted
    assert idx["差旅"]["usage_count"] == 2  # A + B now both on 差旅


def test_web_tag_stale_token_shows_expired(web_client: TestClient, *, identity) -> None:
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]
    resp = web_client.post(
        f"/web/tags/{public_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": "999999"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "其它端" in resp.text or "已过期" in resp.text


def test_web_tag_undo_remote_returns_403(client: TestClient, *, identity) -> None:
    # ADR-0043: /web undo is loopback-gated like every other /web mutation.
    resp = client.post(
        "/web/tags/mutations/some-mutation-id/undo",
        data={"ledger_id": "owner", "expected_row_version": "1"},
    )
    assert resp.status_code == 403
