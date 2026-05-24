from __future__ import annotations

from datetime import UTC, datetime

from app.models import Expense
from app.services.ocr_service import MockOcrProvider, OcrResult, apply_ocr_result, retry_ocr


def test_apply_ocr_result_is_noop_for_terminal_expenses() -> None:
    expense = Expense(
        status="confirmed",
        amount_cents=1234,
        merchant="Stable Cafe",
        category="餐饮",
        raw_text="",
    )

    apply_ocr_result(
        expense,
        OcrResult(raw_text="Changed Cafe\n99.99", amount_cents=9999, merchant="Changed Cafe", confidence=None),
    )

    assert expense.amount_cents == 1234
    assert expense.merchant == "Stable Cafe"
    assert expense.raw_text == ""


def test_ocr_draft_field_aliases_are_canonicalized_when_applying_result() -> None:
    expense = Expense(
        status="pending",
        amount_cents=7200,
        merchant="Stable Cafe",
        category="其他",
        raw_text="",
        expense_time=datetime(2026, 5, 1, tzinfo=UTC),
        ocr_draft_fields='["original_amount", "original_currency", "spent_at"]',
    )

    apply_ocr_result(
        expense,
        OcrResult(
            raw_text="Changed Cafe\n19.00",
            amount_cents=1900,
            merchant="Changed Cafe",
            expense_time=datetime(2026, 5, 2, tzinfo=UTC),
            confidence=None,
        ),
    )

    assert expense.amount_cents == 1900
    assert expense.merchant == "Stable Cafe"
    assert expense.expense_time == datetime(2026, 5, 2, tzinfo=UTC)
    assert expense.ocr_draft_fields == '["amount_cents", "expense_time"]'


def test_mock_ocr_provider_populates_pending_draft() -> None:
    expense = Expense(status="pending", category="其他", raw_text="")
    retry_ocr(expense, MockOcrProvider())
    assert expense.amount_cents == 1851
    assert expense.merchant == "中国建设银行"
    assert expense.expense_time is not None
    assert expense.confidence is not None and expense.confidence >= 0.8
