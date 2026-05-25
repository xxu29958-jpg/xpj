"""v1.2 OCR single-source migration — step 5: the legacy column is
demoted to a denormalised API mirror.

After step 5 no **business-logic** code reads ``expenses.raw_text``:

* The legacy "did OCR happen" gate for draft fields keys off
  ``expense.confidence`` only — the previous ``raw_text`` AND in the
  gate is gone.
* ``EmptyOcrProvider`` and ``MockOcrProvider`` no longer read the
  column as an input. The empty provider returns an empty result;
  the mock returns its canned receipt regardless of column state.

``apply_ocr_result`` still mirrors ``merged.raw_text`` into the
column, but **only when the OCR pass produced text**. An empty pass
(e.g. ``EmptyOcrProvider`` on an unconfigured system, or a provider
error that surfaced as a hollow result) leaves the mirror untouched
so the response surface keeps tracking the most recent meaningful
OCR — same logical view that ``read_ocr_text`` returns by walking
back past empty facts. The mirror still cannot show text the facts
table doesn't have: every non-empty mirror write is paired with an
``append_ocr_fact`` call carrying the same ``merged.raw_text``.

A future cleanup can swap the response layer to ``read_ocr_text``
and drop the column outright; today's contract is "the column is a
denormalised view of the latest non-empty OCR, not a source of
truth."
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import (
    OcrFactDraft,
    read_ocr_text,
    record_ocr_fact,
)
from app.services.ocr_service import (
    EmptyOcrProvider,
    MockOcrProvider,
    OcrResult,
    apply_ocr_result,
)
from app.services.ocr_service._draft_fields import (
    _legacy_pending_ocr_draft_fields,
)


def test_legacy_draft_gate_uses_confidence_only() -> None:
    """The legacy "did OCR happen" gate keyed off
    ``raw_text or "" AND confidence is None`` before step 5. With the
    column no longer touched by the OCR pipeline, the gate uses
    confidence on its own — an expense whose column is empty but
    whose confidence is set still surfaces inferred draft fields."""

    now = datetime(2026, 5, 1, tzinfo=UTC)
    expense = Expense(
        status="pending",
        amount_cents=1900,
        merchant="Cafe",
        category="餐饮",
        # Empty column — the old gate would have returned set() here.
        raw_text="",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    inferred = _legacy_pending_ocr_draft_fields(expense)
    # ``amount_cents``, ``merchant``, ``category`` are populated and
    # category is not "其他", so all three are inferred.
    assert "amount_cents" in inferred
    assert "merchant" in inferred
    assert "category" in inferred


def test_legacy_draft_gate_still_skips_when_confidence_missing() -> None:
    """Confidence is the only signal now; without it, no inference."""

    now = datetime(2026, 5, 1, tzinfo=UTC)
    expense = Expense(
        status="pending",
        amount_cents=1900,
        merchant="Cafe",
        category="餐饮",
        raw_text="has text but never OCR'd",
        confidence=None,
        created_at=now,
        updated_at=now,
    )
    assert _legacy_pending_ocr_draft_fields(expense) == set()


def test_empty_ocr_provider_returns_empty_raw_text() -> None:
    """EmptyOcrProvider is the "no OCR configured" sentinel. It used
    to surface ``expense.raw_text`` as its result — that was a way
    for the deprecated column to feed back into the OCR pipeline as
    if it were a fresh pass. Step 5 cuts the read."""

    expense = Expense(
        status="pending",
        category="其他",
        raw_text="legacy column body that should not surface",
        confidence=0.7,
    )
    result = EmptyOcrProvider().extract(expense)
    assert result.raw_text == ""
    # Confidence is still surfaced — it lives on the expense, not in
    # the ``raw_text`` deprecation tree.
    assert result.confidence == 0.7


def test_read_ocr_text_walks_back_past_empty_facts(*, identity) -> None:
    """Regression for a P1 found in PR #129 review: an empty OCR pass
    (e.g. ``EmptyOcrProvider`` on a system with no OCR configured)
    used to clobber the canonical read. ``apply_ocr_result`` +
    ``append_ocr_fact`` would write a new empty fact, and
    ``read_ocr_text``'s "latest fact only" rule would then return
    ``None`` — losing the previously-recorded ``manual_text`` /
    ``local_llm`` text.

    The fix: ``read_ocr_text`` walks back past empty facts to the
    newest one that actually carries text. The append-only ledger
    still records the empty attempt; the read just skips it."""

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            source="pytest",
            raw_text="",
            status="pending",
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id

        # First: a meaningful OCR pass lands a fact with real text.
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="manual_text",
                raw_text="actual receipt body",
            ),
        )
        # Then: an empty retry (EmptyOcrProvider) lands an empty fact
        # on top. Without the fix, this row's empty raw_text would
        # become the "latest" answer.
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="empty",
                raw_text="",
            ),
        )
        db.commit()

        # The canonical answer is still "actual receipt body".
        expense = db.get(Expense, expense_id)
        assert read_ocr_text(db, tenant_id="owner", expense=expense) == (
            "actual receipt body"
        )


def test_read_ocr_text_walks_back_past_null_raw_text_facts(
    *, identity,
) -> None:
    """Same regression path, but the empty fact has ``raw_text=None``
    (provider returned only parsed fields). The walk-back must skip
    those too — otherwise a structured-fields-only OCR pass would
    hide previous meaningful text."""

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            source="pytest",
            raw_text="",
            status="pending",
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id

        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="manual_text",
                raw_text="real text from manual recognition",
            ),
        )
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

        expense = db.get(Expense, expense_id)
        assert read_ocr_text(db, tenant_id="owner", expense=expense) == (
            "real text from manual recognition"
        )


def test_apply_ocr_result_does_not_clobber_mirror_with_empty_text() -> None:
    """``apply_ocr_result`` mirrors ``merged.raw_text`` into the column
    so the API response surface keeps showing recognised text. An
    empty result must **not** wipe the mirror — otherwise an empty
    retry would clear the column even when previous OCR text exists,
    desyncing the response from what ``read_ocr_text`` (which walks
    back) returns."""

    expense = Expense(
        status="pending",
        category="其他",
        raw_text="previously mirrored OCR text",
        confidence=0.85,
    )
    apply_ocr_result(
        expense,
        OcrResult(raw_text="", confidence=None),
    )
    assert expense.raw_text == "previously mirrored OCR text"


def test_apply_ocr_result_still_mirrors_when_text_is_present() -> None:
    """The mirror behaviour for non-empty results is unchanged — a
    fresh OCR pass with text still updates ``expense.raw_text``."""

    expense = Expense(status="pending", category="其他", raw_text="old")
    apply_ocr_result(
        expense,
        OcrResult(raw_text="brand new OCR body", confidence=0.9),
    )
    assert expense.raw_text == "brand new OCR body"


def test_mock_ocr_provider_uses_canned_text_regardless_of_column() -> None:
    """MockOcrProvider's previous ``expense.raw_text or <canned>``
    branch let tests smuggle real receipt text in through the
    deprecated column. After step 5 the mock always returns the
    canned receipt — behaviour is independent of any historical
    column value."""

    canned_marker = "中国建设银行"

    blank_expense = Expense(status="pending", category="其他", raw_text="")
    blank_result = MockOcrProvider().extract(blank_expense)
    assert canned_marker in blank_result.raw_text

    populated_expense = Expense(
        status="pending",
        category="其他",
        raw_text="some other receipt text 真的不该出现",
    )
    populated_result = MockOcrProvider().extract(populated_expense)
    # Identical result — the column did not change the output.
    assert populated_result.raw_text == blank_result.raw_text
    assert "真的不该出现" not in populated_result.raw_text
