"""Shared local Web client and one actual budget-save setup."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _save_budget(web_client: TestClient, *, total: str = "1000.00") -> None:
    response = web_client.post(
        "/web/budgets/save",
        data={"home_currency_code": "CNY", "expected_row_version": "null", "idempotency_key": str(uuid4()),
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": total,
            "rollover_amount_yuan": "50.00",
            "non_monthly_amount_yuan": "120.00",
            "excluded_category": ["医疗"],
            "excluded_categories": "报销",
            "category_budget_category": ["餐饮", "交通"],
            "category_budget_amount_yuan": ["100.00", "50.00"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
