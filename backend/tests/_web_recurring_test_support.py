"""Shared helpers for the /web recurring test files.

The ``web_client`` fixture stays defined per test file (repo convention); this
module only holds seed/post/extract helpers.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import RecurringItem
from app.services.currency_binding_service import resolve_write_capability
from app.services.merchant_service import normalize_merchant
from app.services.time_service import now_utc
from tests._runtime_protocol import negotiated_headers


def open_recurring_form(client: TestClient, listing, *, public_id: str = ""):
    """Follow the actual focused-task link, keeping the selected ledger and month."""
    entry = "edit=" + public_id if public_id else "new_recurring=1"
    href = next(unescape(href) for href in re.findall(r'<a[^>]*href="([^"]+)"', listing.text) if entry in href)
    page = client.get(href)
    assert page.status_code == 200, page.text
    assert 'aria-label="我的固定支出"' not in page.text
    return page


def seed_candidate() -> None:
    # PR #253 R4: 候选扫描窗口为近 6 个月, 播种改相对日期 (固定日期会随时间掉出窗口)。
    base = now_utc()
    for when in (
        base - timedelta(days=62),
        base - timedelta(days=31),
        base,
    ):
        insert_confirmed_expense(
            amount_cents=20000,
            merchant="ChatGPT Plus",
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )


def seed_observed_item(
    *,
    merchant: str = "Cloud Storage",
    baseline_cents: int = 2_000,
    last_cents: int = 1_900,
    occurrence_count: int = 5,
    status: str = "active",
    next_date: date | None = date(2026, 9, 8),
    source: str = "candidate",
) -> str:
    """Seed a candidate-sourced formal item with real observation provenance."""
    now = now_utc()
    with SessionLocal() as db:
        resolve_write_capability(db)
        item = RecurringItem(home_currency_code="CNY",
            tenant_id="owner",
            merchant_key=normalize_merchant(merchant),
            merchant_name=merchant,
            frequency="monthly",
            baseline_amount_cents=baseline_cents,
            last_amount_cents=last_cents,
            occurrence_count=occurrence_count,
            last_seen_at=now if occurrence_count > 0 else None,
            next_expected_date=next_date,
            status=status,
            confidence="high" if occurrence_count > 0 else None,
            source=source,
            created_at=now,
            updated_at=now,
            archived_at=now if status == "archived" else None,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.public_id


def first_recurring_public_id() -> str:
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).limit(1))
        assert item is not None
        return item.public_id


def row_version(public_id: str) -> int:
    with SessionLocal() as db:
        token = db.scalar(
            select(RecurringItem.row_version).where(RecurringItem.public_id == public_id)
        )
        assert token is not None
        return token


def create_via_web(
    web_client: TestClient,
    *,
    merchant: str = "房租",
    amount: str = "6800",
    date_str: str = "2026-09-06",
    key: str | None = None,
):
    return web_client.post(
        "/web/recurring/create",
        data={"home_currency_code": "CNY",
            "ledger_id": "owner",
            "merchant": merchant,
            "baseline_amount_yuan": amount,
            "next_expected_date": date_str,
            "idempotency_key": key or str(uuid4()),
        },
        follow_redirects=False,
    )


def edit_via_web(
    web_client: TestClient,
    public_id: str,
    *,
    merchant: str = "Cloud Storage 家庭版",
    amount: str = "25",
    date_str: str = "2026-10-08",
    token: int,
    key: str | None = None,
):
    return web_client.post(
        f"/web/recurring/{public_id}/edit",
        data={"home_currency_code": "CNY",
            "ledger_id": "owner",
            "merchant": merchant,
            "baseline_amount_yuan": amount,
            "next_expected_date": date_str,
            "expected_row_version": str(token),
            "idempotency_key": key or str(uuid4()),
        },
        follow_redirects=False,
    )


def post_confirm(
    web_client: TestClient,
    *,
    merchant: str = "ChatGPT Plus",
    amount_cents: str = "20000",
    next_expected_date: str = "",
    **extra: str,
):
    """候选复核提交: 只带 merchant + amount 定位 + 可选日期 (provenance 服务端给)。"""
    return web_client.post(
        "/web/recurring/confirm-candidate",
        data={"home_currency_code": "CNY",
            "ledger_id": "owner",
            "merchant": merchant,
            "amount_cents": amount_cents,
            "next_expected_date": next_expected_date,
            "idempotency_key": str(uuid4()),
            **extra,
        },
        follow_redirects=False,
    )


def extract_hidden_token(html: str, *, action: str) -> str:
    """Pull ``expected_row_version`` out of the form whose ``action`` matches —
    i.e. the token as actually rendered into the page, not a value read
    straight from the DB. Returns "" when absent so the caller can assert the
    page emits a real token."""
    form = re.search(re.escape(f'action="{action}"') + r".*?</form>", html, re.DOTALL)
    if not form:
        return ""
    field = re.search(r'name="expected_row_version"\s+value="([^"]*)"', form.group(0))
    return field.group(1) if field else ""


def hero_block(html: str) -> str:
    match = re.search(r'<section[^>]+aria-label="固定支出概览".*?</section>', html, re.DOTALL)
    return match.group(0) if match else ""


def _seed_monthly_candidate(*, merchant: str = "ChatGPT Plus", amount_cents: int = 20000) -> datetime:
    last_seen = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for when in (
        datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        last_seen,
    ):
        insert_confirmed_expense(
            amount_cents=amount_cents,
            merchant=merchant,
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )
    return last_seen


def _definition_headers(client, identity, key=None):
    return {**negotiated_headers(client, identity.app_headers), "Idempotency-Key": key or str(uuid4())}


def _create_definition(client, identity, currency="JPY"):
    body = {"merchant": "原固定支出", "home_currency_code": currency, "baseline_amount_cents": 1200,
        "next_expected_date": "2026-09-05"}
    key = str(uuid4())
    response = client.post("/api/recurring/items", headers=_definition_headers(client, identity, key), json=body)
    assert response.status_code == 201, response.text
    return body, key, response.json()


def _definition_history(client, identity, public_id, **params):
    response = client.get(f"/api/recurring/items/{public_id}/history", headers=identity.app_headers, params=params)
    assert response.status_code == 200, response.text
    history = response.json()
    assert (history["ledger_id"], history["public_id"]) == ("owner", public_id)
    return history


def _definition_payment(client, identity, *, currency="CNY", amount=1200, month="2026-05"):
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": currency, "amount_cents": amount,
        "merchant": "真实付款", "category": "其他", "expense_time": f"{month}-05T12:00:00Z",
    })
    assert response.status_code == 200, response.text
    # Compare the same current-detail projection before and after planning.
    # The creation receipt intentionally omits detail-only OCR text lines.
    detail = client.get(f"/api/expenses/{response.json()['id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    return detail.json()


def _create_series(client: TestClient, identity) -> dict:
    response = client.post(
        "/api/recurring/items",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"home_currency_code": "CNY",
            "merchant": "房租",
            "baseline_amount_cents": 10_000,
            "next_expected_date": "2026-09-05",
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _occurrence_payment(client: TestClient, identity) -> dict:
    response = client.post(
        "/api/expenses/manual", headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 10_000, "merchant": "房租", "category": "餐饮",
            "expense_time": "2026-09-05T12:00:00Z", "note": "本期完整付款",
        },
    )
    assert response.status_code == 200, response.json()
    detail = client.get(f"/api/expenses/{response.json()['id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.text
    return detail.json()


def _form(body, action):
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, flags=re.S):
        if f'name="action" value="{action}"' in form:
            return {
                name: unescape(value)
                for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form)
            }
    raise AssertionError(f"real {action} form is missing")


def _choice_href(body, action):
    return next(unescape(href) for href in re.findall(r'href="([^"]+)"', body)
        if parse_qs(urlsplit(unescape(href)).query).get("command") == [action])


def _choose(client, body, action):
    page = client.get(_choice_href(body, action))
    assert page.status_code == 200, page.text
    return _form(page.text, action)


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
