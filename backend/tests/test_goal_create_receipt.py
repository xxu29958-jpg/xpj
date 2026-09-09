"""An accepted spending-goal creation cannot become a second or newer goal."""

from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.schemas import GoalCreateRequest
from app.services import goal_create_command as commands
from app.services.idempotency import IdempotencyOutcomeKind


def _payload():
    return GoalCreateRequest(name="Travel", month="2026-09", category="交通",
        target_amount_cents=1200, home_currency_code="JPY")


def _receipt():
    return {
        "public_id": "goal-original", "ledger_id": "owner", "name": "Travel",
        "goal_type": "spending_limit", "period": "monthly", "month": "2026-09",
        "category": "交通", "target_amount_cents": 1200, "home_currency_code": "JPY",
        "spent_amount_cents": 0, "remaining_amount_cents": 1200, "progress_percent": 0,
        "progress_state": "not_started", "status": "active", "row_version": 1,
        "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
    }


def _call():
    return commands.create_spending_goal_idempotently(None, tenant_id="owner",
        payload=_payload(), idempotency_key="original-key", timezone_name="Asia/Shanghai")


def test_create_replay_returns_original_captured_money_without_a_new_write(monkeypatch):
    claim = SimpleNamespace(kind=IdempotencyOutcomeKind.HIT,
        row=SimpleNamespace(resource_id="goal-original", response_body=_receipt()))
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *args, **kwargs: claim)
    monkeypatch.setattr(commands, "create_goal", lambda *args, **kwargs: pytest.fail("replay must not create"))
    result = _call()
    assert (result.public_id, result.home_currency_code, result.target_amount_cents) == ("goal-original", "JPY", 1200)
    assert result.row_version == 1
    assert result.status == "active"


@pytest.mark.parametrize("body", [None, {}, {**_receipt(), "home_currency_code": None}])
def test_missing_original_receipt_requires_review_without_recreating(monkeypatch, body):
    claim = SimpleNamespace(kind=IdempotencyOutcomeKind.HIT,
        row=SimpleNamespace(resource_id="goal-original", response_body=body))
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *args, **kwargs: claim)
    monkeypatch.setattr(commands, "create_goal", lambda *args, **kwargs: pytest.fail("must not recreate"))
    with pytest.raises(AppError) as caught:
        _call()
    assert (caught.value.error, caught.value.status_code) == ("goal_original_requires_review", 409)


@pytest.mark.parametrize(("kind", "code", "status"), [
    (IdempotencyOutcomeKind.IN_PROGRESS, "idempotency_key_in_progress", 409),
    (IdempotencyOutcomeKind.FINGERPRINT_MISMATCH, "idempotency_key_reused", 422),
])
def test_claim_refusal_does_not_create(monkeypatch, kind, code, status):
    monkeypatch.setattr(commands, "claim_idempotency_key",
        lambda *args, **kwargs: SimpleNamespace(kind=kind))
    monkeypatch.setattr(commands, "create_goal", lambda *args, **kwargs: pytest.fail("must not create"))
    with pytest.raises(AppError) as caught:
        _call()
    assert (caught.value.error, caught.value.status_code) == (code, status)
