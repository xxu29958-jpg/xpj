"""Actual rendered form -> shared command -> period, budget and reminder."""

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local
from tests.test_recurring_occurrences import _create_series, _payment


def _form(body, action):
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, flags=re.S):
        if f'name="action" value="{action}"' in form:
            return {
                name: unescape(value)
                for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form)
            }
    raise AssertionError(f"real {action} form is missing")


def _retry_form(body):
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, flags=re.S):
        if "重试原提交" in form:
            return {
                name: unescape(value)
                for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form)
            }
    raise AssertionError("the original proposal retry form is missing")


def test_web_association_and_undo_share_the_api_result(client: TestClient, *, identity) -> None:
    app.dependency_overrides[_require_local] = lambda: None
    try:
        series = _create_series(client, identity)
        payment = _payment(client, identity)
        path = f"/web/recurring/{series['public_id']}/occurrence"
        page = client.get(path, params={"ledger_id": "owner", "month": "2026-09"})
        assert page.status_code == 200, page.text
        original = _form(page.text, "link")
        assert original["expense_public_id"] == payment["public_id"]
        linked = client.post(path, data=original, follow_redirects=False)
        assert linked.status_code == 303, linked.text
        rendered = client.get(linked.headers["location"])
        assert "本期已关联付款" in rendered.text
        assert "2026-10-05" in rendered.text
        api = client.get(
            f"/api/recurring/items/{series['public_id']}/occurrences/2026-09",
            headers=identity.app_headers,
        )
        assert api.json()["reserved_amount_cents"] == 0
        cleared = client.post(path, data=_form(rendered.text, "clear"), follow_redirects=False)
        assert cleared.status_code == 303, cleared.text
        assert "本期尚未关联付款" in client.get(cleared.headers["location"]).text
        # Refreshing/retrying the original submitted form cannot relink after undo.
        replay = client.post(path, data=original, follow_redirects=False)
        assert replay.status_code == 303, replay.text
        current = client.get(replay.headers["location"])
        assert "本期尚未关联付款" in current.text
        assert client.get(
            f"/api/expenses/{payment['id']}", headers=identity.app_headers,
        ).json() == payment
    finally:
        app.dependency_overrides.pop(_require_local, None)


def _record_payment_href(html: str, *, series_id: str, period: str, ledger_id: str = "owner") -> str:
    section = re.search(r'<section\b[^>]*aria-label="记录本期付款"[^>]*>(.*?)</section>', html, flags=re.S)
    assert section is not None, "An unpaid period must offer a record-this-period payment task"
    for href in re.findall(r'href="([^"]+)"', section.group(1)):
        parsed = urlsplit(unescape(href))
        if parsed.path != "/web/expenses/new":
            continue
        query = parse_qs(parsed.query)
        assert query.get("return_to") == ["recurring_occurrence"]
        assert query.get("return_recurring_public_id") == [series_id]
        assert query.get("return_month") == [period]
        assert query.get("ledger_id") == [ledger_id]
        return unescape(href)
    raise AssertionError("The period payment entry must open the existing manual-expense owner")


def test_unpaid_period_record_payment_is_not_the_global_manual_entry(monkeypatch) -> None:
    from fastapi import Request

    from app.middleware import csrf
    from app.models import RecurringItem
    from app.routes import web_recurring_occurrences as web
    from app.schemas._recurring_occurrence import RecurringOccurrenceResponse

    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-recurring-render-signing-key")

    series_id = "6dce3575-fb65-4df5-bb93-7bb270e8df9b"
    item = RecurringItem(
        id=7, public_id=series_id, tenant_id="owner", merchant_name="海外订阅",
        merchant_key="海外订阅", home_currency_code="USD", baseline_amount_cents=2000,
        last_amount_cents=2000, row_version=3, status="active",
    )
    occurrence = RecurringOccurrenceResponse(
        series_public_id=series_id, period="2026-08", series_row_version=3, row_version=0,
        state="unfulfilled", home_currency_code="USD", planned_amount_cents=2000,
        reserved_amount_cents=2000, expense_public_id=None, expense_id=None,
        expense_row_version=None, paid_amount_cents=None, next_due_date=None,
    )
    monkeypatch.setattr(web, "_list_ledger_options", lambda *a: [])
    monkeypatch.setattr(web, "_resolve_selected_ledger_id", lambda *a, **kw: "owner")
    monkeypatch.setattr(web, "get_recurring_item", lambda *a, **kw: item)
    monkeypatch.setattr(web, "occurrence_response", lambda *a, **kw: occurrence)
    monkeypatch.setattr(web, "find_recurring_payments", lambda *a, **kw: [])
    monkeypatch.setattr(web, "_base_ctx", lambda request, **kw: {
        "request": request, "selected_ledger_id": "owner", "can_write": True, "csrf_field": "",
        "csrf_token": "", "selected_ledger_role": "owner",
    })
    request = Request({
        "type": "http", "method": "GET", "path": f"/web/recurring/{series_id}/occurrence",
        "query_string": b"", "headers": [],
    })
    page = web._page(request, object(), public_id=series_id, ledger_id="owner", month="2026-08")
    html = page.body.decode()
    href = _record_payment_href(html, series_id=series_id, period="2026-08")
    assert 'aria-label="选择本期付款"' in html
    assert href != "/web/expenses/new"
    assert occurrence.state == "unfulfilled"
    assert occurrence.reserved_amount_cents == 2000
    assert occurrence.expense_public_id is None


def test_expense_return_adapter_keeps_the_original_series_and_period() -> None:
    from app.routes._web_expense_return_context import edit_context_params, return_href

    series_id = "6dce3575-fb65-4df5-bb93-7bb270e8df9b"
    origin = {
        "return_to": "recurring_occurrence",
        "return_recurring_public_id": series_id,
        "return_month": "2026-08",
    }
    assert edit_context_params(**origin) == origin
    target = urlsplit(return_href(ledger_id="owner", default_path="/web/pending", **origin))
    assert not target.netloc
    assert target.path == f"/web/recurring/{series_id}/occurrence"
    assert parse_qs(target.query) == {"ledger_id": ["owner"], "month": ["2026-08"]}
    focused = return_href(
        ledger_id="owner",
        default_path="/web/pending",
        **{**origin, "return_payment_expense_id": "41"},
    )
    assert parse_qs(urlsplit(focused).query) == {
        "ledger_id": ["owner"], "month": ["2026-08"], "payment_id": ["41"],
    }
    assert edit_context_params(**{**origin, "return_payment_expense_id": "41"}) == {
        **origin, "return_payment_expense_id": "41",
    }
    assert "return_payment_expense_id" not in edit_context_params(
        **{**origin, "return_payment_expense_id": "not-an-id"}
    )
    escaped = return_href(
        ledger_id="owner",
        default_path="/web/pending",
        **{**origin, "return_recurring_public_id": "//outside.invalid/escape"},
    )
    assert urlsplit(escaped).path == "/web/pending" and not urlsplit(escaped).netloc


def test_human_confirm_return_reopens_the_original_unpaid_period() -> None:
    from app.routes._web_expense_return_context import ExpenseReturnContext, confirm_return_redirect

    series_id = "6dce3575-fb65-4df5-bb93-7bb270e8df9b"
    path, params = confirm_return_redirect(
        ExpenseReturnContext(
            return_to="recurring_occurrence",
            return_recurring_public_id=series_id,
            return_month="2026-08",
        ),
    )
    assert path == f"/web/recurring/{series_id}/occurrence"
    assert params == {"month": "2026-08"}
    focused_path, focused_params = confirm_return_redirect(
        ExpenseReturnContext(
            return_to="recurring_occurrence",
            return_recurring_public_id=series_id,
            return_month="2026-08",
            return_payment_expense_id="41",
        ),
    )
    assert focused_path == path
    assert focused_params == {"month": "2026-08", "payment_id": "41"}
    unsafe_path, _ = confirm_return_redirect(
        ExpenseReturnContext(
            return_to="recurring_occurrence",
            return_recurring_public_id="//outside.invalid/escape",
            return_month="2026-08",
        ),
    )
    assert unsafe_path == "/web/pending"


def test_web_association_invalid_action_keeps_the_original_key(client: TestClient, *, identity) -> None:
    app.dependency_overrides[_require_local] = lambda: None
    try:
        series = _create_series(client, identity)
        payment = _payment(client, identity)
        path = f"/web/recurring/{series['public_id']}/occurrence"
        page = client.get(path, params={"ledger_id": "owner", "month": "2026-09", "payment_id": payment["id"]})
        original = _form(page.text, "link")
        assert original["expense_public_id"] == payment["public_id"]
        assert original["payment_id"] == str(payment["id"])
        refused = client.post(path, data={**original, "action": "explode"}, follow_redirects=False)
        assert refused.status_code == 422, refused.text
        assert "NameError" not in refused.text
        retry = _retry_form(refused.text)
        assert retry["idempotency_key"] == original["idempotency_key"]
        assert retry["expense_public_id"] == payment["public_id"]
        assert retry["expected_row_version"] == original["expected_row_version"]
        assert retry["payment_id"] == str(payment["id"])
        refused_again = client.post(path, data={**retry, "action": "explode"}, follow_redirects=False)
        assert refused_again.status_code == 422, refused_again.text
        retry_again = _retry_form(refused_again.text)
        assert retry_again["payment_id"] == str(payment["id"])
    finally:
        app.dependency_overrides.pop(_require_local, None)


def test_web_association_state_conflict_keeps_the_original_proposal(client: TestClient, *, identity) -> None:
    app.dependency_overrides[_require_local] = lambda: None
    try:
        series = _create_series(client, identity)
        payment = _payment(client, identity)
        path = f"/web/recurring/{series['public_id']}/occurrence"
        page = client.get(path, params={"ledger_id": "owner", "month": "2026-09"})
        original = _form(page.text, "link")
        linked = client.post(path, data=original, follow_redirects=False)
        assert linked.status_code == 303, linked.text
        conflict = client.post(
            path,
            data={**original, "idempotency_key": uuid4().hex},
            follow_redirects=False,
        )
        assert conflict.status_code == 409, conflict.text
        assert "NameError" not in conflict.text
        retry = _retry_form(conflict.text)
        assert retry["expense_public_id"] == payment["public_id"]
        assert retry["expected_row_version"] == original["expected_row_version"]
        assert retry["idempotency_key"] != original["idempotency_key"]
    finally:
        app.dependency_overrides.pop(_require_local, None)


def test_focused_payment_review_keeps_the_original_period_return(client: TestClient, *, identity) -> None:
    app.dependency_overrides[_require_local] = lambda: None
    try:
        series = _create_series(client, identity)
        payment = _payment(client, identity)
        path = f"/web/recurring/{series['public_id']}/occurrence"
        page = client.get(
            path,
            params={"ledger_id": "owner", "month": "2026-09", "payment_id": payment["id"]},
        )
        assert page.status_code == 200, page.text
        section = re.search(
            r'<section\b[^>]*aria-label="刚记录的付款"[^>]*>(.*?)</section>',
            page.text,
            flags=re.S,
        )
        assert section is not None
        hrefs = [unescape(href) for href in re.findall(r'href="([^"]+)"', section.group(1))]
        review = next(href for href in hrefs if href.startswith(f"/web/expenses/{payment['id']}/edit"))
        query = parse_qs(urlsplit(review).query)
        assert query.get("return_to") == ["recurring_occurrence"]
        assert query.get("return_recurring_public_id") == [series["public_id"]]
        assert query.get("return_month") == ["2026-09"]
        assert query.get("return_payment_expense_id") == [str(payment["id"])]
        review_page = client.get(review)
        assert review_page.status_code == 200, review_page.text
        assert f'name="return_to" value="recurring_occurrence"' in review_page.text
        assert series["public_id"] in review_page.text
        back = re.search(r'href="(/web/recurring/[^"]+occurrence[^"]*)"', review_page.text)
        assert back is not None
        returned = client.get(unescape(back.group(1)))
        assert returned.status_code == 200, returned.text
        assert 'aria-label="刚记录的付款"' in returned.text
        assert str(payment["id"]) in returned.text
    finally:
        app.dependency_overrides.pop(_require_local, None)


