"""A repeated command returns its accepted money, not a later record revision."""

from types import SimpleNamespace

from app.services import idempotency
from app.services import recurring_item_command_service as commands
from app.services.idempotency import IdempotencyOutcomeKind


def _accepted_claim(monkeypatch, *, version=1):
    receipt = {
        "public_id": "recurring", "ledger_id": "owner", "home_currency_code": "JPY",
        "merchant": "Subscription", "merchant_key": "subscription", "frequency": "monthly",
        "baseline_amount_cents": 1200, "last_amount_cents": 1200, "occurrence_count": 0,
        "status": "active", "source": "manual", "row_version": version,
        "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
    }
    claim = SimpleNamespace(kind=IdempotencyOutcomeKind.HIT,
        row=SimpleNamespace(resource_id="recurring", response_body=receipt))
    latest = SimpleNamespace(**{**receipt, "baseline_amount_cents": 9900, "row_version": 3})
    monkeypatch.setattr(commands, "_get_item", lambda *args, **kwargs: latest)
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *args, **kwargs: claim)
    monkeypatch.setattr(idempotency, "claim_idempotency_key", lambda *args, **kwargs: claim)
    return claim


def test_create_replay_preserves_accepted_amount_and_revision(monkeypatch):
    _accepted_claim(monkeypatch)
    response = commands.create_manual_recurring_item(None, tenant_id="owner", idempotency_key="original-key",
        merchant="Subscription", home_currency_code="JPY", baseline_amount_cents=1200, next_expected_date=None)
    assert response.home_currency_code == "JPY"
    assert response.baseline_amount_cents == 1200
    assert response.row_version == 1


def test_update_replay_preserves_accepted_amount_and_revision(monkeypatch):
    _accepted_claim(monkeypatch, version=2)
    response = commands.update_recurring_item(None, tenant_id="owner", public_id="recurring",
        idempotency_key="original-key", expected_row_version=1, home_currency_code="JPY", merchant=None, merchant_provided=False,
        baseline_amount_cents=1200, baseline_provided=True, next_expected_date=None,
        next_expected_date_provided=False)
    assert response.home_currency_code == "JPY"
    assert response.baseline_amount_cents == 1200
    assert response.row_version == 2
