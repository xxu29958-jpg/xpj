"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from html import escape
from uuid import uuid4

from fastapi.testclient import TestClient


def test_web_merchants_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/merchants?ledger_id=owner")
    assert resp.status_code == 200
    assert "商家目录" in resp.text
    assert "不会覆盖原始账单商家" in resp.text


def test_web_merchants_catalog_and_alias_create_toggle_delete(web_client: TestClient) -> None:
    import re as _re

    _exercise_web_catalog_create_toggle_delete(web_client, _re)
    _exercise_web_alias_create_toggle_delete(web_client, _re)


def test_web_merchant_catalog_rename_conflict_points_to_merge(web_client: TestClient) -> None:
    import re as _re

    _create_web_catalog(web_client, "来源商家")
    _create_web_catalog(web_client, "目标商家")
    page = web_client.get("/web/merchants?ledger_id=owner")
    source_id = _catalog_public_id_for_name(page.text, "来源商家", _re)
    source_rv = _catalog_action_token(web_client, page.text, source_id, "rename", _re)

    conflict = web_client.post(
        f"/web/merchants/catalog/{source_id}/rename",
        data={
            "ledger_id": "owner",
            "expected_row_version": source_rv,
            "display_name": "目标商家",
        },
        follow_redirects=False,
    )

    assert conflict.status_code == 422
    assert 'data-body-stack="product"' in conflict.text
    assert f'data-catalog-key="{source_id}"' in conflict.text
    assert 'aria-describedby="merchant-rename-error"' in conflict.text
    assert 'role="alert"' in conflict.text
    assert 'name="display_name" value="目标商家"' in conflict.text
    assert _catalog_action_token(web_client, conflict.text, source_id, "rename", _re) == source_rv
    assert "商家名已被「目标商家」占用" in conflict.text
    assert "如需归并请使用『合并』" in conflict.text
    assert f"/web/merchants/catalog/{source_id}/merge" in conflict.text


def test_web_merchant_catalog_create_conflict_keeps_the_draft(web_client: TestClient) -> None:
    _create_web_catalog(web_client, "Unicode 咖啡 🧾")

    conflict = web_client.post(
        "/web/merchants/catalog/create",
        data={"idempotency_key": str(uuid4()), "display_name": "Unicode 咖啡 🧾", "ledger_id": "owner"},
        follow_redirects=False,
    )

    assert conflict.status_code == 422
    assert 'data-body-stack="product"' in conflict.text
    assert 'id="merchant-create-error"' in conflict.text
    assert 'role="alert"' in conflict.text
    assert "商家已存在，无需重复添加。" in conflict.text
    assert 'aria-describedby="merchant-create-error"' in conflict.text
    assert 'name="display_name"' in conflict.text
    assert 'value="Unicode 咖啡 🧾"' in conflict.text

    clean = web_client.get("/web/merchants?ledger_id=owner")
    assert clean.status_code == 200
    assert 'id="merchant-create-error"' not in clean.text


def test_web_merchant_catalog_create_conflict_points_to_recycled_entry(
    web_client: TestClient,
) -> None:
    import re as _re

    _create_web_catalog(web_client, "待恢复商家")
    page = web_client.get("/web/merchants?ledger_id=owner")
    public_id = _catalog_public_id_for_name(page.text, "待恢复商家", _re)
    deleted = web_client.post(
        f"/web/merchants/catalog/{public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": _catalog_action_token(web_client,
                page.text,
                public_id,
                "delete",
                _re,
            ),
        },
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}

    conflict = web_client.post(
        "/web/merchants/catalog/create",
        data={"idempotency_key": str(uuid4()), "display_name": "待恢复商家", "ledger_id": "owner"},
        follow_redirects=False,
    )

    assert conflict.status_code == 422
    assert "同名商家已在回收站。请先恢复该商家，或改用其它名称。" in conflict.text
    assert 'href="/web/recycle-bin?ledger_id=owner"' in conflict.text
    assert 'value="待恢复商家"' in conflict.text


def test_web_merchant_alias_create_conflict_keeps_both_draft_fields(web_client: TestClient) -> None:
    created = web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    conflict = web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "另一家",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )

    assert conflict.status_code == 422
    assert 'data-body-stack="product"' in conflict.text
    assert 'id="alias-create-error"' in conflict.text
    assert 'role="alert"' in conflict.text
    assert conflict.text.count('aria-describedby="alias-create-error"') == 2
    assert 'name="canonical_merchant"' in conflict.text
    assert 'value="另一家"' in conflict.text
    assert 'name="alias"' in conflict.text
    assert 'value="starbucks 国贸店"' in conflict.text

    clean = web_client.get("/web/merchants?ledger_id=owner")
    assert clean.status_code == 200
    assert 'id="alias-create-error"' not in clean.text


def test_web_merchant_alias_same_target_conflict_is_neutral_and_truthful(
    web_client: TestClient,
) -> None:
    created = web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    conflict = web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "星巴克",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )

    assert conflict.status_code == 422
    assert "商家别名已存在。" in conflict.text
    assert "已指向其他商家" not in conflict.text


def test_web_merchant_catalog_merge_retains_choice_after_conflict_then_creates_alias(
    web_client: TestClient,
) -> None:
    import re as _re

    _create_web_catalog(web_client, "Old Shop")
    _create_web_catalog(web_client, "New Shop")
    page = web_client.get("/web/merchants?ledger_id=owner")
    source_id = _catalog_public_id_for_name(page.text, "Old Shop", _re)
    target_id = _catalog_public_id_for_name(page.text, "New Shop", _re)
    source_rv = _catalog_action_token(web_client, page.text, source_id, "merge", _re)
    target_rv = _catalog_action_token(web_client, page.text, target_id, "rename", _re)

    renamed = web_client.post(
        f"/web/merchants/catalog/{target_id}/rename",
        data={"ledger_id": "owner", "expected_row_version": target_rv, "display_name": "New Shop Updated"},
    )
    assert renamed.status_code == 200
    original_choice = f"{target_id}:{target_rv}"
    conflict = web_client.post(
        f"/web/merchants/catalog/{source_id}/merge",
        data={"ledger_id": "owner", "expected_row_version": source_rv,
              "target": original_choice, "alias_policy": "create_source_alias"},
        follow_redirects=False,
    )
    assert conflict.status_code == 422
    assert f'value="{original_choice}" selected' in conflict.text
    assert 'value="create_source_alias" selected' in conflict.text
    assert _catalog_action_token(web_client, conflict.text, source_id, "merge", _re) == source_rv
    assert f"/web/merchants/catalog/{source_id}/rename" in conflict.text, "The refused merge changed its source"
    assert "还没有商家别名" in conflict.text, "The refused merge created an alias"
    target_rv = _catalog_action_token(web_client, conflict.text, target_id, "rename", _re)

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
    alias_page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
    assert "Old Shop" in alias_page.text and "New Shop Updated" in alias_page.text
    source_page = web_client.get(f"/web/merchants?ledger_id=owner&view=merchant&merchant={source_id}")
    assert f"merchant={target_id}" in source_page.text
    assert "这个商家已合并" in source_page.text
    assert f"/web/merchants/catalog/{source_id}/toggle" not in source_page.text
    assert f"/web/merchants/catalog/{source_id}/rename" not in source_page.text


def _create_web_catalog(web_client: TestClient, display_name: str) -> None:
    created = web_client.post(
        "/web/merchants/catalog/create",
        data={"idempotency_key": str(uuid4()), "display_name": display_name, "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}


def _catalog_public_id_for_name(html: str, display_name: str, re_module) -> str:
    match = re_module.search(
        rf'<a[^>]*data-catalog-key="([^"]+)"[^>]*aria-label="{re_module.escape(escape(display_name))}"', html,
    )
    assert match, f"catalog entry not found: {display_name}"
    return match.group(1)


def _catalog_action_token(web_client: TestClient, html: str, public_id: str, action: str, re_module) -> str:
    pattern = rf'/web/merchants/catalog/{public_id}/{action}.*?expected_row_version"\s*value="([^"]+)"'
    match = re_module.search(pattern, html, flags=re_module.DOTALL)
    if match is None:
        page = web_client.get(f"/web/merchants?ledger_id=owner&view=merchant&merchant={public_id}")
        assert page.status_code == 200
        match = re_module.search(pattern, page.text, flags=re_module.DOTALL)
    assert match, f"merchant task has no {action} form for {public_id}"
    return match.group(1)


def _exercise_web_catalog_create_toggle_delete(web_client: TestClient, re_module) -> None:
    catalog_created = web_client.post(
        "/web/merchants/catalog/create",
        data={"idempotency_key": str(uuid4()), "display_name": "星巴克", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert catalog_created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner")
    assert page.status_code == 200
    assert page.text.count("data-catalog-key=") == 1
    assert "星巴克" in page.text


    catalog_public_id = _catalog_public_id_for_name(page.text, "星巴克", re_module)
    page = web_client.get(f"/web/merchants?ledger_id=owner&view=merchant&merchant={catalog_public_id}")
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
    page = web_client.get(f"/web/merchants?ledger_id=owner&view=merchant&merchant={catalog_public_id}")

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
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
    assert page.status_code == 200
    assert "STARBUCKS 国贸店" in page.text
    assert "星巴克" in page.text

    duplicate = web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()),
            "canonical_merchant": "另一家",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert duplicate.status_code == 422
    assert "商家别名已存在" in duplicate.text

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
    page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
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
    page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
    assert "还没有商家别名" in page.text


def test_web_merchant_alias_delete_then_undo_restores(web_client: TestClient) -> None:
    """ADR-0038 undo: /web delete offers a 5s 撤销 banner that restores the row."""
    import re as _re

    web_client.post(
        "/web/merchants/aliases/create",
        data={"idempotency_key": str(uuid4()), "canonical_merchant": "星巴克", "alias": "STARBUCKS 国贸店", "ledger_id": "owner"},
        follow_redirects=False,
    )
    page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
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
    aliases_page = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
    assert "还没有商家别名" in aliases_page.text

    undone = web_client.post(
        f"/web/merchants/aliases/{public_id}/undo",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert undone.status_code in {303, 307}
    restored = web_client.get("/web/merchants?ledger_id=owner&view=aliases")
    assert "STARBUCKS 国贸店" in restored.text


def test_web_merchant_alias_undo_remote_returns_403(client: TestClient, *, identity) -> None:
    # ADR-0038: /web undo is loopback-gated like every other /web mutation.
    resp = client.post(
        "/web/merchants/aliases/some-public-id/undo",
        data={"ledger_id": "owner"},
    )
    assert resp.status_code == 403


def test_public_merchant_native_form_keeps_original_version_until_explicit_review(client, identity):
    """A real Web session cannot silently rebase or write while reviewing a stale name."""
    import re
    from contextlib import closing

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import MerchantCatalog
    from app.routes.web_auth import SESSION_COOKIE_NAME
    from tests._web_native_form_support import hidden_post_forms
    from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

    token = mint_session(client, identity=identity)
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, token)
        headers = {"Origin": f"https://{PUBLIC_HOST}"}
        start = web.get("/web/merchants?ledger_id=owner&view=new")
        create_path = "/web/merchants/catalog/create"
        fields = hidden_post_forms(start.text)[create_path]
        assert fields["csrf_token"]
        created = web.post(create_path, data={**fields, "display_name": "原商家"}, headers=headers,
                           follow_redirects=False)
        assert created.status_code == 303
        directory = web.get(created.headers["location"])
        public_id = _catalog_public_id_for_name(directory.text, "原商家", re)
        detail = web.get(f"/web/merchants?ledger_id=owner&view=merchant&merchant={public_id}")
        rename_path = f"/web/merchants/catalog/{public_id}/rename"
        forms = hidden_post_forms(detail.text)
        original = forms[rename_path]
        draft = "  我原来填写的名称  "
        denied = web.post(rename_path, headers=headers,
                          data={key: value for key, value in {**original, "display_name": draft}.items()
                                if key != "csrf_token"})
        assert denied.status_code == 403
        toggle_path = f"/web/merchants/catalog/{public_id}/toggle"
        changed = web.post(toggle_path, data=forms[toggle_path], headers=headers, follow_redirects=False)
        assert changed.status_code == 303
        conflict = web.post(rename_path, data={**original, "display_name": draft}, headers=headers)
        assert conflict.status_code == 422 and f'value="{draft}"' in conflict.text
        retained = hidden_post_forms(conflict.text)[rename_path]
        assert retained["expected_row_version"] == original["expected_row_version"]
        with SessionLocal() as db:
            row = db.scalar(select(MerchantCatalog).where(MerchantCatalog.public_id == public_id))
            original_id, current_version = row.id, row.row_version
            assert row.display_name == "原商家" and row.status == "hidden"
        review = web.post(rename_path, data={**retained, "display_name": draft, "review_latest": "1"}, headers=headers)
        assert review.status_code == 200 and f'value="{draft}"' in review.text
        reviewed = hidden_post_forms(review.text)[rename_path]
        assert int(reviewed["expected_row_version"]) == current_version
        with SessionLocal() as db:
            row = db.get(MerchantCatalog, original_id)
            assert row.display_name == "原商家" and row.row_version == current_version
        accepted = web.post(rename_path, data={**reviewed, "display_name": draft}, headers=headers,
                            follow_redirects=False)
        assert accepted.status_code == 303
        with SessionLocal() as db:
            row = db.get(MerchantCatalog, original_id)
            assert row.public_id == public_id and row.display_name == draft.strip() and row.status == "hidden"
