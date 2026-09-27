"""An arrangement retains explicit zero, original currency and accepted intent."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.errors import AppError
from app.schemas._monthly_arrangement import MonthlyArrangementDto, MonthlyArrangementSaveRequest
from app.services import monthly_arrangement_service as command
from app.services.idempotency import IdempotencyOutcomeKind


def _payload(**changes):
    return MonthlyArrangementSaveRequest(**{"home_currency_code": "JPY", "savings_target_cents": 0,
        "reserved_buffer_cents": 100, "expected_row_version": None, **changes})


@pytest.mark.parametrize("amount", [-1, True, 1.1, "100", 9_000_000_000_001])
def test_arrangement_cannot_accept_invalid_money(amount):
    with pytest.raises(ValidationError):
        _payload(savings_target_cents=amount)


@pytest.mark.parametrize("token", [True, "1", 1.0, 0, -1])
def test_arrangement_token_requires_the_exact_observed_integer(token):
    with pytest.raises(ValidationError):
        _payload(expected_row_version=token)


def test_missing_arrangement_is_distinct_from_explicit_zero():
    db = Mock()
    db.scalar.return_value = None
    assert command.read_monthly_arrangement(db, tenant_id="owner", month="2026-09") is None
    assert _payload(reserved_buffer_cents=0).savings_target_cents == 0


def test_ack_loss_replays_original_receipt_without_touching_later_facts(monkeypatch):
    receipt = MonthlyArrangementDto(ledger_id="owner", month="2026-09", home_currency_code="JPY",
        savings_target_cents=0, reserved_buffer_cents=100, row_version=1, updated_at=datetime.now(UTC))
    db = Mock()
    monkeypatch.setattr(command, "claim_idempotency_key", lambda *a, **k: SimpleNamespace(
        kind=IdempotencyOutcomeKind.HIT, row=SimpleNamespace(response_body=receipt.model_dump(mode="json"))))
    apply = Mock()
    monkeypatch.setattr(command, "_apply_save", apply)
    assert command.save_monthly_arrangement(db, tenant_id="owner", month="2026-09", payload=_payload(),
        actor_account_id=1, idempotency_key="lost-ack") == receipt
    apply.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("currency,version", [("CNY", 3), ("JPY", 1), ("JPY", None)])
def test_stale_or_relabelled_arrangement_preserves_fact(monkeypatch, currency, version):
    db = Mock()
    row = SimpleNamespace(id=7, tenant_id="owner", month="2026-09", home_currency_code="JPY",
        savings_target_cents=300, reserved_buffer_cents=100, row_version=3)
    db.scalar.return_value = row
    monkeypatch.setattr(command, "resolve_write_capability", lambda _: None)
    monkeypatch.setattr(command, "claim_idempotency_key", lambda *a, **k: SimpleNamespace(
        kind=IdempotencyOutcomeKind.PROCEED, row=object()))
    with pytest.raises(AppError):
        command.save_monthly_arrangement(db, tenant_id="owner", month="2026-09", actor_account_id=1,
            idempotency_key="original", payload=_payload(home_currency_code=currency, expected_row_version=version))
    assert (row.savings_target_cents, row.reserved_buffer_cents, row.row_version) == (300, 100, 3)
    db.commit.assert_not_called()
    db.rollback.assert_called_once_with()


def test_unknown_or_pending_original_command_cannot_claim_confirmed_ack():
    db = Mock()
    db.scalar.return_value = None
    assert command.review_monthly_arrangement_save(db, tenant_id="owner", month="2026-09", idempotency_key="unknown") is False
    db.scalar.return_value = SimpleNamespace(operation="save_monthly_arrangement", target_type="monthly_arrangement",
        target_id="2026-09", status="in_progress")
    with pytest.raises(AppError):
        command.review_monthly_arrangement_save(db, tenant_id="owner", month="2026-09", idempotency_key="pending")


def test_review_does_not_accept_another_month_or_operation():
    db = Mock()
    db.scalar.return_value = SimpleNamespace(operation="save_monthly_budget", target_type="monthly_budget",
        target_id="2026-09", status="succeeded")
    with pytest.raises(AppError):
        command.review_monthly_arrangement_save(db, tenant_id="owner", month="2026-09", idempotency_key="wrong-operation")


@pytest.mark.parametrize("kind", [IdempotencyOutcomeKind.IN_PROGRESS, IdempotencyOutcomeKind.FINGERPRINT_MISMATCH])
def test_unaccepted_command_does_not_publish_or_change_intent(monkeypatch, kind):
    db = Mock()
    monkeypatch.setattr(command, "claim_idempotency_key", lambda *a, **k: SimpleNamespace(kind=kind))
    apply = Mock()
    monkeypatch.setattr(command, "_apply_save", apply)
    with pytest.raises(AppError):
        command.save_monthly_arrangement(db, tenant_id="owner", month="2026-09", payload=_payload(),
            actor_account_id=1, idempotency_key="original")
    apply.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_called_once_with()


def test_arrangement_registry_preserves_facts_and_bounds_without_mutating_frozen_money():
    from sqlalchemy import BigInteger, CheckConstraint

    from app.database._dataset_restore_security import RESTORE_TABLE_SECURITY
    from app.database_model_registry import Base
    from app.monthly_arrangement_money_contract import MONTHLY_ARRANGEMENT_MONEY_COLUMNS
    from app.services.portable_export_queries import PORTABLE_COLLECTION_SCOPES

    for column in MONTHLY_ARRANGEMENT_MONEY_COLUMNS:
        table = Base.metadata.tables[column.table]
        assert isinstance(table.c[column.column].type, BigInteger)
        checks = {check.name: str(check.sqltext) for check in table.constraints if isinstance(check, CheckConstraint)}
        assert checks[column.final_check_name] == column.final_check_predicate
        assert len(column.final_check_name) <= 63
        assert RESTORE_TABLE_SECURITY[column.table] == "preserve"
        assert column.table in PORTABLE_COLLECTION_SCOPES


def test_api_writer_uses_protocol_gate_and_readers_use_ledger_context():
    from app.auth import get_current_app_context, get_current_protocol_writer_context
    from app.routes.monthly_arrangements import router

    for route in router.routes:
        auth_calls = {dependency.call for dependency in route.dependant.dependencies}
        expected = get_current_protocol_writer_context if "PUT" in route.methods else get_current_app_context
        assert expected in auth_calls
