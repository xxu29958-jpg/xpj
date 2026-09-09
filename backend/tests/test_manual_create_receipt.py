"""Manual acceptance is an original response, never a later expense projection."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.schemas import ExpenseManualCreateRequest, ExpenseResponse
from app.services.expense_service import _create as owner
from app.services.idempotency import IdempotencyOutcomeKind
from app.services.manual_expense_receipt import read_manual_creation_receipt


def _payload(**changes):
    return ExpenseManualCreateRequest(client_ref="original-ref", home_currency_code="JPY",
        original_currency="JPY", original_amount="12", category="餐饮", **changes)


def _expense(status="confirmed"):
    now = datetime(2026, 9, 9, tzinfo=UTC)
    return Expense(id=42, public_id="original-expense", tenant_id="owner", home_currency_code="JPY",
        original_currency_code="JPY", original_amount_minor=12, amount_cents=12 if status == "confirmed" else None,
        category="餐饮", source="手动记账", status=status, fx_status="ready" if status == "confirmed" else "pending",
        duplicate_status="none", row_version=3, fact_revision=1 if status == "confirmed" else 0,
        created_at=now, updated_at=now, expense_time=now, confirmed_at=now if status == "confirmed" else None)


@pytest.fixture
def probe(monkeypatch):
    db = Mock(spec=Session)
    state = SimpleNamespace(db=db, expense=_expense(), claims={}, inserts=0, commits=[])
    auth = SimpleNamespace(account_id=1, device_id=7, tenant_id="owner", ledger_id="owner")
    def claim(_db, **fields):
        key = fields["tenant_id"], fields["idempotency_key"]
        existing = state.claims.get(key)
        if existing is None:
            existing = SimpleNamespace(**fields, response_body=None, resource_id=None,
                resource_type=None, status="in_progress")
            state.claims[key] = existing
            kind = IdempotencyOutcomeKind.PROCEED
        elif existing.request_fingerprint != fields["request_fingerprint"]:
            kind = IdempotencyOutcomeKind.FINGERPRINT_MISMATCH
        else:
            kind = IdempotencyOutcomeKind.HIT
        return SimpleNamespace(kind=kind, row=existing)
    def insert(*_args, **_kwargs):
        state.inserts += 1
        return state.expense
    def accept(_db, row, **values):
        for name, value in values.items():
            setattr(row, name, value)
        row.status = "succeeded"
    monkeypatch.setattr(owner, "claim_idempotency_key", claim, raising=False)
    monkeypatch.setattr(owner, "mark_idempotency_succeeded", accept, raising=False)
    monkeypatch.setattr(owner, "lock_and_revalidate_mutation_actor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(owner.permission_service, "require_write_expense", lambda _auth: None)
    monkeypatch.setattr(owner, "_find_manual_expense_by_key", lambda *_args: None)
    monkeypatch.setattr(owner, "_insert_manual_expense", insert)
    monkeypatch.setattr(owner, "expense_to_response",
        lambda _db, *, expense, tenant_id: ExpenseResponse.model_validate(expense), raising=False)
    db.commit.side_effect = lambda: state.commits.append([row.response_body for row in state.claims.values()])
    return state, auth


@pytest.mark.parametrize("status", ["confirmed", "pending"])
def test_replay_returns_original_response_after_later_correction_or_confirmation(probe, monkeypatch, status):
    state, auth = probe
    state.expense = _expense(status)
    accepted = owner.create_manual_expense(state.db, _payload(), auth)
    assert isinstance(accepted, ExpenseResponse)
    original = accepted.model_dump(mode="json")
    assert state.commits == [[original]]
    state.expense.amount_cents, state.expense.row_version, state.expense.status = 900, 9, "confirmed"
    monkeypatch.setattr(owner, "_find_manual_expense_by_key",
        lambda *_args: pytest.fail("A receipt HIT must not read the current expense"))
    replay = owner.create_manual_expense(state.db, _payload(), auth)
    assert replay.model_dump(mode="json") == original
    assert state.inserts == 1
    assert state.db.commit.call_count == 1


def test_legacy_matching_key_without_receipt_requires_review_not_latest_success(probe, monkeypatch):
    state, auth = probe
    state.expense.draft_request_fingerprint = owner._manual_request_fingerprint(_payload())
    monkeypatch.setattr(owner, "_find_manual_expense_by_key", lambda *_args: state.expense)
    with pytest.raises(AppError) as caught:
        owner.create_manual_expense(state.db, _payload(), auth)
    assert (caught.value.error, caught.value.status_code) == ("manual_create_original_requires_review", 409)
    assert caught.value.details == {"expense_id": 42}
    assert state.inserts == 0
    state.db.commit.assert_not_called()


@pytest.mark.parametrize("body", [None, {}, {"id": 42}])
def test_missing_or_invalid_saved_receipt_never_uses_current_expense(probe, monkeypatch, body):
    state, auth = probe
    owner.create_manual_expense(state.db, _payload(), auth)
    next(iter(state.claims.values())).response_body = body
    monkeypatch.setattr(owner, "_find_manual_expense_by_key", lambda *_args: pytest.fail("No latest fallback"))
    with pytest.raises(AppError) as caught:
        owner.create_manual_expense(state.db, _payload(), auth)
    assert caught.value.error == "manual_create_original_requires_review"
    assert state.inserts == 1


def test_ref_key_is_device_scoped_fits_table_and_keeps_original_fingerprint(probe):
    state, auth = probe
    payload = _payload().model_copy(update={"client_ref": "r" * 64})
    owner.create_manual_expense(state.db, payload, auth)
    first_key = next(iter(state.claims))[1]
    assert len(first_key) <= 64
    assert next(iter(state.claims.values())).request_fingerprint == owner._manual_request_fingerprint(payload)
    auth.device_id = 8
    owner.create_manual_expense(state.db, payload, auth)
    assert len(state.claims) == 2
    assert state.inserts == 2


@pytest.mark.parametrize("body", [{}, {"client_ref": None}, {"client_ref": ""}, {"client_ref": "   "}])
def test_new_manual_body_requires_an_original_nonblank_client_reference(body):
    with pytest.raises(ValidationError):
        ExpenseManualCreateRequest(amount_cents=12, home_currency_code="JPY", **body)


def test_original_reference_and_legacy_fingerprint_are_not_normalized():
    payload = ExpenseManualCreateRequest(client_ref=" original ", original_currency="CNY", original_amount="12.00")
    assert payload.client_ref == " original "
    assert "home_currency_code" not in payload.model_dump(exclude_unset=True)
    assert owner._manual_request_fingerprint(payload) == owner._manual_request_fingerprint(
        payload.model_copy(update={"client_ref": "different"}))


@pytest.mark.parametrize("step", ["expense_to_response", "mark_idempotency_succeeded"])
def test_receipt_failure_never_commits_the_created_fact(probe, monkeypatch, step):
    state, auth = probe
    def fail(*_args, **_kwargs):
        raise AppError("server_error", status_code=503)
    monkeypatch.setattr(owner, step, fail)
    with pytest.raises(AppError):
        owner.create_manual_expense(state.db, _payload(), auth)
    state.db.commit.assert_not_called()
    state.db.rollback.assert_called_once()


def test_web_ack_reads_saved_receipt_without_reconstructing_current_fact(probe):
    state, auth = probe
    accepted = owner.create_manual_expense(state.db, _payload(), auth)
    claim = next(iter(state.claims.values()))
    state.db.scalar.return_value = claim
    state.expense.amount_cents, state.expense.status = 999, "rejected"
    assert read_manual_creation_receipt(state.db, tenant_id="owner", device_id=7,
        client_ref="original-ref") == accepted
    query = state.db.scalar.call_args.args[0].compile().params
    assert set(query.values()) == {"owner", next(iter(state.claims))[1], "succeeded"}
    claim.response_body = None
    assert read_manual_creation_receipt(state.db, tenant_id="owner", device_id=7, client_ref="original-ref") is None
