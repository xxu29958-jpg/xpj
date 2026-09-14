"""Actual rendered form -> shared command -> period, budget and reminder."""

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

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
    unsafe_path, _ = confirm_return_redirect(
        ExpenseReturnContext(
            return_to="recurring_occurrence",
            return_recurring_public_id="//outside.invalid/escape",
            return_month="2026-08",
        ),
    )
    assert unsafe_path == "/web/pending"
