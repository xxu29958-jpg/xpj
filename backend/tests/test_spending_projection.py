"""The shared reader and page adapter retain the same confirmed stream facts."""

from datetime import UTC, date, datetime
from decimal import Decimal

from test_stats_currency_projection import StatsRows, entry

from app.models import Expense, ExpenseOffsetFact
from app.schemas import ExpenseResponse
from app.services import money_projection_service as money
from app.services.expense_service._query import _stream_entry
from app.services.spending_projection_service import entry_gaps, project_confirmed_items, read_projected_entries


def page_item(*, kind="expense", id=1, amount=10000, stream_amount=10000, currency="CNY", day=date(2026, 9, 9)):
    root = Expense(id=1, amount_cents=amount, home_currency_code="CNY", original_currency_code="CNY",
        original_amount_minor=10000, category="餐饮", merchant="root shop")
    response = ExpenseResponse.model_construct(id=1, amount_cents=amount, home_currency=root.home_currency,
        category=root.category, merchant=root.merchant)
    offset = ExpenseOffsetFact(id=id, public_id=f"offset-{id}", kind="refund", amount_cents=abs(stream_amount),
        original_amount_minor=abs(stream_amount), original_currency_code=currency,
        home_currency_code=currency, category="交通") if kind == "offset" else None
    return _stream_entry(root, response, [offset] if offset else [], offset=offset,
        stream_date=day, stream_sort_id=id, stream_sort_time=datetime.combine(day, datetime.min.time(), tzinfo=UTC))


def test_original_page_order_root_offset_identity_and_own_currency_are_not_reloaded(monkeypatch):
    monkeypatch.setattr(money, "resolve_payload_rate", lambda *a, **kw: (Decimal("20"), None, None, None))
    root = page_item()
    offset = page_item(kind="offset", id=1, stream_amount=-300, currency="JPY", day=date(2026, 9, 8))
    values = project_confirmed_items(None, tenant_id="owner", home="JPY", items=[offset, root])
    assert [(value.entry_kind, value.entry_id, value.root_expense_id) for value in values] == [("offset", 1, 1), ("expense", 1, 1)]
    assert [(value.amount_cents, value.home_currency_code, value.category) for value in values] == [(-300, "JPY", "交通"), (2000, "CNY", "餐饮")]
    assert [value.stream_date for value in values] == [date(2026, 9, 8), date(2026, 9, 9)]
    assert (root.root.amount_cents, root.root.home_currency, offset.stream_amount_cents) == (10000, "CNY", -300)


def test_unknown_original_amount_is_not_the_stream_serializer_zero_or_a_fake_fx_gap(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An unknown amount cannot be repaired by inventing an exchange-rate lookup")

    monkeypatch.setattr(money, "resolve_payload_rate", forbidden)
    item = page_item(amount=None, stream_amount=0)
    projected = project_confirmed_items(None, tenant_id="owner", home="JPY", items=[item])
    assert projected[0].amount_cents is None
    assert entry_gaps(projected) == ()


def test_shared_read_retains_tenant_root_tags_soft_deletes_and_timezone_bounds():
    db = StatsRows([entry(1000)])
    start, end = datetime(2026, 8, 31, 16, tzinfo=UTC), datetime(2026, 9, 30, 16, tzinfo=UTC)
    read_projected_entries(db, tenant_id="target-ledger", ranges=[(start, end)], timezone_name="Asia/Shanghai", home="JPY", tag="旅行")
    statement = db.statements[0]
    sql = str(statement)
    params = statement.compile().params
    assert "expense_offset_facts.tenant_id" in sql
    assert "expense_tags.tenant_id" in sql and "tags.deleted_at IS NULL" in sql
    assert date(2026, 9, 1) in params.values() and date(2026, 10, 1) in params.values()
    assert "target-ledger" in params.values() and "旅行" in params.values()
