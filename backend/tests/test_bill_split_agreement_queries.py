"""Use the real agreement and existing participant DTO queries."""

import pytest

from app.errors import AppError
from app.services.bill_split_service._agreement_queries import get_bill_split_agreement
from tests.bill_split_test_support import accept_agreement_change as _accept
from tests.bill_split_test_support import agreement_db as agreement_db
from tests.bill_split_test_support import record_agreement_payment as _paid
from tests.bill_split_test_support import request_agreement_change as _request


def test_each_party_sees_the_same_share_and_return_without_the_others_ledger(agreement_db):
    db, split = agreement_db
    _paid(db, split, split["original_id"], 4_000)
    _accept(db, split, _request(db, split, share=2_000, net=-2_000))
    sender = get_bill_split_agreement(db, tenant_id="owner", actor_account_id=split["sender_id"], public_id=split["debt"])
    receiver = get_bill_split_agreement(db, tenant_id="split-receiver", actor_account_id=split["receiver_id"], public_id=split["debt"])
    assert sender.agreed_share_amount_cents == receiver.agreed_share_amount_cents == 2_000
    assert sender.settlement_net_amount_cents == receiver.settlement_net_amount_cents == -2_000
    assert sender.original_debt.ledger_id is None
    assert sender.return_debt.ledger_id is None
    assert sender.return_debt.viewer_is_debtor is True
    assert receiver.return_debt.viewer_is_debtor is False
    assert "split-receiver" not in sender.model_dump_json()
    assert '"owner"' not in receiver.model_dump_json()
    assert "sender_expense_id" not in sender.model_dump_json()


def test_third_party_ledger_reader_can_read_but_is_not_offered_bilateral_actions(agreement_db):
    db, split = agreement_db
    view = get_bill_split_agreement(db, tenant_id="split-receiver", actor_account_id=split["viewer_id"], public_id=split["debt"])
    assert not view.viewer_is_party
    with pytest.raises(AppError) as denied:
        get_bill_split_agreement(db, tenant_id="unrelated", actor_account_id=split["viewer_id"], public_id=split["debt"])
    assert denied.value.error == "debt_not_found"


def test_a_previous_custom_settlement_remains_visible_when_previewing_another_share(agreement_db):
    db, split = agreement_db
    _paid(db, split, split["original_id"], 4_000)
    _accept(db, split, _request(db, split, share=2_000, net=-500))
    view = get_bill_split_agreement(db, tenant_id="split-receiver", actor_account_id=split["receiver_id"],
        public_id=split["debt"], new_share_amount_cents=3_000)
    assert view.preview.requires_explicit_settlement
    assert view.preview.default_settlement_net_amount_cents == -500
    assert view.preview.cash_based_settlement_net_amount_cents == -1_000
    assert view.agreed_share_amount_cents == 2_000


@pytest.mark.parametrize("latest_share", [0, 1_500])
def test_source_impact_uses_latest_accepted_share_without_rewriting_invitation_or_expense(agreement_db, latest_share):
    from types import SimpleNamespace

    from app.models import BillSplitInvitation, Debt, Expense
    from app.routes._web_expense_offset_fact import _relationship_view
    from app.routes.web_common import templates
    from app.services.bill_split_service._query import list_accepted_source_relationships
    from app.services.expense_offset_relationship_projection import relationship_impacts

    db, split = agreement_db

    def source_relationship():
        return list_accepted_source_relationships(db, sender_ledger_id="owner", sender_expense_id=split["source"])[0]

    assert source_relationship().agreed_share_home_minor == 4_000
    first = _request(db, split, share=2_000, net=2_000)
    assert source_relationship().agreed_share_home_minor == 4_000, "A pending proposal is not an agreement"
    _accept(db, split, first)
    assert source_relationship().agreed_share_home_minor == 4_000
    assert source_relationship().current_agreed_share_home_minor == 2_000
    _accept(db, split, _request(db, split, share=latest_share, net=latest_share))
    _request(db, split, share=1_800, net=1_800)
    assert source_relationship().agreed_share_home_minor == 4_000
    assert source_relationship().current_agreed_share_home_minor == latest_share
    impacts = relationship_impacts(db, tenant_id="owner", expense_id=split["source"],
        offsets=[SimpleNamespace(id=1, accounting_date="2026-09-20", kind="refund")],
        summary=SimpleNamespace(remaining_refundable_original_minor=5_000, gross_original_minor=10_000))
    assert impacts.accepted_impacts[0].original_agreed_share_home_minor == 4_000
    assert impacts.accepted_impacts[0].current_agreed_share_home_minor == latest_share
    assert impacts.accepted_impacts[0].suggested_net_share_home_minor == 2_000, "Never discount the renegotiated share again"
    web = _relationship_view(SimpleNamespace(relationship_impacts=impacts, root=SimpleNamespace(home_currency="CNY")))
    assert web["accepted"][0]["original_share_label"] == "¥40.00"
    assert web["accepted"][0]["current_share_label"] == ("¥0.00" if latest_share == 0 else "¥15.00")
    assert web["accepted"][0]["suggested_share_label"] == "¥20.00"
    assert web["accepted"][0]["debt_public_id"] == split["debt"]
    rendered = templates.get_template("_fact_offsets.html").render(
        expense={"id": split["source"], "row_version": 1, "original_currency_code": "CNY"},
        offset_summary={"status": "partially_refunded"},
        offset_form={"open": False, "accounting_date": "2026-09-20"},
        offset_currency_input={}, edit_return_fields={},
        offset_relationship_impacts=web, active_offsets=[], offset_recent_history=[], offset_can_write=False)
    assert "原份额 ¥40.00" in rendered
    assert "当前约定 " + web["accepted"][0]["current_share_label"] in rendered
    assert "按原份额对原单净额计算的参考为 ¥20.00" in rendered
    assert "不是再次减免或新的待结算金额" in rendered
    assert "也不表示双方尚未处理" in rendered
    assert list_accepted_source_relationships(db, sender_ledger_id="wrong-ledger", sender_expense_id=split["source"]) == ()
    assert db.get(BillSplitInvitation, split["invitation_id"]).amount_cents == 4_000
    assert db.get(Debt, split["original_id"]).principal_amount_cents == 4_000
    assert db.get(Expense, split["source"]).amount_cents == 10_000
