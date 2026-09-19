"""Unknown dates stay findable without masquerading as a creation timestamp."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs

from app.models import Expense
from app.routes import web_app
from app.routes._web_expense_return_context import return_context_params
from app.routes._web_money_views import _expense_view
from app.schemas import ExpenseResponse
from app.schemas._accounting_time import AccountingTimeSnapshot
from app.services.web_search_service import _expense_subtitle


def _root(snapshot):
    return ExpenseResponse.model_construct(id=41, public_id="original", amount_cents=1234,
        original_currency_code="CNY", original_amount_minor=1234, home_currency="CNY",
        category="餐饮", source="手动记账", merchant="原账单", note=None, status="confirmed",
        image_path=None, image_deleted_at=None, duplicate_status="none",
        expense_time=snapshot.instant_utc, created_at=datetime(2026, 6, 1, tzinfo=UTC),
        accounting_time=snapshot)


def test_unknown_root_remains_a_money_row_without_a_synthetic_day():
    root = _root(AccountingTimeSnapshot(precision="unknown", calendar_revision=1,
        accounting_date=None, basis="legacy_unknown"))
    entry = SimpleNamespace(root=root, entry_kind="expense", offset=None, stream_date=None,
        stream_sort_id=41, stream_amount_cents=1234, lineage_status="confirmed")
    rows = web_app._confirmed_items([entry], "CNY", db=object(), ledger_id="owner")
    assert len(rows) == 1 and rows[0]["id"] == 41
    assert rows[0]["stream_date"] == "" and rows[0]["projected_amount_cents"] == 1234


def test_typed_response_keeps_accounting_day_and_original_zone_in_the_web_view():
    snapshot = AccountingTimeSnapshot(precision="instant", calendar_revision=1,
        instant_utc=datetime(2026, 5, 1, tzinfo=UTC), user_local_date=date(2026, 5, 1),
        accounting_date=date(2026, 5, 1), source_timezone="Asia/Shanghai",
        source_utc_offset_seconds=28800, basis="instant_calendar")
    view = _expense_view(_root(snapshot), presentation_currency_code="CNY")
    assert view["accounting_date"] == "2026-05-01"
    assert "08:00:00+08:00" in view["expense_time"]


def test_unknown_date_search_result_does_not_present_created_at_as_a_purchase_day():
    expense = Expense(category="餐饮", source="手动记账", status="confirmed",
        expense_time=None, accounting_date=None, created_at=datetime(2026, 6, 1, tzinfo=UTC))
    label = _expense_subtitle(expense)
    assert "账务日期待核对" in label
    assert "2026-06-01" not in label


def test_undated_correction_returns_to_the_same_cross_period_task():
    params = return_context_params("confirmed", return_filter="missing_accounting_date",
        return_month="2026-05", return_tag="旅行", return_page="2")
    assert params == {"filter": "missing_accounting_date", "tag": "旅行", "page": "2"}


def test_undated_task_ignores_stale_month_and_retains_filter_when_paging(monkeypatch):
    calls = []

    def list_rows(db, **query):
        calls.append(query)
        return [], 75

    monkeypatch.setattr(web_app, "list_confirmed", list_rows)
    monkeypatch.setattr(web_app, "_confirmed_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "current_ledger_month",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cross-period task has no default month")))
    month, home, _, total, _, pager, page = web_app._confirmed_page_rows(object(),
        selected_id="owner", page=2, month="2026-05", tag="旅行",
        filter="missing_accounting_date", home_currency_code="JPY")
    assert (month, home, total, page) == ("", "JPY", 75, 2)
    assert calls[0]["month"] is None and calls[0]["missing_accounting_date"] is True
    assert calls[0]["tenant_id"] == "owner" and calls[0]["tag"] == "旅行"
    assert parse_qs(pager) == {"ledger_id": ["owner"], "filter": ["missing_accounting_date"],
        "tag": ["旅行"], "home_currency_code": ["JPY"]}
