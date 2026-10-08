"""Saved search conditions survive the real form, command and SQL read boundary.

The component database is isolated SQLite; public-session and migration contracts
remain in the existing PostgreSQL journeys.
"""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError, add_exception_handlers
from app.models import (
    Account,
    ApiIdempotencyKey,
    Expense,
    ExpenseOffsetFact,
    Ledger,
    LedgerMember,
    MerchantAlias,
    OcrFact,
    SavedView,
    Tag,
)
from app.routes import web_saved_views
from app.services.expense_service import _query
from app.services.idempotency import fingerprint_request
from app.services.saved_view_service import create_view, resolve_view_query, update_view


@pytest.fixture
def saved_search(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queries.sqlite'}")
    for model in (Account, Ledger, LedgerMember, Tag, SavedView, ApiIdempotencyKey):
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add(Account(id=1, display_name="Owner"))
        db.add(Ledger(ledger_id="owner", name="家庭", owner_account_id=1))
        db.add(LedgerMember(ledger_id="owner", account_id=1, role="owner"))
        db.commit()
    app = FastAPI()
    app.include_router(web_saved_views.router)
    add_exception_handlers(app)

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[web_saved_views.LocalOnly.dependency] = lambda: None
    monkeypatch.setattr(web_saved_views, "_list_ledger_options", lambda db: [
        SimpleNamespace(ledger_id="owner", role="owner")])
    monkeypatch.setattr(web_saved_views, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_saved_views, "resolve_web_actor_account_id", lambda *args: 1)
    monkeypatch.setattr(web_saved_views, "preserve_original_ledger_form", lambda *args, **kwargs: None)
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


def _fields(**changes):
    return {"ledger_id": "owner", "name": "每月日用", "month_mode": "fixed", "month": "2026-10",
        "filter": "", "tag_public_id": "", "home_currency_code": "JPY", "idempotency_key": "original-query",
        "query_text": "便利店", "category": "购物", **changes}


def test_native_form_reopens_the_saved_keyword_and_category_after_database_reopen(saved_search):
    client, engine = saved_search
    response = client.post("/web/saved-views", data=_fields(), follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(engine) as db:
        row = db.scalar(select(SavedView))
        query = resolve_view_query(db, tenant_id="owner", actor_account_id=1, public_id=row.public_id)
    assert query == {"ledger_id": "owner", "month": "2026-10", "home_currency_code": "JPY",
        "q": "便利店", "category": "购物"}


def test_original_saved_query_receipt_is_stable_after_a_later_edit(saved_search):
    client, engine = saved_search
    assert client.post("/web/saved-views", data=_fields(), follow_redirects=False).status_code == 303
    definition = {key: value for key, value in _fields().items() if key not in {"ledger_id", "idempotency_key"}}
    with Session(engine) as db:
        original = create_view(db, tenant_id="owner", actor_account_id=1,
            idempotency_key="original-query", **definition)
        changed = update_view(db, tenant_id="owner", actor_account_id=1,
            public_id=original.public_id, expected_row_version=original.row_version,
            **{**definition, "query_text": "超市", "category": "餐饮"})
        replay = create_view(db, tenant_id="owner", actor_account_id=1,
            idempotency_key="original-query", **definition)
        assert replay == original and replay.query_text == "便利店" and replay.category == "购物"
        assert changed.query_text == "超市" and changed.category == "餐饮"
        with pytest.raises(AppError) as mismatch:
            create_view(db, tenant_id="owner", actor_account_id=1,
                idempotency_key="original-query", **{**definition, "query_text": "超市"})
        assert mismatch.value.error == "idempotency_key_reused"
        current = resolve_view_query(db, tenant_id="owner", actor_account_id=1, public_id=original.public_id)
        assert current["q"] == "超市" and current["category"] == "餐饮"


def test_legacy_key_replays_the_original_receipt_without_new_empty_fields(saved_search):
    client, engine = saved_search
    fields = _fields(query_text="", category="")
    assert client.post("/web/saved-views", data=fields, follow_redirects=False).status_code == 303
    with Session(engine) as db:
        accepted = db.scalar(select(ApiIdempotencyKey))
        old_definition = {key: value for key, value in fields.items()
            if key not in {"ledger_id", "idempotency_key", "query_text", "category"}}
        old_definition.update(tag_public_id=None, name_key=fields["name"].casefold())
        accepted.request_fingerprint = fingerprint_request(operation="create_saved_view", target_id=None,
            body={**old_definition, "actor_account_id": 1}, expected_row_version=None)
        original = dict(accepted.response_body)
        assert "query_text" not in original and "category" not in original
        db.delete(db.scalar(select(SavedView)))
        db.commit()
    assert client.post("/web/saved-views", data=fields, follow_redirects=False).status_code == 303
    with Session(engine) as db:
        assert db.scalar(select(SavedView)) is None
        assert db.scalar(select(ApiIdempotencyKey)).response_body == original


def test_keyword_and_category_filter_before_paging_and_keep_matching_refund_events(saved_search, monkeypatch):
    _, engine = saved_search
    # Query-only seed tables. PostgreSQL constraints/fences are checked by the
    # real-db journey, not reimplemented in this short SELECT counterexample.
    metadata = MetaData()
    for model in (Expense, ExpenseOffsetFact, MerchantAlias, OcrFact):
        Table(model.__tablename__, metadata, *(Column(column.name,
            JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
    metadata.create_all(engine)
    monkeypatch.setattr(_query, "_confirmed_stream_entries", lambda db, *, tenant_id, locators: locators)
    with Session(engine) as db:
        for id_, merchant, category, ledger in (
            (1, "便利店原单", "购物", "owner"), (2, "便利店其它分类", "餐饮", "owner"),
            (3, "超市", "购物", "owner"), (4, "便利店外账本", "购物", "other"),
        ):
            db.add(Expense(id=id_, tenant_id=ledger, merchant=merchant, category=category,
                status="confirmed", amount_cents=1200, original_amount_minor=1200,
                accounting_date=date(2026, 10, 3)))
        db.flush()
        db.add(ExpenseOffsetFact(tenant_id="owner", expense_id=1, kind="refund", status="active",
            category="购物", accounting_date=date(2026, 10, 7), original_currency_code="CNY",
            original_amount_minor=300, home_currency_code="CNY", amount_cents=300,
            reason="实际退款", created_actor_account_id=1))
        db.commit()
        kwargs = {"tenant_id": "owner", "month": "2026-10", "category": "购物", "query_text": "便利店", "page_size": 1}
        first, total = _query.list_confirmed(db, page=1, **kwargs)
        second, total_again = _query.list_confirmed(db, page=2, **kwargs)
        assert total == total_again == 2
        assert [(row["root_expense_id"], row["entry_kind"], row["stream_amount_cents"])
            for row in first + second] == [(1, "offset", -300), (1, "expense", 1200)]
        db.add(Expense(tenant_id="owner", merchant="便利店后来入账", category="购物", status="confirmed",
            amount_cents=500, original_amount_minor=500, accounting_date=date(2026, 10, 8)))
        db.commit()
        current, total = _query.list_confirmed(db, **kwargs)
        assert total == 3 and current[0]["stream_amount_cents"] == 500
