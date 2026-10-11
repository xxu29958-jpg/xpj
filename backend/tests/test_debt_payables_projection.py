"""Exercise real relationship SELECTs and folds without PostgreSQL write claims."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

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
from app.services.debt_service import _query as query

WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest.fixture
def records(monkeypatch):
    # Only the production SELECT/DTO/fold is under test. PG constraints and
    # the split-return writer belong to their separate transaction tests.
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for model in (Account, Debt, DebtAdjustment, DebtForgiveness, Ledger, LedgerCalendarRevision,
                  LedgerMember, Repayment, RepaymentVoid):
        Table(model.__tablename__, metadata, *(
            Column(column.name, JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
    metadata.create_all(engine)
    monkeypatch.setattr(query, "runtime_home_currency_code", lambda _db: "CNY")
    with Session(engine) as db:
        db.add_all([Account(id=1, display_name="Sender"), Account(id=2, display_name="Receiver"),
                    Account(id=3, display_name="Bystander")])
        for ledger_id, owner, revision, timezone in (("mine", 1, 1, "Asia/Shanghai"),
                                                    ("theirs", 2, 7, "Pacific/Honolulu")):
            db.add(Ledger(ledger_id=ledger_id, name=ledger_id, owner_account_id=owner, calendar_revision=revision))
            db.add(LedgerCalendarRevision(ledger_id=ledger_id, revision=revision, timezone_name=timezone,
                basis="user_selected", adopted_at=WHEN, actor_account_id=owner))
        db.add_all([LedgerMember(ledger_id="mine", account_id=1, role="owner"),
                    LedgerMember(ledger_id="theirs", account_id=2, role="owner")])
        db.flush()
        yield db
    engine.dispose()


def _debt(db, public_id, *, ledger="theirs", owner=2, counterparty=1, direction="owed_to_me"):
    member = counterparty is not None
    debt = Debt(public_id=public_id, tenant_id=ledger, owner_account_id=owner,
        created_by_account_id=owner, direction=direction, counterparty_type="member" if member else "external",
        counterparty_account_id=counterparty, counterparty_label=None if member else "Bank",
        principal_amount_cents=4000, home_currency_code="CNY", status="open",
        source_type="bill_split_return" if member else "manual", source_id=public_id if member else None,
        created_at=WHEN, updated_at=WHEN, row_version=1)
    db.add(debt)
    db.flush()
    return debt


def _payables(db, *, ledger="mine", account=1):
    items = query.list_payables_for_account(db, tenant_id=ledger, account_id=account).items
    assert len({item.public_id for item in items}) == len(items)
    return {item.public_id: item for item in items}


def test_return_counterparty_discovers_payable_with_canonical_role_name_and_balance(records):
    debt = _debt(records, "return-one")
    records.add(Repayment(public_id="partial-return", debt_id=debt.id, amount_cents=1000,
        paid_at=WHEN, actor_account_id=1, idempotency_key="return-payment", created_at=WHEN))
    records.flush()

    rows = _payables(records)
    assert set(rows) == {"return-one"}
    item = rows["return-one"]
    assert item.ledger_id is None
    assert item.viewer_is_debtor is True
    assert item.counterparty_label == "Receiver"
    assert item.direction == "owed_to_me" and item.source_type == "bill_split_return"
    assert (item.principal_amount_cents, item.paid_amount_cents, item.remaining_amount_cents) == (4000, 1000, 3000)
    detail = query.get_participant_debt_response(records, public_id=debt.public_id, ledger_id="mine", account_id=1)
    assert item.model_dump(exclude={"repayment_calendar"}) == detail.model_dump(exclude={"repayment_calendar"})
    assert item.repayment_calendar is None  # Lists do not perform per-row calendar reads.
    assert detail.repayment_calendar.revision == 7
    assert detail.repayment_calendar.timezone_name == "Pacific/Honolulu"
    assert "theirs" not in item.model_dump_json()
    assert "theirs" not in detail.model_dump_json()


def test_local_payables_remain_and_cross_lookup_does_not_grant_third_party_or_external_access(records):
    _debt(records, "local-external", ledger="mine", owner=1, counterparty=None, direction="i_owe")
    _debt(records, "local-counterparty", ledger="mine")
    _debt(records, "return-one")
    _debt(records, "local-receivable", ledger="mine", owner=1, counterparty=2)
    _debt(records, "third-party", counterparty=3)
    _debt(records, "foreign-external", owner=1, counterparty=None, direction="i_owe")
    _debt(records, "foreign-owner-payable", owner=1, counterparty=2, direction="i_owe")
    _debt(records, "cross-receivable", direction="i_owe")

    rows = _payables(records)
    assert set(rows) == {"local-external", "local-counterparty", "return-one"}
    assert rows["local-external"].ledger_id == rows["local-counterparty"].ledger_id == "mine"
    assert rows["return-one"].ledger_id is None


@pytest.mark.parametrize("disabled_at", [None, WHEN])
def test_membership_in_another_ledger_does_not_hide_counterparty_payable(records, disabled_at):
    _debt(records, "return-one")
    records.add(LedgerMember(ledger_id="theirs", account_id=1, role="member", disabled_at=disabled_at))
    records.flush()

    assert _payables(records)["return-one"].ledger_id is None
    if disabled_at is None:
        local = _payables(records, ledger="theirs")
        assert set(local) == {"return-one"}
        assert local["return-one"].ledger_id == "theirs"


@pytest.mark.parametrize("selected_ledger", ["mine", "theirs"])
def test_bystander_ledger_member_does_not_inherit_another_accounts_return_payable(records, selected_ledger):
    _debt(records, "return-one")
    records.add(LedgerMember(ledger_id=selected_ledger, account_id=3, role="member"))
    records.flush()
    assert _payables(records, ledger=selected_ledger, account=3) == {}


def test_existing_receivable_discovery_keeps_its_direction_and_membership_scope(records):
    _debt(records, "receivable", direction="i_owe")
    _debt(records, "return-one")
    before = query.list_member_receivables_for_account(records, account_id=1).items
    assert [item.public_id for item in before] == ["receivable"]
    assert before[0].ledger_id is None and before[0].viewer_is_debtor is False
    records.add(LedgerMember(ledger_id="theirs", account_id=1, role="member"))
    records.flush()
    assert query.list_member_receivables_for_account(records, account_id=1).items == []
    local = query.list_receivables_for_account(records, tenant_id="theirs", account_id=1).items
    assert [item.public_id for item in local] == ["receivable"]
    assert local[0].ledger_id == "theirs"


def test_balance_components_keep_adjustments_forgiveness_and_voided_payments_distinct(records):
    debt = _debt(records, "balance-components")
    records.add_all([
        DebtAdjustment(debt_id=debt.id, amount_cents=-1000, reason="原约定减少", actor_account_id=2),
        DebtAdjustment(debt_id=debt.id, amount_cents=500, reason="双方后来调整", actor_account_id=2),
        DebtForgiveness(debt_id=debt.id, amount_cents=500, actor_account_id=2),
        Repayment(public_id="active-payment", debt_id=debt.id, amount_cents=1000,
                  paid_at=WHEN, actor_account_id=1, idempotency_key="active-payment"),
    ])
    voided = Repayment(public_id="voided-payment", debt_id=debt.id, amount_cents=900,
                       paid_at=WHEN, actor_account_id=1, idempotency_key="voided-payment")
    records.add(voided)
    records.flush()
    records.add(RepaymentVoid(repayment_id=voided.id, actor_account_id=1))
    records.flush()
    detail = query.get_participant_debt_response(records, public_id=debt.public_id, ledger_id="mine", account_id=1)
    assert (detail.principal_amount_cents, detail.paid_amount_cents, detail.adjustment_amount_cents,
            detail.forgiven_amount_cents, detail.remaining_amount_cents) == (4000, 1000, -500, 500, 2000)
    assert detail.ledger_id is None and detail.viewer_is_debtor is True
    assert not detail.is_forgiven  # A later reopened obligation still has an independent prior waiver.
    assert _payables(records)[debt.public_id].model_dump(exclude={"repayment_calendar"}) == detail.model_dump(
        exclude={"repayment_calendar"})
    legacy = detail.model_dump(exclude={"adjustment_amount_cents", "forgiven_amount_cents"})
    old_receipt = type(detail).model_validate(legacy)
    assert old_receipt.adjustment_amount_cents is old_receipt.forgiven_amount_cents is None
