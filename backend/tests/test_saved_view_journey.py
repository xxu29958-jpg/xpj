"""A saved view preserves a shared query, not a frozen list of financial facts."""

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest

from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._infra.tag_helpers import manual_expense
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

pytestmark = pytest.mark.real_db


def _assert_original_query_return(browser, current, expense_id):
    detail_links = [unescape(link) for link in re.findall(r'href="([^"]+)"', current.text)
        if f"/web/expenses/{expense_id}/edit?" in link]
    assert len(detail_links) == 1
    detail = browser.get(detail_links[0])
    assert detail.status_code == 200
    return_queries = [parse_qs(urlsplit(unescape(link)).query)
        for link in re.findall(r'href="([^"]+)"', detail.text) if link.startswith("/web/confirmed?")]
    expected = {"q": ["九月"], "category": ["购物"], "tag": ["旅行"], "month": ["2026-09"]}
    assert any(expected.items() <= params.items() for params in return_queries)


def test_saved_view_reopens_the_same_query_and_reads_new_facts_without_changing_originals(client, identity) -> None:
    original = manual_expense(client, identity.app_headers, tags="旅行", merchant="九月原账单", category="购物",
                              expense_time="2026-09-03T10:00:00Z")
    before = client.get(f"/api/expenses/{original['id']}", headers=identity.app_headers)
    assert before.status_code == 200, before.text
    token = mint_session(client, identity=identity)
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, token, domain=PUBLIC_HOST, path="/")
    try:
        source = browser.get("/web/confirmed", params={"ledger_id": "owner", "month": "2026-09",
                                                     "tag": "旅行", "home_currency_code": "CNY", "q": "九月", "category": "购物"})
        assert source.status_code == 200, source.text
        entry = re.search(r'<a\b(?=[^>]*\bdata-save-view\b)[^>]*\bhref="([^"]+)"', source.text)
        assert entry is not None, "The current financial query has no save-view entry"
        href = unescape(entry.group(1))
        conditions = {key: values[0] for key, values in parse_qs(urlsplit(href).query, keep_blank_values=True).items() if key != "create"}
        editor = browser.get(href)
        assert editor.status_code == 200 and 'value="2026-09"' in editor.text
        forms = hidden_post_forms(editor.text)
        submitted = {**conditions, **forms["/web/saved-views"], "name": "九月旅行", "month_mode": "fixed"}
        saved = browser.post("/web/saved-views", data=submitted,
                             headers={"Origin": f"https://{PUBLIC_HOST}"}, follow_redirects=False)
        assert saved.status_code == 303, saved.text
        library = browser.get("/web/library?ledger_id=owner")
        assert library.status_code == 200 and "/web/saved-views?ledger_id=owner" in library.text
    finally:
        browser.close()

    manual_expense(client, identity.app_headers, tags="旅行", merchant="后来记入的九月账单", category="购物",
                   expense_time="2026-09-15T10:00:00Z")
    manual_expense(client, identity.app_headers, tags="出差", merchant="九月其他标签账单", category="购物",
                   expense_time="2026-09-15T10:00:00Z")
    manual_expense(client, identity.app_headers, tags="旅行", merchant="九月关键词但十月账单", category="购物",
                   expense_time="2026-10-03T10:00:00Z")
    manual_expense(client, identity.app_headers, tags="旅行", merchant="九月其他分类账单", category="餐饮",
                   expense_time="2026-09-15T10:00:00Z")
    manual_expense(client, identity.app_headers, tags="旅行", merchant="不同关键词账单", category="购物",
                   expense_time="2026-09-15T10:00:00Z")
    reopened = public_client()
    reopened.cookies.set(SESSION_COOKIE_NAME, token, domain=PUBLIC_HOST, path="/")
    try:
        views = reopened.get("/web/saved-views?ledger_id=owner")
        assert views.status_code == 200 and "九月旅行" in views.text
        actions = hidden_post_forms(views.text)
        delete_action = next(action for action in actions if action.endswith("/delete"))
        public_id = delete_action.split("/")[-2]
        search = reopened.get("/web/search?ledger_id=owner&q=旅行")
        assert search.status_code == 200 and "九月旅行" in search.text
        assert f"/web/saved-views/{public_id}/open?ledger_id=owner" in search.text
        opened = reopened.get(f"/web/saved-views/{public_id}/open?ledger_id=owner", follow_redirects=False)
        assert opened.status_code == 303, opened.text
        location = urlsplit(opened.headers["location"])
        assert location.path == "/web/confirmed"
        query = parse_qs(location.query)
        assert {key: query[key] for key in ("ledger_id", "month", "tag", "home_currency_code", "q", "category")} == {
            "ledger_id": ["owner"], "month": ["2026-09"], "tag": ["旅行"], "home_currency_code": ["CNY"],
            "q": ["九月"], "category": ["购物"],
        }
        current = reopened.get(opened.headers["location"])
        assert current.status_code == 200
        assert "九月原账单" in current.text and "后来记入的九月账单" in current.text
        for excluded in ("九月其他标签账单", "九月关键词但十月账单", "九月其他分类账单", "不同关键词账单"):
            assert excluded not in current.text
        _assert_original_query_return(reopened, current, original['id'])
    finally:
        reopened.close()

    after = client.get(f"/api/expenses/{original['id']}", headers=identity.app_headers)
    assert after.status_code == 200, after.text
    for field in ("amount_cents", "home_currency", "original_currency", "original_amount_minor", "expense_time",
                  "accounting_time", "row_version", "fact_revision", "tags"):
        assert after.json()[field] == before.json()[field], field
