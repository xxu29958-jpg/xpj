"""Unknown dates stay findable without masquerading as a creation timestamp."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request

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
    assert view["image_state"] == "unknown"
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
    from app.middleware import csrf
    from app.routes import web_common

    calls = []

    def list_rows(db, **query):
        calls.append(query)
        return [], 75

    monkeypatch.setattr(web_app, "list_confirmed", list_rows)
    monkeypatch.setattr(web_app, "_confirmed_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_app, "current_ledger_month",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cross-period task has no default month")))
    monkeypatch.setattr(web_app, "_sidebar_counts", lambda *args: (0, 0))
    monkeypatch.setattr(web_app, "list_ledger_category_options", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_common, "require_runtime_home_currency_code", lambda *args: "CNY")
    monkeypatch.setattr(web_common, "count_undated_expenses", lambda *args, **kwargs: 75)
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"controlled-date-review-signing")
    origin = {"return_to": "reports", "return_month": "2026-05", "return_home_currency_code": "JPY",
        "return_granularity": "week", "return_ranking_metric": "count", "return_merchant_category": "旅行"}
    query = dict(ledger_id="owner", filter="missing_accounting_date", **origin)
    request = Request({"type": "http", "method": "GET", "path": "/web/confirmed", "headers": [],
        "query_string": urlencode(query).encode(), "server": ("testserver", 80), "scheme": "http"})
    response = web_app._render_confirmed_page(request, object(),
        [SimpleNamespace(ledger_id="owner", name="家庭账本", role="viewer", is_default=True)], "owner",
        page=2, month="2026-05", tag="旅行", msg=None,
        filter="missing_accounting_date", home_currency_code="JPY")
    context = response.context
    assert (context["month"], context["home_currency_code"], context["total"], context["page"]) == ("", "JPY", 75, 2)
    assert calls[0]["month"] is None and calls[0]["missing_accounting_date"] is True
    assert calls[0]["tenant_id"] == "owner" and calls[0]["tag"] == "旅行"
    expected = "/web/reports?" + urlencode({"ledger_id": "owner", "month": "2026-05", "home_currency_code": "JPY",
        "granularity": "week", "ranking_metric": "count", "merchant_category": "旅行"})
    assert context.get("date_review_return_href") == expected
    body = response.body.decode()
    assert "返回原月份月报" in body and "返回数据体检" not in body
    assert parse_qs(context["pager_query"]) == {"ledger_id": ["owner"], "filter": ["missing_accounting_date"],
        "tag": ["旅行"], "home_currency_code": ["JPY"], **{key: [value] for key, value in origin.items()}}
    from app.routes._web_expense_return_context import return_href

    fields = {key: values[0] for key, values in parse_qs(context["confirmed_edit_query"]).items()}
    assert return_href(default_path="/web/confirmed", **fields) == expected
