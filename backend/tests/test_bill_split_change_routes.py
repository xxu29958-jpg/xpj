"""The real protocol dependency refuses a split command before its writer."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_writer_context
from app.database import get_db
from app.errors import add_exception_handlers
from app.routes import debt_split_changes


def test_protocol_refusal_precedes_money_writer(monkeypatch):
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(debt_split_changes.router)
    app.dependency_overrides[get_current_writer_context] = lambda: SimpleNamespace(
        tenant_id="unused", account_id=1, role="owner")
    app.dependency_overrides[get_db] = lambda: None

    def unexpected_write(*args, **kwargs):
        pytest.fail("A client without the current protocol reached the money writer")

    monkeypatch.setattr(debt_split_changes, "accept_bill_split_change_idempotently", unexpected_write)
    with TestClient(app) as client:
        result = client.post("/api/debts/original/split-change-proposals/proposal/accept",
            json={"expected_row_version": 1}, headers={"Idempotency-Key": "not-admitted"})
    assert result.status_code == 409
    assert result.json()["error"] == "client_upgrade_required"
