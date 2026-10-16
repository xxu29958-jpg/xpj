"""Actual PostgreSQL relationship projection, authority and balance components."""

from datetime import UTC, datetime

import pytest

from app.database import SessionLocal
from app.models import (
    Account,
    Debt,
    DebtAdjustment,
    DebtForgiveness,
    Ledger,
    LedgerCalendarRevision,
    LedgerMember,
    Repayment,
    RepaymentVoid,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.debt_service import _query as query

WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def records(identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        accounts = {name: Account(display_name=name) for name in ("Sender", "Receiver", "Bystander")}
        db.add_all(accounts.values())
        db.flush()
        actors = {name: account.id for name, account in accounts.items()}
        for ledger_id, owner, revision, timezone in (("mine", actors["Sender"], 1, "Asia/Shanghai"),
                                                    ("theirs", actors["Receiver"], 7, "Pacific/Honolulu")):
            ledger = Ledger(ledger_id=ledger_id, name=ledger_id, owner_account_id=owner)
            db.add(ledger)
            db.flush()
            db.add(LedgerCalendarRevision(ledger_id=ledger_id, revision=revision, timezone_name=timezone,
                basis="user_selected", adopted_at=WHEN, actor_account_id=owner))
            db.flush()
            ledger.calendar_revision = revision
            db.add(LedgerMember(ledger_id=ledger_id, account_id=owner, role="owner"))
        db.flush()
        yield db, actors


def _debt(db, actors, public_id, *, ledger="theirs", owner="Receiver", counterparty="Sender", direction="owed_to_me"):
    member = counterparty is not None
    debt = Debt(public_id=public_id, tenant_id=ledger, owner_account_id=actors[owner],
        created_by_account_id=actors[owner], direction=direction, counterparty_type="member" if member else "external",
        counterparty_account_id=actors[counterparty] if member else None, counterparty_label=None if member else "Bank",
        principal_amount_cents=4000, home_currency_code="CNY", status="open",
        source_type="bill_split_return" if member else "manual", source_id=public_id if member else None,
        created_at=WHEN, updated_at=WHEN, row_version=1)
    db.add(debt)
    db.flush()
    return debt


def _payables(db, actors, *, ledger="mine", account="Sender"):
    items = query.list_payables_for_account(db, tenant_id=ledger, account_id=actors[account]).items
    assert len({item.public_id for item in items}) == len(items)
    return {item.public_id: item for item in items}


def test_return_counterparty_discovers_payable_with_canonical_role_name_and_balance(records):
    db, actors = records
    debt = _debt(db, actors, "return-one")
    db.add(Repayment(public_id="partial-return", debt_id=debt.id, amount_cents=1000,
        paid_at=WHEN, actor_account_id=actors["Sender"], idempotency_key="return-payment", created_at=WHEN))
    db.flush()

    rows = _payables(db, actors)
    assert set(rows) == {"return-one"}
    item = rows["return-one"]
    assert item.ledger_id is None
    assert item.viewer_is_debtor is True
    assert item.counterparty_label == "Receiver"
    assert item.direction == "owed_to_me" and item.source_type == "bill_split_return"
    assert (item.principal_amount_cents, item.paid_amount_cents, item.remaining_amount_cents) == (4000, 1000, 3000)
    detail = query.get_participant_debt_response(db, public_id=debt.public_id, ledger_id="mine", account_id=actors["Sender"])
    assert item.model_dump(exclude={"repayment_calendar"}) == detail.model_dump(exclude={"repayment_calendar"})
    assert item.repayment_calendar is None  # Lists do not perform per-row calendar reads.
    assert detail.repayment_calendar.revision == 7
    assert detail.repayment_calendar.timezone_name == "Pacific/Honolulu"
    assert "theirs" not in item.model_dump_json()
    assert "theirs" not in detail.model_dump_json()


def test_local_payables_remain_and_cross_lookup_does_not_grant_third_party_or_external_access(records):
    db, actors = records
    _debt(db, actors, "local-external", ledger="mine", owner="Sender", counterparty=None, direction="i_owe")
    _debt(db, actors, "local-counterparty", ledger="mine")
    _debt(db, actors, "return-one")
    _debt(db, actors, "local-receivable", ledger="mine", owner="Sender", counterparty="Receiver")
    _debt(db, actors, "third-party", counterparty="Bystander")
    _debt(db, actors, "foreign-external", owner="Sender", counterparty=None, direction="i_owe")
    _debt(db, actors, "foreign-owner-payable", owner="Sender", counterparty="Receiver", direction="i_owe")
    _debt(db, actors, "cross-receivable", direction="i_owe")

    rows = _payables(db, actors)
    assert set(rows) == {"local-external", "local-counterparty", "return-one"}
    assert rows["local-external"].ledger_id == rows["local-counterparty"].ledger_id == "mine"
    assert rows["return-one"].ledger_id is None


@pytest.mark.parametrize("disabled_at", [None, WHEN])
def test_membership_in_another_ledger_does_not_hide_counterparty_payable(records, disabled_at):
    db, actors = records
    _debt(db, actors, "return-one")
    db.add(LedgerMember(ledger_id="theirs", account_id=actors["Sender"], role="member", disabled_at=disabled_at))
    db.flush()

    assert _payables(db, actors)["return-one"].ledger_id is None
    if disabled_at is None:
        local = _payables(db, actors, ledger="theirs")
        assert set(local) == {"return-one"}
        assert local["return-one"].ledger_id == "theirs"


@pytest.mark.parametrize("selected_ledger", ["mine", "theirs"])
def test_bystander_ledger_member_does_not_inherit_another_accounts_return_payable(records, selected_ledger):
    db, actors = records
    _debt(db, actors, "return-one")
    db.add(LedgerMember(ledger_id=selected_ledger, account_id=actors["Bystander"], role="member"))
    db.flush()
    assert _payables(db, actors, ledger=selected_ledger, account="Bystander") == {}


def test_existing_receivable_discovery_keeps_its_direction_and_membership_scope(records):
    db, actors = records
    _debt(db, actors, "receivable", direction="i_owe")
    _debt(db, actors, "return-one")
    before = query.list_member_receivables_for_account(db, account_id=actors["Sender"]).items
    assert [item.public_id for item in before] == ["receivable"]
    assert before[0].ledger_id is None and before[0].viewer_is_debtor is False
    db.add(LedgerMember(ledger_id="theirs", account_id=actors["Sender"], role="member"))
    db.flush()
    assert query.list_member_receivables_for_account(db, account_id=actors["Sender"]).items == []
    local = query.list_receivables_for_account(db, tenant_id="theirs", account_id=actors["Sender"]).items
    assert [item.public_id for item in local] == ["receivable"]
    assert local[0].ledger_id == "theirs"


def test_balance_components_keep_adjustments_forgiveness_and_voided_payments_distinct(records):
    db, actors = records
    debt = _debt(db, actors, "balance-components")
    db.add_all([
        DebtAdjustment(debt_id=debt.id, amount_cents=-1000, reason="原约定减少", actor_account_id=actors["Receiver"], idempotency_key="adjust-minus"),
        DebtAdjustment(debt_id=debt.id, amount_cents=500, reason="双方后来调整", actor_account_id=actors["Receiver"], idempotency_key="adjust-plus"),
        DebtForgiveness(debt_id=debt.id, amount_cents=500, actor_account_id=actors["Receiver"], idempotency_key="forgive"),
        Repayment(public_id="active-payment", debt_id=debt.id, amount_cents=1000,
                  paid_at=WHEN, actor_account_id=actors["Sender"], idempotency_key="active-payment"),
    ])
    voided = Repayment(public_id="voided-payment", debt_id=debt.id, amount_cents=900,
                       paid_at=WHEN, actor_account_id=actors["Sender"], idempotency_key="voided-payment")
    db.add(voided)
    db.flush()
    db.add(RepaymentVoid(repayment_id=voided.id, actor_account_id=actors["Sender"], reason="Duplicate payment", idempotency_key="void-payment"))
    db.flush()
    detail = query.get_participant_debt_response(db, public_id=debt.public_id, ledger_id="mine", account_id=actors["Sender"])
    assert (detail.principal_amount_cents, detail.paid_amount_cents, detail.adjustment_amount_cents,
            detail.forgiven_amount_cents, detail.remaining_amount_cents) == (4000, 1000, -500, 500, 2000)
    assert detail.ledger_id is None and detail.viewer_is_debtor is True
    assert not detail.is_forgiven  # A later reopened obligation still has an independent prior waiver.
    assert _payables(db, actors)[debt.public_id].model_dump(exclude={"repayment_calendar"}) == detail.model_dump(
        exclude={"repayment_calendar"})
    legacy = detail.model_dump(exclude={"adjustment_amount_cents", "forgiven_amount_cents"})
    old_receipt = type(detail).model_validate(legacy)
    assert old_receipt.adjustment_amount_cents is old_receipt.forgiven_amount_cents is None
