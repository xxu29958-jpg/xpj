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


@pytest.mark.parametrize(
    "path",
    [
        "/api/stats/monthly?month=2026-13",
        "/api/stats/monthly?month=0000-05",
        "/api/stats/lifestyle?month=2026-5",
        "/api/expenses/confirmed?month=2026-13",
        "/api/expenses/export.csv?month=0000-05",
    ],
)
def test_month_filters_reject_invalid_month_labels(client: TestClient, path: str, *, identity) -> None:
    response = client.get(path, headers=identity.app_headers)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
