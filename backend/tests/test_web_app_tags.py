"""Tests for the /web 标签管理 UI (ADR-0043 slice C).

Mirrors test_web_app_merchants.py: seed tags implicitly via /api/expenses/manual,
then drive the /web surface. OCC tokens are scraped from the rendered HTML (the
real carrier the browser submits), not read from the DB.
"""

from __future__ import annotations

import re as _re
from contextlib import closing
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._infra.tag_helpers import demote_owner_to_viewer, expense_row, manual_expense, tag_index, tag_links
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


def _unused_tag(client: TestClient, headers: dict[str, str]) -> dict:
    expense = manual_expense(client, headers, tags="出差, 工作", merchant="原标签")
    corrected = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": expense["row_version"], "reason": "移除误加标签", "tags": "出差"},
    )
    assert corrected.status_code == 201, corrected.text
    return tag_index(client, headers)["工作"]


def test_unused_tags_show_only_unused_rows_but_keep_live_merge_destinations(web_client: TestClient, *, identity) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    used = tag_index(web_client, identity.app_headers)["出差"]
    other = _unused_tag(web_client, identity.gray_app_headers)
    page = web_client.get("/web/tags?ledger_id=owner&unused=1")
    assert page.status_code == 200
    assert f'data-tag-key="{unused["public_id"]}"' in page.text
    assert f'data-tag-key="{used["public_id"]}"' not in page.text
    assert other["public_id"] not in page.text
    editor = _editor(web_client, unused["public_id"], "merge", unused=True)
    assert f'value="{used["public_id"]}:{used["row_version"]}"' in editor.text
    assert 'href="/web/tags?ledger_id=owner"' in page.text


def test_unused_cleanup_does_not_remove_a_tag_reused_after_the_page_was_opened(web_client: TestClient, *, identity) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    public_id = unused["public_id"]
    page = _editor(web_client, public_id, "delete", unused=True)
    token = _row_version_for(page.text, public_id, "delete")
    manual_expense(web_client, identity.app_headers, tags="工作", merchant="新使用者")
    reused = tag_index(web_client, identity.app_headers)["工作"]
    assert str(reused["row_version"]) == token, "Reusing a live tag does not change its OCC token"
    rejected = web_client.post(
        f"/web/tags/{public_id}/delete",
        data={"ledger_id": "owner", "expected_row_version": token, "unused": "1"},
        follow_redirects=False,
    )
    assert rejected.status_code == 409
    assert tag_index(web_client, identity.app_headers)["工作"] == reused
    assert "已被使用" in rejected.text
    assert 'name="unused" value="1"' in rejected.text
    assert _row_version_for(rejected.text, public_id, "delete") == token


@pytest.mark.parametrize("action", ["rename", "merge"])
def test_unused_tag_actions_cannot_rewrite_a_bill_that_reused_the_source_after_render(
    web_client: TestClient, identity, action: str,
) -> None:
    source = _unused_tag(web_client, identity.app_headers)
    target = tag_index(web_client, identity.app_headers)["出差"]
    page = _editor(web_client, source["public_id"], action, unused=True)
    token = _row_version_for(page.text, source["public_id"], action)
    accepted = manual_expense(web_client, identity.app_headers, tags="工作", merchant="随后使用标签的账单")
    reused = tag_index(web_client, identity.app_headers)["工作"]
    assert str(reused["row_version"]) == token
    response = web_client.post(
        f"/web/tags/{source['public_id']}/{action}",
        data={"ledger_id": "owner", "unused": "1", "expected_row_version": token,
              "name": "办公", "target": f"{target['public_id']}:{target['row_version']}"},
        follow_redirects=False,
    )
    assert response.status_code == 409
    returned = response
    assert 'name="unused" value="1"' in returned.text
    assert "已被使用" in returned.text and 'role="alert"' in returned.text
    assert expense_row("随后使用标签的账单") == (accepted["id"], accepted["row_version"], "工作")
    assert tag_links(accepted["id"]) == ["工作"]
    current = tag_index(web_client, identity.app_headers)
    assert current["工作"] == reused and current["出差"] == target
    history = web_client.get(f"/api/expenses/{accepted['id']}/revisions", headers=identity.app_headers)
    assert history.status_code == 200 and history.json()["total"] == 1


def test_unused_cleanup_native_form_and_undo_preserve_the_same_view(client: TestClient, *, identity) -> None:
    unused = _unused_tag(client, identity.app_headers)
    public_id = unused["public_id"]
    session = mint_session(client, identity=identity)
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, session)
        headers = {"Origin": f"https://{PUBLIC_HOST}"}
        page = _editor(web, public_id, "delete", unused=True)
        path = f"/web/tags/{public_id}/delete"
        fields = hidden_post_forms(page.text)[path]
        assert fields["unused"] == "1" and fields["csrf_token"]
        rejected = web.post(path, data={**fields, "csrf_token": ""}, headers=headers)
        assert rejected.status_code == 403
        assert tag_index(client, identity.app_headers)["工作"] == unused
        deleted = web.post(path, data=fields, headers=headers, follow_redirects=False)
        assert deleted.status_code == 303
        assert "工作" not in tag_index(client, identity.app_headers)
        assert parse_qs(urlsplit(deleted.headers["location"]).query)["unused"] == ["1"]
        undo_page = web.get(deleted.headers["location"])
        undo_path, undo_fields = next((path, fields) for path, fields in hidden_post_forms(undo_page.text).items()
            if path.startswith("/web/tags/mutations/") and path.endswith("/undo"))
        undone = web.post(undo_path, data=undo_fields, headers=headers, follow_redirects=False)
        assert undone.status_code == 303
        assert parse_qs(urlsplit(undone.headers["location"]).query)["unused"] == ["1"]
        restored = tag_index(client, identity.app_headers)["工作"]
        assert restored["public_id"] == public_id and restored["usage_count"] == 0
        assert f'data-tag-key="{public_id}"' in web.get(undone.headers["location"]).text


def _editor(client: TestClient, public_id: str, action: str = "rename", *, unused: bool = False):
    catalog = client.get("/web/tags?ledger_id=owner" + ("&unused=1" if unused else ""))
    link = _re.search(rf'href="(/web/tags/{public_id}/edit\?[^"]*action={action}[^"]*)"', catalog.text)
    assert link is not None, catalog.text[:1500]
    page = client.get(unescape(link.group(1)))
    assert page.status_code == 200, page.text
    return page


def _row_version_for(page_text: str, public_id: str, action: str) -> str:
    """Pull the hidden expected_row_version from the {action} form of a tag row."""
    m = _re.search(
        rf"/web/tags/{public_id}/{action}.*?expected_row_version\"\s*value=\"([^\"]*)\"",
        page_text,
        flags=_re.DOTALL,
    )
    assert m, page_text[:1500]
    return m.group(1)


def test_web_tags_local_returns_200(web_client: TestClient, *, identity) -> None:
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    resp = web_client.get("/web/tags?ledger_id=owner")
    assert resp.status_code == 200
    assert "当前标签" in resp.text
    assert "出差" in resp.text
    # UI/UX 批 14: 旧「按标签看统计」(跳已删除的 /web/stats) 改成行级「看账单」,
    # 跳已确认账单页并按本标签过滤；HTML 实体不改变实际查询参数。
    assert "看账单" in resp.text
    assert "/web/confirmed?ledger_id=owner&tag=%E5%87%BA%E5%B7%AE" in unescape(resp.text)
    assert "/web/stats" not in resp.text


def test_web_tag_rename(web_client: TestClient, *, identity) -> None:
    expense = manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]

    page = _editor(web_client, public_id, "rename", unused=False)
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
    history = web_client.get(
        f"/api/expenses/{expense['id']}/revisions",
        headers=identity.app_headers,
    )
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["actor_account_name"] == "我"


def test_web_tag_rename_conflict_points_to_merge(web_client: TestClient, *, identity) -> None:
    """契约 5: renaming onto an existing key fails with a 合并 hint."""
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    manual_expense(web_client, identity.app_headers, tags="差旅", merchant="B")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]
    page = _editor(web_client, public_id, "rename", unused=False)
    token = _row_version_for(page.text, public_id, "rename")

    resp = web_client.post(
        f"/web/tags/{public_id}/rename",
        data={"ledger_id": "owner", "expected_row_version": token, "name": "差旅"},
        follow_redirects=False,
    )
    assert resp.status_code == 409
    assert 'data-body-stack="product"' in resp.text
    assert f'data-tag-key="{public_id}"' in resp.text
    assert 'role="alert"' in resp.text
    assert 'name="name" value="差旅"' in resp.text
    assert _row_version_for(resp.text, public_id, "rename") == token
    assert "合并" in resp.text
    # Both tags still exist — nothing silently merged.
    assert set(tag_index(web_client, identity.app_headers)) == {"出差", "差旅"}


def test_web_tag_delete_then_undo_restores(web_client: TestClient, *, identity) -> None:
    """Deletion offers an undo action that restores the original tag."""
    manual_expense(web_client, identity.app_headers, tags="出差", merchant="A")
    public_id = tag_index(web_client, identity.app_headers)["出差"]["public_id"]

    page = _editor(web_client, public_id, "delete", unused=False)
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

    page = _editor(web_client, source_id, "merge", unused=False)
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
    assert resp.status_code == 409
    assert "状态已变化" in resp.text
    assert _row_version_for(resp.text, public_id, "delete") == "999999"


def test_web_tag_undo_remote_returns_403(client: TestClient, *, identity) -> None:
    # ADR-0043: /web undo is loopback-gated like every other /web mutation.
    resp = client.post(
        "/web/tags/mutations/some-mutation-id/undo",
        data={"ledger_id": "owner", "expected_row_version": "1"},
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("token_kind", ["current", "blank", "stale", "conflict"])
def test_unused_tag_rename_keeps_original_version_until_explicit_review(
    web_client: TestClient, identity, token_kind: str
) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    public_id = unused["public_id"]
    page = _editor(web_client, public_id, "rename", unused=True)
    token = _row_version_for(page.text, public_id, "rename")
    submitted_token = {"blank": "", "stale": "999999"}.get(token_kind, token)
    name = "出差" if token_kind == "conflict" else "闲置工作"
    response = web_client.post(
        f"/web/tags/{public_id}/rename",
        data={"ledger_id": "owner", "unused": "1", "expected_row_version": submitted_token, "name": name},
        follow_redirects=False,
    )
    if token_kind == "current":
        assert response.status_code == 303
        assert parse_qs(urlsplit(response.headers["location"]).query)["unused"] == ["1"]
        returned = web_client.get(response.headers["location"])
        assert "闲置工作" in tag_index(web_client, identity.app_headers)
    else:
        assert response.status_code == 409
        returned = response
        assert 'role="alert"' in returned.text
        assert f'name="name" value="{name}"' in returned.text
        assert _row_version_for(returned.text, public_id, "rename") == submitted_token
        fields = hidden_post_forms(returned.text)[f"/web/tags/{public_id}/rename"]
        reviewed = web_client.post(f"/web/tags/{public_id}/rename", data={**fields, "name": name, "review_latest": "true"})
        assert reviewed.status_code == 200
        assert _row_version_for(reviewed.text, public_id, "rename") == token
        assert f'name="name" value="{name}"' in reviewed.text
        assert tag_index(web_client, identity.app_headers)["工作"] == unused
        assert 'name="unused" value="1"' in returned.text
    used = tag_index(web_client, identity.app_headers)["出差"]
    assert f'data-tag-key="{used["public_id"]}"' not in returned.text


def test_unused_tag_merge_to_used_target_keeps_filter_and_undo(
    web_client: TestClient, identity
) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    used = tag_index(web_client, identity.app_headers)["出差"]
    page = _editor(web_client, unused["public_id"], "merge", unused=True)
    path = f'/web/tags/{unused["public_id"]}/merge'
    fields = hidden_post_forms(page.text)[path]
    assert fields["unused"] == "1"
    fields["target"] = f'{used["public_id"]}:{used["row_version"]}'
    merged = web_client.post(path, data=fields, follow_redirects=False)
    assert merged.status_code == 303
    assert parse_qs(urlsplit(merged.headers["location"]).query)["unused"] == ["1"]
    assert "工作" not in tag_index(web_client, identity.app_headers)
    assert tag_index(web_client, identity.app_headers)["出差"]["usage_count"] == 1
    returned = web_client.get(merged.headers["location"])
    assert "当前没有未使用的标签" in returned.text
    assert 'name="unused" value="1"' in returned.text  # undo retains the filter


@pytest.mark.parametrize("action", ["delete", "merge", "undo"])
@pytest.mark.parametrize("token", ["", "999999"])
def test_unused_tag_failed_mutation_keeps_filter(
    web_client: TestClient, identity, action: str, token: str
) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    used = tag_index(web_client, identity.app_headers)["出差"]
    path = (
        "/web/tags/mutations/missing/undo" if action == "undo"
        else f'/web/tags/{unused["public_id"]}/{action}'
    )
    response = web_client.post(
        path,
        data={"ledger_id": "owner", "unused": "1", "expected_row_version": token,
              "target": f'{used["public_id"]}:{used["row_version"]}'},
        follow_redirects=False,
    )
    if action != "undo":
        assert response.status_code == 409
        returned = response
        assert 'name="unused" value="1"' in returned.text
        assert _row_version_for(returned.text, unused["public_id"], action) == token
        if action == "merge":
            assert f'value="{used["public_id"]}:{used["row_version"]}" selected' in returned.text
    else:
        assert response.status_code == 303
        assert parse_qs(urlsplit(response.headers["location"]).query)["unused"] == ["1"]
        returned = web_client.get(response.headers["location"])
    assert tag_index(web_client, identity.app_headers)["工作"] == unused
    assert f'data-tag-key="{unused["public_id"]}"' in returned.text
    assert 'product-feedback--error' in returned.text and 'role="alert"' in returned.text


def test_unused_tags_viewer_reads_but_cannot_cleanup(web_client: TestClient, identity) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    demote_owner_to_viewer()
    page = web_client.get("/web/tags?ledger_id=owner&unused=1")
    assert page.status_code == 200
    assert f'data-tag-key="{unused["public_id"]}"' in page.text
    assert "只读角色" in page.text
    assert f'action="/web/tags/{unused["public_id"]}/delete"' not in page.text
    rejected = web_client.post(
        f'/web/tags/{unused["public_id"]}/delete',
        data={"ledger_id": "owner", "unused": "1", "expected_row_version": str(unused["row_version"])},
    )
    assert rejected.status_code == 403
    assert tag_index(web_client, identity.app_headers)["工作"] == unused


def test_unused_cleanup_cannot_delete_another_ledgers_tag(web_client: TestClient, identity) -> None:
    unused = _unused_tag(web_client, identity.app_headers)
    other = _unused_tag(web_client, identity.gray_app_headers)
    rejected = web_client.post(
        f'/web/tags/{other["public_id"]}/delete',
        data={"ledger_id": "owner", "unused": "1", "expected_row_version": str(other["row_version"])},
        follow_redirects=False,
    )
    assert rejected.status_code == 404
    assert 'name="ledger_id" value="owner"' in rejected.text
    assert 'name="unused" value="1"' in rejected.text
    assert tag_index(web_client, identity.gray_app_headers)["工作"] == other
    assert tag_index(web_client, identity.app_headers)["工作"] == unused


@pytest.mark.parametrize("action", ["rename", "merge"])
def test_tag_conflict_keeps_original_versions_and_review_does_not_write(web_client, identity, action):
    expense = manual_expense(web_client, identity.app_headers, tags="原标签", merchant="原账单")
    manual_expense(web_client, identity.app_headers, tags="目标", merchant="目标账单")
    tags = tag_index(web_client, identity.app_headers)
    source, target = tags["原标签"], tags["目标"]
    path = f'/web/tags/{source["public_id"]}/{action}'
    original = hidden_post_forms(_editor(web_client, source["public_id"], action).text)[path]
    original.update(name="保留的新名称", target=f'{target["public_id"]}:{target["row_version"]}')
    other_id = (source if action == "rename" else target)["public_id"]
    other_path = f"/web/tags/{other_id}/rename"
    other = hidden_post_forms(_editor(web_client, other_id).text)[other_path]
    changed = web_client.post(other_path, data={**other, "name": "其它端已修改"}, follow_redirects=False)
    assert changed.status_code == 303
    before = tag_index(web_client, identity.app_headers)
    rejected = web_client.post(path, data=original)
    assert rejected.status_code == 409
    kept = hidden_post_forms(rejected.text)[path]
    assert kept["expected_row_version"] == original["expected_row_version"]
    if action == "merge":
        assert f'value="{original["target"]}" selected' in rejected.text
    else:
        assert 'name="name" value="保留的新名称"' in rejected.text
    assert tag_index(web_client, identity.app_headers) == before
    review = web_client.post(path, data={**original, "review_latest": "true"})
    assert review.status_code == 200
    assert tag_index(web_client, identity.app_headers) == before, "Review must not publish"
    ready = hidden_post_forms(review.text)[path]
    ready["name"] = "保留的新名称"
    if action == "merge":
        selected = _re.search(r'<select name="target"[^>]*>.*?<option value="([^"]+)" selected>', review.text, _re.DOTALL)
        assert selected is not None
        ready["target"] = selected.group(1)
        assert ready["target"] != original["target"]
    else:
        assert ready["expected_row_version"] != original["expected_row_version"]
    saved = web_client.post(path, data=ready, follow_redirects=False)
    assert saved.status_code == 303
    assert tag_links(expense["id"]) == ["保留的新名称" if action == "rename" else "其它端已修改"]


def test_native_tag_draft_retains_input_on_role_loss_and_refuses_another_browser(client, identity):
    source = _unused_tag(client, identity.app_headers)
    token = mint_session(client, identity=identity)
    path = f'/web/tags/{source["public_id"]}/rename'
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, token)
        original = hidden_post_forms(_editor(web, source["public_id"], unused=True).text)[path]
        original["name"] = "保留的出差安排"
        headers = {"Origin": f"https://{PUBLIC_HOST}"}
        demote_owner_to_viewer()
        denied = web.post(path, data=original, headers=headers)
        assert denied.status_code == 403
        retained = hidden_post_forms(denied.text)[path]
        for field in ("draft_scope", "draft_ref", "expected_row_version", "unused"):
            assert retained[field] == original[field]
        assert 'name="name" value="保留的出差安排"' in denied.text
        assert tag_index(client, identity.app_headers)["工作"] == source
        with SessionLocal() as db:
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
            member.role = "owner"
            db.commit()
        replacement = mint_session(client, identity=identity)
        web.cookies.set(SESSION_COOKIE_NAME, replacement)
        refused = web.post(path, data=original, headers=headers)
        assert refused.status_code == 409 and "身份或账本已切换" in refused.text
        assert tag_index(client, identity.app_headers)["工作"] == source
        web.cookies.set(SESSION_COOKIE_NAME, token)
        saved = web.post(path, data=original, headers=headers, follow_redirects=False)
        assert saved.status_code == 303
        assert tag_index(client, identity.app_headers)["保留的出差安排"]["public_id"] == source["public_id"]
