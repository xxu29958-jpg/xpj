"""v1.2 P0 — OCR facts append-only snapshot table contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Expense, OcrFact
from app.services.learning_service import (
    OcrFactDraft,
    ocr_facts_for_expense,
    record_ocr_fact,
)


def _make_expense(tenant_id: str) -> int:
    """Seed a minimal pending expense so the FK on ``ocr_facts.expense_id``
    is satisfiable. Tests that need the OCR-facts table need *an*
    expense to attach to; they don't care about its content."""

    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            source="pytest",
            raw_text="",
            status="pending",
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_record_ocr_fact_persists_full_snapshot(*, identity) -> None:
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        row = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                ocr_model="qwen2.5-vl-7b",
                raw_text="麦当劳 ¥38.50",
                parsed_amount_cents=3850,
                parsed_merchant="麦当劳",
                parsed_category="餐饮",
                parsed_expense_time=datetime(
                    2026, 5, 1, 12, 30, tzinfo=UTC
                ),
                parse_confidence=0.82,
            ),
        )
        db.commit()
        assert row.id is not None
        assert row.ocr_provider == "local_llm"
        assert row.parsed_amount_cents == 3850
        assert row.parsed_category == "餐饮"
        assert row.parse_confidence == pytest.approx(0.82)


def test_record_ocr_fact_allows_partial_results(*, identity) -> None:
    # Real OCR failures yield partial structured guesses — table must
    # accept raw_text alone.
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        row = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="empty",
                raw_text="blurry receipt",
            ),
        )
        db.commit()
        assert row.id is not None
        assert row.parsed_amount_cents is None
        assert row.parsed_merchant is None


def test_facts_returned_newest_first(*, identity) -> None:
    expense_id = _make_expense("owner")
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    with SessionLocal() as db:
        for offset_min in (0, 5, 15):
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=expense_id,
                    ocr_provider="local_llm",
                    raw_text=f"text-{offset_min}",
                ),
                now=base + timedelta(minutes=offset_min),
            )
        db.commit()
        facts = ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=expense_id
        )
        assert [f.raw_text for f in facts] == [
            "text-15",
            "text-5",
            "text-0",
        ]


def test_facts_are_tenant_isolated(*, identity) -> None:
    owner_expense_id = _make_expense("owner")
    tester_expense_id = _make_expense("tester_1")
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=owner_expense_id,
                ocr_provider="local_llm",
                raw_text="owner-text",
            ),
        )
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="tester_1",
                expense_id=tester_expense_id,
                ocr_provider="local_llm",
                raw_text="tester-text",
            ),
        )
        db.commit()

        owner_facts = ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=owner_expense_id
        )
        tester_facts = ocr_facts_for_expense(
            db, tenant_id="tester_1", expense_id=tester_expense_id
        )
        assert len(owner_facts) == 1
        assert len(tester_facts) == 1
        assert owner_facts[0].raw_text == "owner-text"
        assert tester_facts[0].raw_text == "tester-text"


def test_record_ocr_fact_refuses_cross_tenant_expense(*, identity) -> None:
    tester_expense_id = _make_expense("tester_1")
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="another tenant"):
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=tester_expense_id,
                    ocr_provider="local_llm",
                    raw_text="wrong tenant",
                ),
            )
        db.rollback()


def test_facts_table_is_append_only_no_unique_per_expense(*, identity) -> None:
    # Same expense, repeated runs (manual retry) must produce multiple
    # rows, never an upsert / replace.
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        first = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="run-1",
            ),
        )
        second = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="run-2",
            ),
        )
        db.commit()
        assert first.id != second.id
        count = (
            db.query(OcrFact)
            .filter(OcrFact.tenant_id == "owner")
            .filter(OcrFact.expense_id == expense_id)
            .count()
        )
        assert count == 2
