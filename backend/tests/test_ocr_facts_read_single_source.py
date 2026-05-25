"""v1.2 follow-up — OCR single-source read helpers.

Step 1 of the migration off ``expenses.raw_text``. Two helpers tested
here:

* ``latest_ocr_fact_for_expense`` — the indexed lookup that returns
  the newest ``ocr_facts`` row for a given expense (or ``None``).
* ``read_ocr_text`` — wrapper that prefers the fact's ``raw_text``
  and falls back to a caller-supplied ``legacy_raw_text`` (i.e.
  ``expense.raw_text``) so consumers can be migrated gradually
  without breaking expenses that pre-date the new table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import Expense, OcrFact
from app.services.learning_service import (
    OcrFactDraft,
    latest_ocr_fact_for_expense,
    read_ocr_text,
    record_ocr_fact,
)


def _make_expense(*, tenant_id: str = "owner") -> int:
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


def test_latest_returns_newest_row(*, identity) -> None:
    expense_id = _make_expense()
    base = datetime(2026, 5, 1, tzinfo=UTC)
    with SessionLocal() as db:
        # Two facts, three minutes apart.
        for offset_min in (0, 5):
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=expense_id,
                    ocr_provider="local_llm",
                    raw_text=f"snapshot-{offset_min}",
                ),
                now=base + timedelta(minutes=offset_min),
            )
        db.commit()
        latest = latest_ocr_fact_for_expense(
            db, tenant_id="owner", expense_id=expense_id
        )
        assert latest is not None
        assert latest.raw_text == "snapshot-5"


def test_latest_returns_none_when_no_facts(*, identity) -> None:
    expense_id = _make_expense()
    with SessionLocal() as db:
        assert (
            latest_ocr_fact_for_expense(
                db, tenant_id="owner", expense_id=expense_id
            )
            is None
        )


def test_latest_is_tenant_scoped(*, identity) -> None:
    owner_expense = _make_expense(tenant_id="owner")
    tester_expense = _make_expense(tenant_id="tester_1")
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=owner_expense,
                ocr_provider="local_llm",
                raw_text="owner-side",
            ),
        )
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="tester_1",
                expense_id=tester_expense,
                ocr_provider="local_llm",
                raw_text="tester-side",
            ),
        )
        db.commit()

        # Cross-tenant lookup using owner's expense id but tester
        # tenant returns None (tenant filter blocks it).
        assert (
            latest_ocr_fact_for_expense(
                db, tenant_id="tester_1", expense_id=owner_expense
            )
            is None
        )
        # Each tenant sees its own.
        assert (
            latest_ocr_fact_for_expense(
                db, tenant_id="owner", expense_id=owner_expense
            ).raw_text
            == "owner-side"
        )
        assert (
            latest_ocr_fact_for_expense(
                db, tenant_id="tester_1", expense_id=tester_expense
            ).raw_text
            == "tester-side"
        )


def test_read_ocr_text_prefers_fact_over_legacy(*, identity) -> None:
    expense_id = _make_expense()
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="from-facts",
            ),
        )
        db.commit()
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense_id=expense_id,
            legacy_raw_text="from-expense-column",
        )
        assert text == "from-facts"


def test_read_ocr_text_falls_back_when_no_fact(*, identity) -> None:
    expense_id = _make_expense()
    with SessionLocal() as db:
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense_id=expense_id,
            legacy_raw_text="from-expense-column",
        )
        assert text == "from-expense-column"


def test_read_ocr_text_falls_back_when_fact_has_empty_raw_text(
    *, identity,
) -> None:
    """An OCR pass that produced structured fields but no raw_text
    (e.g. provider returned only parsed values) should still let the
    legacy column win, otherwise the consumer gets nothing."""

    expense_id = _make_expense()
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text=None,
                parsed_amount_cents=4500,
            ),
        )
        db.commit()
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense_id=expense_id,
            legacy_raw_text="from-expense-column",
        )
        assert text == "from-expense-column"


def test_read_ocr_text_returns_none_when_no_source(*, identity) -> None:
    expense_id = _make_expense()
    with SessionLocal() as db:
        assert (
            read_ocr_text(
                db,
                tenant_id="owner",
                expense_id=expense_id,
                legacy_raw_text=None,
            )
            is None
        )
        assert (
            read_ocr_text(
                db,
                tenant_id="owner",
                expense_id=expense_id,
                legacy_raw_text="",
            )
            is None
        )


def test_read_ocr_text_walks_to_newest_fact(*, identity) -> None:
    """Append-only facts table: when multiple OCR runs exist, the
    helper picks the newest one, not just any one."""

    expense_id = _make_expense()
    base = datetime(2026, 5, 1, tzinfo=UTC)
    with SessionLocal() as db:
        for offset_min, text in [
            (0, "first-run"),
            (10, "second-run"),
            (20, "third-run"),
        ]:
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=expense_id,
                    ocr_provider="local_llm",
                    raw_text=text,
                ),
                now=base + timedelta(minutes=offset_min),
            )
        db.commit()
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense_id=expense_id,
            legacy_raw_text="legacy-fallback",
        )
        assert text == "third-run"


def test_read_ocr_text_does_not_revive_after_tenant_mismatch(
    *, identity,
) -> None:
    """A consumer that accidentally passes the wrong tenant must not
    inherit another tenant's OCR text via fallback."""

    expense_id = _make_expense(tenant_id="owner")
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="owner-only",
            ),
        )
        db.commit()
        # tester_1 calling with owner's expense_id and a NULL fallback:
        # the fact lookup misses (tenant filter), and there's no
        # fallback to read → None.
        assert (
            read_ocr_text(
                db,
                tenant_id="tester_1",
                expense_id=expense_id,
                legacy_raw_text=None,
            )
            is None
        )
