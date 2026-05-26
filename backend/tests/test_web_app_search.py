"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import OcrFactDraft, record_ocr_fact


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试", *, identity) -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_search_finds_current_ledger_entities(web_client: TestClient, *, identity) -> None:
    pending_id = _seed_pending_with_amount(web_client, "9.00", "SearchCafe Pending", identity=identity)
    confirmed_id = _seed_pending_with_amount(web_client, "11.00", "SearchCafe Confirmed", identity=identity)
    confirmed = web_client.post(
        f"/web/expenses/{confirmed_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert confirmed.status_code in {303, 307}
    rule = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "SearchCafe",
            "category": "餐饮",
            "priority": "100",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert rule.status_code in {303, 307}
    goal = web_client.post(
        "/web/goals/create",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "name": "SearchGoal Groceries",
            "target_amount_yuan": "1000",
            "category": "餐饮",
        },
        follow_redirects=False,
    )
    assert goal.status_code in {303, 307}

    page = web_client.get("/web/search?ledger_id=owner&q=SearchCafe")
    assert page.status_code == 200
    assert f"/web/expenses/{pending_id}/edit?ledger_id=owner" in page.text
    assert f"/web/expenses/{confirmed_id}/edit?ledger_id=owner" in page.text
    assert "/web/rules?ledger_id=owner" in page.text

    goals = web_client.get("/web/search?ledger_id=owner&q=SearchGoal")
    assert goals.status_code == 200
    assert "SearchGoal Groceries" in goals.text
    assert "/web/goals?ledger_id=owner&amp;month=2026-05" in goals.text

    other_ledger = web_client.get("/web/search?ledger_id=tester_1&q=SearchCafe")
    assert other_ledger.status_code == 200
    assert "SearchCafe Pending" not in other_ledger.text
    assert "SearchCafe Confirmed" not in other_ledger.text


def test_web_search_uses_enabled_merchant_aliases(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_with_amount(web_client, "19.00", "STARBUCKS 国贸店", identity=identity)
    alias = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "ledger_id": "owner",
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
        },
        follow_redirects=False,
    )
    assert alias.status_code in {303, 307}

    page = web_client.get("/web/search?ledger_id=owner&q=星巴克")
    assert page.status_code == 200
    assert f"/web/expenses/{expense_id}/edit?ledger_id=owner" in page.text


def test_web_search_matches_ocr_facts_raw_text(
    web_client: TestClient, *, identity,
) -> None:
    """v1.2 OCR single-source migration (step 4): the raw_text needle
    is now resolved against ``ocr_facts``, not ``expenses.raw_text``.
    An expense whose OCR fact carries the search term must be found
    even when the expense's own ``raw_text`` column is empty."""

    expense_id = _seed_pending_with_amount(
        web_client, "12.34", "FactSearch Cafe", identity=identity,
    )
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert expense is not None
        # Strip the column so the only place "UniqueOcrToken" can live
        # is the fact row we're about to write.
        expense.raw_text = ""
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="receipt body with UniqueOcrToken inside",
            ),
        )
        db.commit()

    page = web_client.get("/web/search?ledger_id=owner&q=UniqueOcrToken")
    assert page.status_code == 200
    assert f"/web/expenses/{expense_id}/edit?ledger_id=owner" in page.text


def test_web_search_ignores_legacy_expense_raw_text_column(
    web_client: TestClient, *, identity,
) -> None:
    """The legacy ``expenses.raw_text`` column is no longer a search
    surface — the step-3 backfill mirrored every populated row into
    ``ocr_facts``, so a raw needle that lives **only** in the column
    (and not in any fact) is by definition a row the backfill missed.
    We don't want search to keep papering over that gap."""

    expense_id = _seed_pending_with_amount(
        web_client, "21.00", "ColumnOnly Cafe", identity=identity,
    )
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert expense is not None
        # Plant the needle in the deprecated column with no matching
        # fact. (The upload path's mock OCR would create a fact with
        # different content; clearing all facts for this expense keeps
        # the test scoped to the column-only case.)
        expense.raw_text = "needle ColumnOnlyToken needle"
        db.execute(
            text("DELETE FROM ocr_facts WHERE expense_id = :id"),
            {"id": expense_id},
        )
        db.commit()

    page = web_client.get("/web/search?ledger_id=owner&q=ColumnOnlyToken")
    assert page.status_code == 200
    assert f"/web/expenses/{expense_id}/edit" not in page.text


def test_web_search_uses_category_alias_terms(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_with_amount(web_client, "19.00", "Legacy Category Cafe", identity=identity)
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert expense is not None
        expense.category = "吃饭"
        db.commit()

    page = web_client.get("/web/search?ledger_id=owner&q=餐饮")
    assert page.status_code == 200
    assert f"/web/expenses/{expense_id}/edit?ledger_id=owner" in page.text
