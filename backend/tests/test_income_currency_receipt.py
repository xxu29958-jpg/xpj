"""Old accepted income receipts gain currency only from their immutable revision."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.schemas import IncomePlanUpdateRequest
from app.services.idempotency import IdempotencyOutcomeKind
from app.services.income_plan_service import _delivery


def _old_receipt(monkeypatch, *, revised_amount=1200):
    body = {
        "public_id": "income-1", "label": "Salary", "source_type": "salary",
        "frequency": "monthly", "income_month": None, "amount_cents": 1200, "pay_day": 10,
        "status": "active", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-09T00:00:00Z",
        "row_version": 2, "archived_at": None,
    }
    monkeypatch.setattr(_delivery, "claim_idempotency_key", lambda *args, **kwargs: SimpleNamespace(
        kind=IdempotencyOutcomeKind.HIT, row=SimpleNamespace(response_body=body),
    ))
    revision = SimpleNamespace(**{key: body[key] for key in (
        "label", "source_type", "frequency", "income_month", "pay_day", "status",
    )}, amount_cents=revised_amount, home_currency_code="JPY")
    db = Mock()
    db.scalar.return_value = revision
    return db, body


def _replay(db):
    return _delivery.update_income_plan_idempotently(
        db, tenant_id="owner", public_id="income-1", actor_account_id=1, idempotency_key="accepted-intent",
        payload=IncomePlanUpdateRequest(expected_row_version=1, intent_month="2026-09", amount_cents=1200),
    )


def test_old_income_receipt_uses_its_revision_currency_without_rewriting_the_receipt(monkeypatch):
    db, body = _old_receipt(monkeypatch)
    before = dict(body)
    result = _replay(db)
    assert result.home_currency_code == "JPY"
    assert result.amount_cents == 1200
    assert body == before and "home_currency_code" not in body
    db.commit.assert_not_called()


def test_a_different_revision_cannot_be_used_to_declare_a_receipts_currency(monkeypatch):
    db, _ = _old_receipt(monkeypatch, revised_amount=9900)
    with pytest.raises(AppError) as error:
        _replay(db)
    assert error.value.error == "income_plan_response_unverified"
    db.commit.assert_not_called()
