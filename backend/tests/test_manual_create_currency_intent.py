"""An unsubmitted manual expense retains the money basis the user saw."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import ExpenseManualCreateRequest
from app.services import exchange_rate_service
from app.services.expense_service import _create as owner
from app.services.idempotency import IdempotencyOutcomeKind


@pytest.fixture()
def create_context(monkeypatch):
    db = Mock(spec=Session)
    monkeypatch.setattr(owner, "resolve_write_capability", Mock())
    monkeypatch.setattr(exchange_rate_service, "resolve_write_capability", Mock())
    monkeypatch.setattr(owner, "require_runtime_home_currency_code", lambda _db: "CNY")
    for name in ("_materialize_category_preference", "sync_expense_tags", "mark_duplicate_status",
                 "record_confirmation_revision", "lock_and_revalidate_mutation_actor"):
        monkeypatch.setattr(owner, name, Mock())
    monkeypatch.setattr(owner.permission_service, "require_write_expense", Mock())
    return db


def _insert(db, payload):
    return owner._insert_manual_expense(db, payload, "owner", draft_idempotency_key="device:ref",
        draft_request_fingerprint=owner._manual_request_fingerprint(payload), actor_account_id=1, actor_device_id=1)


def test_new_manual_create_retains_captured_jpy_home_under_current_cny(create_context):
    payload = ExpenseManualCreateRequest(client_ref="captured", amount_cents=12, home_currency_code="JPY", category="餐饮")
    result = _insert(create_context, payload)
    assert (result.home_currency_code, result.original_currency_code,
        result.amount_cents, result.original_amount_minor) == ("JPY", "JPY", 12, 12)
    create_context.commit.assert_not_called()


def test_legacy_explicit_original_money_can_still_be_accepted_without_rewriting_its_body(create_context):
    payload = ExpenseManualCreateRequest(client_ref="legacy", original_currency="CNY", original_amount="12.00", category="餐饮")
    result = _insert(create_context, payload)
    assert (result.original_currency_code, result.original_amount_minor) == ("CNY", 1200)
    assert "home_currency_code" not in payload.model_dump(exclude_unset=True)


def test_new_bare_minor_amount_without_currency_is_refused_before_any_fact_write(create_context):
    with pytest.raises(AppError) as error:
        _insert(create_context, ExpenseManualCreateRequest(client_ref="unknown", amount_cents=12, category="餐饮"))
    assert error.value.error == "manual_currency_context_required"
    create_context.add.assert_not_called()
    create_context.commit.assert_not_called()


def test_legacy_bare_amount_with_existing_fact_requires_review_before_new_write_validation(create_context, monkeypatch):
    payload = ExpenseManualCreateRequest(amount_cents=12, client_ref="old-ref", category="餐饮")
    accepted = SimpleNamespace(id=42, draft_request_fingerprint=owner._manual_request_fingerprint(payload))
    monkeypatch.setattr(owner, "claim_idempotency_key",
        lambda *_args, **_kwargs: SimpleNamespace(kind=IdempotencyOutcomeKind.PROCEED))
    monkeypatch.setattr(owner, "_find_manual_expense_by_key", lambda *_args: accepted)
    auth = SimpleNamespace(account_id=1, ledger_id="owner", tenant_id="owner", device_id=1)
    with pytest.raises(AppError) as caught:
        owner.create_manual_expense(create_context, payload, auth)
    assert (caught.value.error, caught.value.details) == ("manual_create_original_requires_review", {"expense_id": 42})
    create_context.add.assert_not_called()
    create_context.commit.assert_not_called()


def test_native_old_form_without_captured_home_is_blocked_with_inputs_preserved():
    from app.routes.web_expense_create import _manual_expense_failure, _manual_expense_payload

    with pytest.raises(AppError) as error:
        _manual_expense_payload(amount_major="12", currency_code="JPY", merchant="", category="餐饮",
            note="", spent_at="2026-09-09T12:00", client_ref="a" * 32, home_currency="")
    assert error.value.error == "manual_currency_context_required"
    assert _manual_expense_failure(error.value)[1:] == (409, "blocked")
