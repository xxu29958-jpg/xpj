"""Current OCR text read owner: latest nonempty fact, stable ties and tenant isolation.
The retired expense.raw_text mirror never supplies the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import (
    OcrFactDraft,
    read_ocr_text,
    record_ocr_fact,
)


def _make_expense(
    *, tenant_id: str = "owner", raw_text: str | None = ""
) -> int:
    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            source="pytest",
            raw_text=raw_text,
            status="pending",
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_current_text_breaks_same_timestamp_ties_by_append_order(
    *, identity,
) -> None:
    expense_id = _make_expense()
    timestamp = datetime(2026, 5, 1, tzinfo=UTC)
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="first-row",
            ),
            now=timestamp,
        )
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="second-row",
            ),
            now=timestamp,
        )
        db.commit()
        latest = read_ocr_text(
            db, tenant_id="owner", expense=db.get(Expense, expense_id)
        )
        assert latest is not None
        assert latest == "second-row"


def test_read_ocr_text_returns_latest_fact_text(*, identity) -> None:
    """The canonical happy path — a fact carries the OCR text and the
    helper returns it. The legacy column is left populated to make
    sure the assertion isn't accidentally satisfied by fallback (the
    column says ``from-expense-column``, the fact says ``from-facts``;
    a fallback would surface the column value)."""

    expense_id = _make_expense(raw_text="from-expense-column")
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
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
            expense=expense,
        )
        assert text == "from-facts"


def test_read_ocr_text_returns_none_when_no_fact_even_if_column_set(
    *, identity,
) -> None:
    """Post-step-4 contract: when no fact exists the helper returns
    ``None`` instead of reading ``expense.raw_text``. After the step-3
    backfill ran, this state should not occur in real deployments —
    every expense with non-empty ``raw_text`` got a backfill fact. The
    test pins the contract so a regression that re-introduces the
    fallback fails loudly."""

    expense_id = _make_expense(raw_text="from-expense-column")
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        # Sanity check: the column is non-empty so a fallback would
        # have returned it.
        assert expense.raw_text == "from-expense-column"
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense=expense,
        )
        assert text is None


def test_read_ocr_text_returns_none_when_only_fact_has_empty_raw_text(
    *, identity,
) -> None:
    """An OCR pass that produced structured fields but no raw_text
    (e.g. provider returned only parsed values) leaves the expense
    text-less from the helper's point of view. We do **not** revive
    the legacy column to fill the gap — that fallback was the entire
    thing step 4 dropped. Consumers must handle ``None``."""

    expense_id = _make_expense(raw_text="from-expense-column")
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
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
            expense=expense,
        )
        assert text is None


def test_read_ocr_text_returns_none_when_no_source(*, identity) -> None:
    expense_id = _make_expense(raw_text=None)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert (
            read_ocr_text(
                db,
                tenant_id="owner",
                expense=expense,
            )
            is None
        )
        expense.raw_text = ""
        assert (
            read_ocr_text(
                db,
                tenant_id="owner",
                expense=expense,
            )
            is None
        )


def test_read_ocr_text_walks_to_newest_fact(*, identity) -> None:
    """Append-only facts table: when multiple OCR runs exist, the
    helper picks the newest one, not just any one."""

    expense_id = _make_expense(raw_text="legacy-fallback")
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
        expense = db.get(Expense, expense_id)
        assert expense is not None
        text = read_ocr_text(
            db,
            tenant_id="owner",
            expense=expense,
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
        expense = db.get(Expense, expense_id)
        assert expense is not None
        # tester_1 calling with owner's expense object: the helper
        # rejects the tenant mismatch before either fact or legacy
        # fallback can return owner data.
        assert (
            read_ocr_text(
                db,
                tenant_id="tester_1",
                expense=expense,
            )
            is None
        )
