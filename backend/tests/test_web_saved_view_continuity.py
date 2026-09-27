"""Native saved-view forms preserve the original query through refusals and repair."""

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember, SavedView, Tag
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._infra.tag_helpers import manual_expense
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


@pytest.fixture
def browser(client, identity):
    token = mint_session(client, identity=identity)
    web = public_client()
    web.cookies.set(SESSION_COOKIE_NAME, token, domain=PUBLIC_HOST, path="/")
    yield web
    web.close()


def _post(browser, action, fields):
    return browser.post(action, data=fields, headers={"Origin": f"https://{PUBLIC_HOST}"},
                        follow_redirects=False)


def _create(browser, client, identity):
    manual_expense(client, identity.app_headers, tags="旅行", merchant="原旅行账单",
                   expense_time="2026-09-03T10:00:00Z")
    page = browser.get("/web/confirmed?ledger_id=owner&month=2026-09&tag=旅行&home_currency_code=CNY")
    assert page.status_code == 200, page.text
    fields = {**hidden_post_forms(page.text)["/web/saved-views"],
              "name": "九月旅行", "month_mode": "fixed"}
    result = _post(browser, "/web/saved-views", fields)
    assert result.status_code == 303, result.text
    with SessionLocal() as db:
        view = db.scalar(select(SavedView).where(SavedView.tenant_id == "owner"))
        return view.public_id, fields


def _editor(browser, public_id, original):
    page = browser.get("/web/saved-views?ledger_id=owner")
    assert page.status_code == 200, page.text
    action = f"/web/saved-views/{public_id}/rename"
    return action, {**original, **hidden_post_forms(page.text)[action]}


def test_conflicting_names_and_stale_forms_keep_input_without_overwriting_new_conditions(browser, client, identity):
    public_id, original = _create(browser, client, identity)
    duplicate = _post(browser, "/web/saved-views", {**original, "idempotency_key": "other-creation"})
    assert duplicate.status_code == 409, duplicate.text
    assert 'value="九月旅行"' in duplicate.text
    retained = hidden_post_forms(duplicate.text)["/web/saved-views"]
    assert retained["idempotency_key"] == "other-creation" and retained["ledger_id"] == "owner"
    action, old_fields = _editor(browser, public_id, original)
    changed = _post(browser, action, {**old_fields, "name": "最新名称", "month": "2026-10"})
    assert changed.status_code == 303, changed.text
    stale = _post(browser, action, {**old_fields, "name": "保留我的输入"})
    assert stale.status_code == 409 and 'value="保留我的输入"' in stale.text
    assert hidden_post_forms(stale.text)[action]["expected_row_version"] == old_fields["expected_row_version"]
    refused_delete = _post(browser, f"/web/saved-views/{public_id}/delete", old_fields)
    assert refused_delete.status_code == 409, refused_delete.text
    opened = browser.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False)
    assert opened.status_code == 303 and parse_qs(urlsplit(opened.headers["location"]).query)["month"] == ["2026-10"]
    with SessionLocal() as db:
        rows = db.scalars(select(SavedView).where(SavedView.tenant_id == "owner")).all()
        assert len(rows) == 1 and (rows[0].name, rows[0].month, rows[0].row_version) == ("最新名称", "2026-10", 2)


def test_role_refusal_preserves_original_query_and_ledger_form_cannot_retarget(browser, client, identity):
    public_id, original = _create(browser, client, identity)
    action, fields = _editor(browser, public_id, original)
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner"))
        member_id = member.id
        member.role = "viewer"
        db.commit()
    readonly = browser.get("/web/saved-views?ledger_id=owner")
    assert readonly.status_code == 200 and action not in hidden_post_forms(readonly.text)
    refused = _post(browser, action, {**fields, "name": "原输入继续"})
    assert refused.status_code == 403 and 'value="原输入继续"' in refused.text
    assert "权限恢复后重试原提交" in refused.text and 'type="submit" disabled' not in refused.text
    assert hidden_post_forms(refused.text)[action]["expected_row_version"] == fields["expected_row_version"]
    assert _post(browser, "/web/saved-views", {**original, "idempotency_key": "viewer-create"}).status_code == 403
    assert browser.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        db.get(LedgerMember, member_id).role = "owner"
        db.commit()
    foreign = _post(browser, action, {**fields, "ledger_id": "tester_1", "name": "不能改投当前账本"})
    assert foreign.status_code == 409 and "原提交已保留" in foreign.text
    assert hidden_post_forms(foreign.text)[action]["ledger_id"] == "tester_1"
    with SessionLocal() as db:
        view = db.scalar(select(SavedView).where(SavedView.public_id == public_id))
        assert (view.name, view.row_version, view.tenant_id) == ("九月旅行", 1, "owner")
    continued = _post(browser, action, {**fields, "name": "原输入继续"})
    assert continued.status_code == 303, continued.text
    with SessionLocal() as db:
        view = db.scalar(select(SavedView).where(SavedView.public_id == public_id))
        assert (view.name, view.row_version, view.month, view.tag_public_id) == (
            "原输入继续", 2, "2026-09", original["tag_public_id"])


def test_real_tag_rename_follows_identity_but_merge_requires_explicit_view_repair(browser, client, identity):
    public_id, original = _create(browser, client, identity)
    source_id = original["tag_public_id"]
    tag_page = browser.get("/web/tags?ledger_id=owner")
    rename = f"/web/tags/{source_id}/rename"
    renamed = _post(browser, rename, {**hidden_post_forms(tag_page.text)[rename], "name": "假期"})
    assert renamed.status_code == 303, renamed.text
    opened = browser.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False)
    assert opened.status_code == 303 and parse_qs(urlsplit(opened.headers["location"]).query)["tag"] == ["假期"]
    assert "原旅行账单" in browser.get(opened.headers["location"]).text
    manual_expense(client, identity.app_headers, tags="家庭", merchant="原家庭账单",
                   expense_time="2026-09-06T10:00:00Z")
    with SessionLocal() as db:
        target = db.scalar(select(Tag).where(Tag.tenant_id == "owner", Tag.key == "家庭"))
        target_id, target_version = target.public_id, target.row_version
    tag_page = browser.get("/web/tags?ledger_id=owner")
    merge = f"/web/tags/{source_id}/merge"
    merged = _post(browser, merge, {**hidden_post_forms(tag_page.text)[merge], "target": f"{target_id}:{target_version}"})
    assert merged.status_code == 303, merged.text
    unavailable = browser.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False)
    assert unavailable.status_code == 409 and "原标签已被删除或合并" in unavailable.text
    assert f'value="{source_id}" selected' in unavailable.text
    with SessionLocal() as db:
        view = db.scalar(select(SavedView).where(SavedView.public_id == public_id))
        assert (view.tag_public_id, view.row_version) == (source_id, 1)
    action, fields = _editor(browser, public_id, original)
    repaired = _post(browser, action, {**fields, "tag_public_id": target_id, "name": "家庭旅行"})
    assert repaired.status_code == 303, repaired.text
    opened = browser.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False)
    assert opened.status_code == 303 and parse_qs(urlsplit(opened.headers["location"]).query)["tag"] == ["家庭"]
    current = browser.get(opened.headers["location"])
    assert "原旅行账单" in current.text and "原家庭账单" in current.text
