"""Calendar governance retains accepted results and never changes financial rows."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Ledger, LedgerCalendarRevision
from app.schemas._ledger_calendar import LedgerCalendarChangeRequest
from app.services import ledger_calendar_commands as owner
from app.services.idempotency import IdempotencyOutcomeKind


@pytest.fixture
def command(monkeypatch):
    db = Mock(spec=Session)
    ledger = Ledger(ledger_id="owner", owner_account_id=7, calendar_revision=2)
    state = SimpleNamespace(db=db, ledger=ledger, role="owner", row=SimpleNamespace(response_body=None))
    monkeypatch.setattr(owner, "lock_and_revalidate_mutation_actor", lambda *_args, **_kw: None)
    monkeypatch.setattr(owner, "get_ledger_for_account", lambda *_args, **_kw: (ledger, state.role))
    monkeypatch.setattr(owner, "claim_idempotency_key", lambda *_args, **_kw:
        SimpleNamespace(kind=state.kind, row=state.row))
    monkeypatch.setattr(owner, "mark_idempotency_succeeded", Mock())
    db.scalar.return_value = ledger
    db.get.return_value = LedgerCalendarRevision(ledger_id="owner", revision=2, timezone_name="UTC")
    state.kind = IdempotencyOutcomeKind.PROCEED
    return state


def _change(state, *, expected=2, zone="Asia/Shanghai"):
    return owner.change_ledger_calendar(state.db, ledger_id="owner", actor_account_id=7, auth=None,
        payload=LedgerCalendarChangeRequest(expected_revision=expected, timezone_name=zone), idempotency_key="same-attempt")


def test_owner_change_appends_rule_and_keeps_original_acceptance(command):
    accepted = _change(command)
    assert accepted.revision == 3 and command.ledger.calendar_revision == 3
    assert {type(call.args[0]).__name__ for call in command.db.add.call_args_list} == {"LedgerCalendarRevision", "LedgerAuditLog"}
    command.db.commit.assert_called_once()
    command.row.response_body = accepted.model_dump(mode="json")
    command.kind = IdempotencyOutcomeKind.HIT
    command.ledger.calendar_revision = 9
    command.db.scalar.reset_mock()
    assert _change(command).model_dump(mode="json") == command.row.response_body
    command.db.scalar.assert_not_called()
    command.db.commit.assert_called_once()


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_shared_calendar_requires_owner_even_for_a_financial_writer(command, role):
    command.role = role
    with pytest.raises(AppError) as caught:
        _change(command)
    assert caught.value.status_code == 403
    command.db.add.assert_not_called()


def test_stale_rule_and_invalid_zone_leave_no_calendar_change(command):
    with pytest.raises(AppError) as caught:
        _change(command, expected=1)
    assert caught.value.status_code == 409
    assert command.ledger.calendar_revision == 2
    with pytest.raises(AppError) as caught:
        _change(command, zone="unusable/example")
    assert caught.value.status_code == 422
    command.db.add.assert_not_called()
    command.db.commit.assert_not_called()


def test_accepted_old_rule_is_not_replaced_by_current_rule(command):
    command.kind = IdempotencyOutcomeKind.HIT
    command.row.response_body = {"ledger_id": "owner", "revision": 1, "timezone_name": "UTC",
        "basis": "owner_selected", "adopted_at": datetime(2026, 4, 1, tzinfo=UTC).isoformat()}
    assert _change(command, expected=1).revision == 1
    command.db.get.assert_not_called()
