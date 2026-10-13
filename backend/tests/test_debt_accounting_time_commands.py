"""Principal occurrence evidence at its existing financial command owners."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Debt, Expense, LedgerCalendarRevision
from app.schemas import DebtCreateRequest
from app.services.debt_service import _create, _money, installment_payoff_date


def test_backdated_principal_keeps_day_fx_and_schedule_independent_of_recording(monkeypatch):
    db = MagicMock(spec=Session)
    db.get.return_value = LedgerCalendarRevision(ledger_id="original-ledger", revision=3,
        timezone_name="Pacific/Honolulu")
    monkeypatch.setattr(_create, "resolve_write_capability", lambda _db: None)
    rates = []

    def rate(_db, **values):
        rates.append(values["rate_date"])
        return Decimal("7"), "manual", "ready", values["rate_date"]

    monkeypatch.setattr(_money, "resolve_payload_rate", rate)
    payload = DebtCreateRequest(home_currency_code="CNY", direction="i_owe", counterparty_type="external",
        counterparty_label="朋友", original_currency="USD", original_amount="10.00",
        debt_kind="installment", installment_count=2,
        time_input={"precision": "date_only", "calendar_revision": 3, "user_local_date": "2026-01-31"})
    debt = _create.create_debt(db, tenant_id="original-ledger", created_by_account_id=2,
        owner_account_id=2, payload=payload, commit=False)
    assert debt.accounting_time_snapshot["user_local_date"] == "2026-01-31"
    assert debt.accounting_time_snapshot["instant_utc"] is None
    assert debt.accounting_time_snapshot["calendar_revision"] == 3
    assert rates == [date(2026, 1, 31)]
    assert debt.principal_amount_cents == 7000 and debt.original_amount_minor == 1000
    assert installment_payoff_date(debt) == date(2026, 3, 31)
    debt.created_at = datetime(2030, 8, 1, tzinfo=UTC)
    assert installment_payoff_date(debt) == date(2026, 3, 31)


def test_old_principal_has_no_invented_occurrence_or_installment_end():
    debt = Debt(debt_kind="installment", installment_count=6, installment_period_months=1,
        created_at=datetime(2026, 10, 12, tzinfo=UTC))
    assert installment_payoff_date(debt) is None
    debt.accounting_time_snapshot = {"precision": "unknown", "accounting_date": "2026-10-12",
        "basis": "legacy_confirmed_at"}
    assert installment_payoff_date(debt) is None


def test_legacy_command_keeps_timestamp_without_inventing_its_precision(monkeypatch):
    db = MagicMock(spec=Session)
    db.get.side_effect = AssertionError("old input must not acquire today's calendar")
    monkeypatch.setattr(_create, "resolve_write_capability", lambda _db: None)
    payload = DebtCreateRequest(home_currency_code="CNY", direction="i_owe", counterparty_type="external",
        counterparty_label="原欠款", principal_amount_cents=10000, event_time="2026-01-31T00:00:00+08:00")
    debt = _create.create_debt(db, tenant_id="original-ledger", created_by_account_id=2,
        owner_account_id=2, payload=payload, commit=False)
    assert debt.accounting_time_snapshot["instant_utc"] == "2026-01-30T16:00:00Z"
    assert debt.accounting_time_snapshot["precision"] == "unknown"
    assert debt.accounting_time_snapshot["user_local_date"] is None
    assert debt.accounting_time_snapshot["calendar_revision"] is None


def test_split_acceptance_and_delayed_rollout_keep_received_expense_evidence(monkeypatch):
    from types import SimpleNamespace

    from app.services.bill_split_service import _backfill, _transitions

    received = Expense(tenant_id="receiver", time_precision="date_only", user_local_date=date(2026, 1, 31),
        accounting_date=date(2026, 2, 1), calendar_revision=3, accounting_date_basis="recorded_date")
    invitation = SimpleNamespace(public_id="invitation", receiver_ledger_id="receiver", received_expense_id=8,
        receiver_account_id=2, sender_account_id=5, amount_cents=3000, home_currency_code="CNY",
        expense_time_snapshot=None)
    monkeypatch.setattr(_transitions, "get_settings", lambda: SimpleNamespace(debt_rollout_enabled=True))
    monkeypatch.setattr(_create, "resolve_write_capability", lambda _db: None)
    db = MagicMock(spec=Session)
    _transitions._create_accept_debt_if_enabled(db, invitation, received)
    accepted = db.add.call_args.args[0]
    db.scalars.return_value.all.return_value = [invitation]
    db.scalar.return_value = {"accounting_time": accepted.accounting_time_snapshot}
    db.get.side_effect = AssertionError("a later corrected Expense cannot replace accepted evidence")
    assert _backfill.backfill_bill_split_debts(db) == 1
    backfilled = db.add.call_args.args[0]
    assert accepted.accounting_time_snapshot == backfilled.accounting_time_snapshot
    assert accepted.accounting_time_snapshot["user_local_date"] == "2026-01-31"
    assert accepted.accounting_time_snapshot["accounting_date"] == "2026-02-01"
    assert accepted.accounting_time_snapshot["calendar_revision"] == 3
    assert accepted.accounting_time_snapshot["instant_utc"] is None
    assert accepted.principal_amount_cents == backfilled.principal_amount_cents == 3000
    assert accepted.source_id == backfilled.source_id == "invitation"

    # An older confirmation may lack its snapshot. Source-side evidence proves
    # the occurrence, but cannot supply the recipient's accounting day/calendar.
    invitation.accounting_time_snapshot = dict(accepted.accounting_time_snapshot, calendar_revision=9)
    db.scalar.return_value = None
    assert _backfill.backfill_bill_split_debts(db) == 1
    historical = db.add.call_args.args[0].accounting_time_snapshot
    assert historical["user_local_date"] == "2026-01-31"
    assert historical["accounting_date"] is None and historical["calendar_revision"] is None
    assert invitation.accounting_time_snapshot["accounting_date"] == "2026-02-01"
    invitation.accounting_time_snapshot = None
    assert _backfill.backfill_bill_split_debts(db) == 1
    assert db.add.call_args.args[0].accounting_time_snapshot is None


def test_return_obligation_starts_at_the_actual_bilateral_acceptance(monkeypatch):
    from types import SimpleNamespace

    from app.services.bill_split_service import _agreement_commands
    from app.services.debt_service import _principal_time

    db = MagicMock(spec=Session)
    rule = LedgerCalendarRevision(ledger_id="receiver", revision=7, timezone_name="Asia/Shanghai")
    monkeypatch.setattr(_principal_time, "current_calendar", lambda _db, **kw: rule)
    accepted = datetime(2026, 9, 1, 16, 30, tzinfo=UTC)
    monkeypatch.setattr(_agreement_commands, "now_utc", lambda: accepted)
    original = Debt(tenant_id="receiver", owner_account_id=2, counterparty_account_id=5,
        home_currency_code="CNY", source_id="invitation", created_at=datetime(2026, 1, 31, tzinfo=UTC))
    returned = _agreement_commands._create_return(db, SimpleNamespace(original=original), 500, 5)
    assert returned.accounting_time_snapshot["instant_utc"] == "2026-09-01T16:30:00Z"
    assert returned.accounting_time_snapshot["user_local_date"] == "2026-09-02"
    assert returned.accounting_time_snapshot["calendar_revision"] == 7
    assert returned.principal_amount_cents == 500 and returned.source_type == "bill_split_return"


def test_missing_original_calendar_or_conflicting_instant_cannot_commit_principal():
    from app.schemas._accounting_time import AccountingTimeInput
    from app.services.debt_service._principal_time import resolve_principal_time

    db = MagicMock(spec=Session)
    db.get.return_value = None
    time = AccountingTimeInput(precision="date_only", user_local_date="2026-01-31", calendar_revision=3)
    with pytest.raises(AppError, match="原往来任务"):
        resolve_principal_time(db, ledger_id="original", time_input=time, event_time=None)
    with pytest.raises(AppError) as conflict:
        resolve_principal_time(db, ledger_id="original", time_input=time, event_time=datetime(2026, 1, 31, tzinfo=UTC))
    assert conflict.value.error == "accounting_time_invalid"


def test_web_date_is_not_midnight_and_blank_calendar_is_not_a_legacy_command():
    from app.routes.web_debt_create import _create_payload

    fields = {"direction": "i_owe", "counterparty_label": "原欠款", "note": "", "amount_major": "10",
        "currency_code": "USD", "home_currency": "CNY", "event_time": "2026-01-31", "debt_kind": "one_off",
        "installment_count": "", "installment_period_months": ""}
    payload = _create_payload(**fields, calendar_revision="3")
    assert payload.event_time is None and payload.time_input.precision == "date_only"
    assert payload.time_input.user_local_date == date(2026, 1, 31)
    with pytest.raises(AppError):
        _create_payload(**fields, calendar_revision="")
    legacy = _create_payload(**fields)
    assert legacy.event_time is not None and "time_input" not in legacy.model_fields_set


def test_principal_creation_receipt_survives_later_balance_and_calendar_changes(monkeypatch):
    from types import SimpleNamespace

    from app.models import ApiIdempotencyKey
    from app.schemas import DebtResponse
    from app.services import debt_command_service as commands
    from app.services.idempotency import IdempotencyOutcome, IdempotencyOutcomeKind

    db = MagicMock(spec=Session)
    original = DebtResponse(public_id="original-debt", ledger_id="original-ledger", direction="i_owe",
        counterparty_type="external", counterparty_label="原欠款", principal_amount_cents=1000,
        remaining_amount_cents=1000, paid_amount_cents=0, status="open", source_type="manual",
        home_currency_code="CNY", created_at=datetime(2026, 2, 1, tzinfo=UTC),
        updated_at=datetime(2026, 2, 1, tzinfo=UTC), row_version=1,
        accounting_time={"precision": "date_only", "user_local_date": "2026-01-31",
            "accounting_date": "2026-01-31", "calendar_revision": 3, "basis": "recorded_date"})
    current = [original]
    claim = ApiIdempotencyKey()
    outcome = IdempotencyOutcome(IdempotencyOutcomeKind.PROCEED, claim)
    monkeypatch.setattr(commands, "claim_idempotency_key", lambda *a, **kw: outcome)
    create = MagicMock(return_value=SimpleNamespace(public_id="original-debt"))
    monkeypatch.setattr(commands, "create_debt", create)
    monkeypatch.setattr(commands, "get_debt_response", lambda *a, **kw: current[0])
    db.commit.side_effect = lambda: current.__setitem__(0, original.model_copy(update={
        "remaining_amount_cents": 700, "paid_amount_cents": 300, "row_version": 2,
        "repayment_calendar": None}))
    payload = DebtCreateRequest(home_currency_code="CNY", direction="i_owe", counterparty_type="external",
        counterparty_label="原欠款", principal_amount_cents=1000,
        time_input={"precision": "date_only", "user_local_date": "2026-01-31", "calendar_revision": 3})
    args = {"tenant_id": "original-ledger", "actor_account_id": 2, "payload": payload, "idempotency_key": "original-key"}
    first = commands.create_debt_idempotently(db, **args)
    outcome.kind = IdempotencyOutcomeKind.HIT
    replay = commands.create_debt_idempotently(db, **args)
    assert first == replay == original
    assert claim.response_body == original.model_dump(mode="json")
    assert current[0].remaining_amount_cents == 700
    create.assert_called_once()
    db.commit.assert_called_once()


def test_actual_web_form_distinguishes_blank_original_calendar_from_old_protocol(monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.routes import web_debt_create as routes

    db = MagicMock(spec=Session)
    sent = []
    monkeypatch.setattr(routes, "_list_ledger_options", lambda db: [])
    monkeypatch.setattr(routes, "_resolve_selected_ledger_id", lambda *a, **kw: "original-ledger")
    monkeypatch.setattr(routes, "preserve_original_ledger_form", lambda *a, **kw: None)
    monkeypatch.setattr(routes, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(routes, "_actor_account_id", lambda *a: 2)
    monkeypatch.setattr(routes, "create_debt_idempotently", lambda *a, **kw:
        sent.append(kw) or SimpleNamespace(public_id="original-debt"))
    monkeypatch.setattr(routes, "_render_create_error", lambda *a, **kw:
        JSONResponse({"values": kw["values"]}, status_code=kw["status_code"]))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[routes.LocalOnly.dependency] = lambda: None
    fields = {"ledger_id": "original-ledger", "direction": "i_owe", "counterparty_label": "原欠款", "amount_major": "10",
        "currency_code": "CNY", "home_currency_code": "CNY", "event_time": "2026-01-31", "debt_kind": "one_off",
        "idempotency_key": "original-key"}
    with TestClient(app) as client:
        known = client.post("/web/debts", data={**fields, "calendar_revision": "3"}, follow_redirects=False)
        assert known.status_code == 303
        assert sent[-1]["payload"].time_input.user_local_date == date(2026, 1, 31)
        assert sent[-1]["payload"].event_time is None
        blank = client.post("/web/debts", data={**fields, "calendar_revision": ""}, follow_redirects=False)
        assert blank.status_code == 422 and len(sent) == 1
        assert blank.json()["values"]["calendar_revision"] == ""
        assert blank.json()["values"]["idempotency_key"] == "original-key"
        old = client.post("/web/debts", data=fields, follow_redirects=False)
        assert old.status_code == 303
        assert "time_input" not in sent[-1]["payload"].model_fields_set

        def reused(*args, **kwargs):
            raise AppError("idempotency_key_reused", status_code=422)

        monkeypatch.setattr(routes, "create_debt_idempotently", reused)
        conflict = client.post("/web/debts", data=fields, follow_redirects=False)
        assert conflict.status_code == 422
        # An unknown original result cannot become a second financial intent.
        assert conflict.json()["values"]["idempotency_key"] == fields["idempotency_key"]
