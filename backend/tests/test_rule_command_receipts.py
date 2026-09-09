"""An accepted rule command replays its original snapshot, never the current row."""

from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.schemas import CategoryRuleCreateRequest, CategoryRuleUpdateRequest
from app.services import rule_command_service as commands
from app.services.idempotency import IdempotencyOutcomeKind


def _receipt():
    return {"id": 17, "keyword": "Travel", "category": "交通", "enabled": True, "priority": 100,
        "amount_min_cents": 1200, "amount_max_cents": None, "home_currency_code": "JPY",
        "source_contains": None, "tag_contains": None, "row_version": 1,
        "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}


def _call(kind, key="original-key", db=None):
    if kind == "create":
        return commands.create_rule_idempotently(db, tenant_id="owner", idempotency_key=key,
            payload=CategoryRuleCreateRequest(keyword="Travel", category="交通", amount_min_cents=1200, home_currency_code="JPY"))
    return commands.update_rule_idempotently(db, tenant_id="owner", rule_id=17, idempotency_key=key,
        payload=CategoryRuleUpdateRequest(expected_row_version=3, amount_min_cents=1200, home_currency_code="JPY"))


@pytest.mark.parametrize("kind", ["create", "update"])
def test_accepted_snapshot_replays_without_any_latest_read_or_write(monkeypatch, kind):
    body = _receipt()
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **kw: SimpleNamespace(
        kind=IdempotencyOutcomeKind.HIT, row=SimpleNamespace(resource_id="17", response_body=body)))
    for name in ("get_rule_for_tenant", "create_rule", "update_rule"):
        monkeypatch.setattr(commands, name, lambda *a, **kw: pytest.fail("Replay must not access a newer rule"))
    result = _call(kind)
    assert result.model_dump(mode="json") == body


@pytest.mark.parametrize("kind", ["create", "update"])
@pytest.mark.parametrize("body", [None, {}, {**_receipt(), "home_currency_code": None}, {**_receipt(), "id": "invalid"}])
def test_unverifiable_accepted_receipt_requires_review(monkeypatch, kind, body):
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **kw: SimpleNamespace(
        kind=IdempotencyOutcomeKind.HIT, row=SimpleNamespace(resource_id="17", response_body=body)))
    monkeypatch.setattr(commands, "get_rule_for_tenant", lambda *a, **kw: pytest.fail("No latest-row fallback"))
    with pytest.raises(AppError) as caught:
        _call(kind)
    assert (caught.value.error, caught.value.status_code) == ("rule_original_requires_review", 409)


@pytest.mark.parametrize("kind", ["create", "update"])
@pytest.mark.parametrize(("outcome", "error", "status"), [
    (IdempotencyOutcomeKind.IN_PROGRESS, "idempotency_key_in_progress", 409),
    (IdempotencyOutcomeKind.FINGERPRINT_MISMATCH, "idempotency_key_reused", 422),
])
def test_claim_refusal_cannot_mutate(monkeypatch, kind, outcome, error, status):
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **kw: SimpleNamespace(kind=outcome))
    with pytest.raises(AppError) as caught:
        _call(kind)
    assert (caught.value.error, caught.value.status_code) == (error, status)


@pytest.mark.parametrize("kind", ["create", "update"])
@pytest.mark.parametrize("key", [None, "", "x" * 65])
def test_original_key_is_required_before_a_claim(monkeypatch, kind, key):
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **kw: pytest.fail("Invalid key must not claim"))
    with pytest.raises(AppError) as caught:
        _call(kind, key)
    assert caught.value.status_code == 422
