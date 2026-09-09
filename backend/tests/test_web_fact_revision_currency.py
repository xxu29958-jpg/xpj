"""Fact history keeps its own money basis after the installation default changes."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.models import Expense
from app.routes import _web_expense_fact as fact
from app.routes import _web_expense_helpers as helpers
from app.schemas import ExpenseRevisionListResponse, ExpenseRevisionResponse


def _snapshot(home, amount, original, original_amount, split):
    return {
        "home_currency_code": home, "amount_cents": amount,
        "original_currency_code": original, "original_amount_minor": original_amount,
        "items": [{"name": "车票", "unit_price_cents": amount, "amount_cents": amount}],
        "splits": [{"member_id": 7, "amount_cents": split}],
    }


@pytest.fixture()
def fact_context(monkeypatch):
    now = datetime(2026, 9, 1, 4, tzinfo=UTC)
    expense = Expense(id=41, tenant_id="owner", home_currency_code="CNY", amount_cents=60,
        original_currency_code="JPY", original_amount_minor=12, exchange_rate_to_cny=Decimal("0.05"),
        exchange_rate_source="manual", exchange_rate_date=now.date(), fx_status="ready",
        merchant="车票", category="交通", status="confirmed", fact_revision=2, row_version=2,
        expense_time=now, created_at=now, confirmed_at=now, updated_at=now, duplicate_status="none")
    monkeypatch.setattr(helpers, "get_expense", lambda *_a: expense)
    monkeypatch.setattr(fact, "get_expense", lambda *_a: expense)
    monkeypatch.setattr(helpers, "_base_ctx", lambda *_a, **_k: {
        "home_currency_code": "JPY", "can_write": True})
    monkeypatch.setattr(helpers, "manual_draft_ack", lambda *_a: None)
    monkeypatch.setattr(helpers, "_web_item_rows", lambda *_a, **_k: {})
    monkeypatch.setattr(helpers, "web_split_rows", lambda *_a, **_k: {})
    monkeypatch.setattr(helpers, "web_split_members", lambda *_a: [])
    monkeypatch.setattr(helpers, "list_ledger_category_options", lambda *_a, **_k: [])
    monkeypatch.setattr(fact, "build_split_invite_context", lambda *_a, **_k: {})
    monkeypatch.setattr(fact, "expense_offset_fact_view", lambda *_a: {})
    monkeypatch.setattr(fact.invitation_members, "list_members", lambda *_a, **_k: [
        SimpleNamespace(member_id=7, account_name="我")])

    def read(before, after):
        revision = ExpenseRevisionResponse(public_id="revision-2", revision_number=2,
            change_kind="correction", reason="实际支付日元", created_at=now, before=before, after=after,
            changed_fields=["amount_cents", "original_currency_code", "original_amount_minor", "items", "splits"])
        monkeypatch.setattr(fact, "list_expense_revisions", lambda *_a, **_k: ExpenseRevisionListResponse(
            items=[revision], page=1, page_size=50, total=1, snapshot_revision=2))
        request = Request({"type": "http", "method": "GET", "headers": [],
            "path": "/web/expenses/41/edit", "query_string": b""})
        return fact.web_fact_context(object(), request, [], "owner", 41)

    return read


def test_actual_fact_context_uses_revision_currency_for_money_items_and_splits(fact_context):
    context = fact_context(_snapshot("CNY", 1200, "CNY", 1200, 1200),
        _snapshot("CNY", 60, "JPY", 12, 50))
    assert context["home_currency_code"] == "JPY"  # Only the surrounding shell's current default.
    assert context["expense"]["home_currency_code"] == "CNY"
    assert context["expense"]["amount_label"] == "¥12"
    changes = context["fact_timeline"][0]["changes"]
    money = next(change for change in changes if change["label"] == "入账金额")
    assert (money["before"], money["after"]) == ("¥12.00", "¥0.60")
    original = next(change for change in changes if change["label"] == "原币金额")
    assert (original["before"], original["after"]) == ("¥12.00", "¥12")
    items = next(change for change in changes if change["label"] == "小票明细")["details"]
    assert items["before_rows"][0]["facts"] == ["单价 ¥12.00", "金额 ¥12.00"]
    assert items["after_rows"][0]["facts"] == ["单价 ¥0.60", "金额 ¥0.60"]
    splits = next(change for change in changes if change["label"] == "家庭拆账")
    assert (splits["before"], splits["after"]) == ("已分完", "还差 ¥0.10 未分配")
    assert splits["details"]["before_rows"][0]["facts"] == ["¥12.00"]
    assert splits["details"]["after_rows"][0]["facts"] == ["¥0.50"]


@pytest.mark.parametrize("code", [None, "", "XYZ"])
def test_unknown_revision_currency_never_borrows_current_or_record_currency(fact_context, code):
    before = _snapshot(code, 1200, code, 1200, 1000)
    if code is None:
        before.pop("home_currency_code")
        before.pop("original_currency_code")
    context = fact_context(before, _snapshot("CNY", 60, "JPY", 12, 50))
    changes = context["fact_timeline"][0]["changes"]
    money = next(change for change in changes if change["label"] == "入账金额")
    assert money["before"] == "1,200 最小单位（币种待核对）"
    assert money["after"] == "¥0.60"
    items = next(change for change in changes if change["label"] == "小票明细")["details"]
    assert items["before_rows"][0]["facts"] == [
        "单价 1,200 最小单位（币种待核对）", "金额 1,200 最小单位（币种待核对）"]
    split = next(change for change in changes if change["label"] == "家庭拆账")
    assert split["before"] == "还差 200 最小单位（币种待核对） 未分配"
    assert split["details"]["before_rows"][0]["facts"] == ["1,000 最小单位（币种待核对）"]


def test_each_revision_side_uses_its_own_explicit_carrier(fact_context):
    context = fact_context(_snapshot("CNY", 1200, "CNY", 1200, 1000),
        _snapshot("JPY", 12, "JPY", 12, 10))
    changes = context["fact_timeline"][0]["changes"]
    money = next(change for change in changes if change["label"] == "入账金额")
    assert (money["before"], money["after"]) == ("¥12.00", "¥12")
    splits = next(change for change in changes if change["label"] == "家庭拆账")
    assert splits["details"]["after_rows"][0]["facts"] == ["¥10"]
