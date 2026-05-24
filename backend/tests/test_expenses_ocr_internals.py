from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from api_contract_helpers import (
    upload_png,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import DuplicateIgnore, Expense
from app.services.duplicate_service import _remember_duplicate_ignore
from app.services.expense_service import confirm_expense, reject_expense, retry_expense_ocr
from app.services.ocr_service import MockOcrProvider, OcrResult, apply_ocr_result, retry_ocr
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT


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
