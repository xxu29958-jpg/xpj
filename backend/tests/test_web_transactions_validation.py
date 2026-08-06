"""S-TX validation, filter-cohort, and return-context Web contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from types import SimpleNamespace

import pytest
from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.services.tag_service import set_expense_tags
from app.services.web_stats_service import confirmed_by_day, source_breakdown
from app.tag_text import MAX_TAG_STORAGE_LENGTH
from tests._web_bulk_test_support import seed_pending_with_amount
from tests.test_web_transactions_backend import (
    _expense_payload,
    _foreign_expense,
    _seed_confirmed,
)


def test_confirmed_tag_filter_shares_list_total_calendar_and_source_cohort(
    web_client: TestClient,
) -> None:
    when = datetime(2026, 5, 4, 1, 0, tzinfo=UTC)
    _seed_confirmed(
        merchant="Family Store",
        when=when,
        amount_minor=1200,
        source="手动记账",
        tags="家庭",
    )
    _seed_confirmed(
        merchant="Personal Store",
        when=when.replace(day=5),
        amount_minor=9900,
        source="CSV导入",
        tags="个人",
    )

    response = web_client.get(
        "/web/confirmed?ledger_id=owner&month=2026-05&tag=家庭"
    )

    assert response.status_code == 200, response.text
    assert "Family Store" in response.text
    assert "Personal Store" not in response.text
    assert "<b>1</b> 笔" in response.text
    assert '<span class="int">12</span><span class="dec">.00</span>' in response.text
    with SessionLocal() as db:
        assert confirmed_by_day(db, "owner", "2026-05", tag="家庭") == [
            {
                "date": "2026-05-04",
                "amount_cents": 1200,
                "amount_yuan": 12.0,
                "count": 1,
            }
        ]
        assert source_breakdown(db, "owner", "2026-05", tag="家庭") == [
            {"label": "手动", "count": 1, "percent": 100}
        ]


def test_confirmed_rows_display_the_same_stat_time_used_by_month_queries(
    web_client: TestClient,
) -> None:
    _seed_confirmed(
        merchant="Confirmed Time Fallback",
        when=None,
        confirmed_at=datetime(2026, 8, 4, 1, 30, tzinfo=UTC),
        created_at=datetime(2026, 7, 1, 1, 30, tzinfo=UTC),
    )

    response = web_client.get("/web/confirmed?ledger_id=owner&month=2026-08")

    assert response.status_code == 200, response.text
    assert "Confirmed Time Fallback" in response.text
    assert "08 月 04 日" in response.text
    assert ">09:30<" in response.text
    assert "07 月 01 日" not in response.text


def test_tag_persistence_boundary_rejects_casefold_storage_overflow() -> None:
    expense_id = _seed_confirmed(
        merchant="Tag Boundary",
        when=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
    )
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        with pytest.raises(AppError) as caught:
            set_expense_tags(db, expense, "ß" * 33)
        db.rollback()
    assert caught.value.status_code == 422
    assert "64" in caught.value.message


def test_web_edit_rejects_nonpositive_occ_token_as_invalid_form(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "9.00", "Token Baseline", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": "-1",
            "original_currency": "CNY",
            "amount_yuan": "10.00",
            "merchant": "Should Not Save",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert "页面已过期" in response.text
    assert _expense_payload(web_client, expense_id, identity=identity) == before


def test_web_edit_rejects_hidden_currency_tampering_without_mutation(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _foreign_expense(web_client, identity=identity)
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(before["row_version"]),
            "original_currency": "JPY",
            "amount_yuan": "124",
            "merchant": "Tampered Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert "币种已冻结" in response.text
    assert 'aria-invalid="true"' in response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after == before


@pytest.mark.parametrize(
    ("field", "value", "error_fragment"),
    [
        ("merchant", "商" * 256, "商家最多 255"),
        ("category", "类" * 65, "分类最多 64"),
        ("tags", "标" * (MAX_TAG_STORAGE_LENGTH + 1), "单个标签最多 64"),
        ("tags", "ß" * (MAX_TAG_STORAGE_LENGTH // 2 + 1), "单个标签最多 64"),
    ],
)
def test_web_edit_rejects_overlong_transaction_fields_before_database_write(
    web_client: TestClient,
    field: str,
    value: str,
    error_fragment: str,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "9.00", "Length Baseline", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)
    form = {
        "ledger_id": "owner",
        "expected_row_version": str(before["row_version"]),
        "original_currency": before["original_currency_code"],
        "amount_yuan": "9.00",
        "merchant": "Length Baseline",
        "category": "餐饮",
        "note": "",
        "tags": "",
    }
    form[field] = value

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data=form,
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert error_fragment in response.text
    assert value in response.text
    assert 'aria-invalid="true"' in response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after == before


def test_web_edit_stale_write_returns_409_with_authoritative_values(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "8.00", "Before Conflict", identity=identity
    )
    stale = _expense_payload(web_client, expense_id, identity=identity)
    intervening = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "ledger_id": "owner",
            "amount_yuan": "8.00",
            "merchant": "Authoritative Merchant",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
    )
    assert intervening.status_code == 303, intervening.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(stale["row_version"]),
            "original_currency": stale["original_currency_code"],
            "amount_yuan": "8.00",
            "merchant": "Stale Overwrite",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 409, response.text
    assert "已在其它端被修改" in response.text
    assert "Authoritative Merchant" in response.text
    assert "Stale Overwrite" in response.text
    assert (
        f'name="expected_row_version" value="{stale["row_version"]}"'
        in response.text
    )
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["merchant"] == "Authoritative Merchant"


def test_web_search_renders_expense_amount_with_record_currency(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routes.web_search as web_search_route

    result = SimpleNamespace(
        group="confirmed",
        title="Historic JPY Cafe",
        subtitle="餐饮",
        href="/web/expenses/1/edit?ledger_id=owner",
        badge="已确认",
        amount_cents=1234,
        currency_code="JPY",
    )
    monkeypatch.setattr(
        web_search_route,
        "search_web",
        lambda *_args, **_kwargs: [
            SimpleNamespace(key="confirmed", title="已确认", results=[result])
        ],
    )

    response = web_client.get("/web/search?ledger_id=owner&q=Historic")

    assert response.status_code == 200, response.text
    assert "¥1,234" in response.text
    assert "JPY" in response.text
    assert "¥12.34" not in response.text


def test_web_search_rejects_long_query_in_place_without_silent_truncation(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routes.web_search as web_search_route

    called = False

    def _unexpected_search(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(web_search_route, "search_web", _unexpected_search)
    query = "家" * 81

    response = web_client.get(
        "/web/search", params={"ledger_id": "owner", "q": query}
    )

    assert response.status_code == 422, response.text
    assert "搜索词最多 80 个字符" in response.text
    assert query in response.text
    assert called is False


def _expense_edit_href(body: str, expense_id: int) -> str:
    match = re.search(
        rf'href="([^"]*/web/expenses/{expense_id}/edit[^"]*)"',
        body,
    )
    assert match is not None
    return unescape(match.group(1))


def _hidden_input(body: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', body)
    assert match is not None, name
    return unescape(match.group(1))


def test_search_edit_save_returns_to_validated_search_context(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "17.00", "Return Search Cafe", identity=identity
    )
    search = web_client.get("/web/search?ledger_id=owner&q=Return%20Search")
    assert search.status_code == 200, search.text
    edit_href = _expense_edit_href(search.text, expense_id)
    assert "return_to=search" in edit_href
    assert "return_query=Return+Search" in edit_href
    edit = web_client.get(edit_href)
    assert edit.status_code == 200, edit.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": _hidden_input(edit.text, "expected_row_version"),
            "idempotency_key": _hidden_input(edit.text, "idempotency_key"),
            "original_currency": _hidden_input(edit.text, "original_currency"),
            "amount_yuan": "17.00",
            "merchant": "Return Search Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
            "return_to": _hidden_input(edit.text, "return_to"),
            "return_query": _hidden_input(edit.text, "return_query"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/web/search?ledger_id=owner&q=Return+Search"

    returned_search = web_client.get(response.headers["location"])
    returned_edit = web_client.get(_expense_edit_href(returned_search.text, expense_id))
    assert returned_edit.status_code == 200, returned_edit.text

    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": _hidden_input(
                returned_edit.text, "expected_row_version"
            ),
            "idempotency_key": _hidden_input(returned_edit.text, "idempotency_key"),
            "save_before_confirm": "1",
            "original_currency": _hidden_input(
                returned_edit.text, "original_currency"
            ),
            "amount_yuan": "17.00",
            "merchant": "Return Search Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
            "return_to": _hidden_input(returned_edit.text, "return_to"),
            "return_query": _hidden_input(returned_edit.text, "return_query"),
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303, confirmed.text
    assert confirmed.headers["location"] == (
        "/web/search?ledger_id=owner&q=Return+Search"
    )
