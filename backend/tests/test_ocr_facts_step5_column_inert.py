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
column on every OCR pass. The mirror lets the Pydantic
``ExpenseResponse`` (``from_attributes=True``) keep surfacing
``raw_text`` to clients — the value matches what ``append_ocr_fact``
just wrote into ``ocr_facts``, so the mirror cannot diverge from the
canonical store. A future cleanup can swap the response layer to
``read_ocr_text`` and drop the column outright; today's contract is
"the column is a denormalised view, not a source of truth."
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Expense
from app.services.ocr_service import EmptyOcrProvider, MockOcrProvider
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
