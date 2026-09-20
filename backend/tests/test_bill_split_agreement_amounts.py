"""Financial examples distinguish a new share, cash and an existing waiver."""

import pytest

from app.errors import AppError
from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX
from app.services.bill_split_service._agreement_amounts import (
    SettlementAmounts,
    change_settlement_preview,
    settlement_targets,
)


@pytest.mark.parametrize(("paid", "expected"), [(0, 2_000), (1_000, 1_000), (3_000, -1_000), (4_000, -2_000)])
def test_new_share_accounts_for_actual_payment_without_fabricating_repayment(paid, expected):
    preview = change_settlement_preview(
        new_share_amount_cents=2_000,
        amounts=SettlementAmounts(original_remaining=4_000 - paid, original_paid=paid),
    )
    assert preview.default_settlement_net == expected
    assert preview.cash_based_settlement_net == expected
    assert not preview.requires_explicit_settlement


@pytest.mark.parametrize(("share", "expected"), [(2_000, -1_200), (3_000, -200), (3_500, 300), (4_000, 800)])
def test_repeated_changes_preserve_both_directions_of_actual_cash(share, expected):
    amounts = SettlementAmounts(original_remaining=0, return_remaining=1_200,
        original_paid=4_000, return_paid=800)
    preview = change_settlement_preview(new_share_amount_cents=share, amounts=amounts)
    assert preview.default_settlement_net == expected
    assert settlement_targets(expected) == (max(expected, 0), max(-expected, 0))


def test_original_forgiveness_is_neither_a_cash_refund_nor_revoked_by_new_share():
    amounts = SettlementAmounts(original_remaining=0, original_paid=1_000, original_forgiven=3_000)
    preview = change_settlement_preview(new_share_amount_cents=2_000, amounts=amounts)
    assert preview.requires_explicit_settlement
    assert preview.default_settlement_net == 0
    assert preview.cash_based_settlement_net == 1_000


def test_return_forgiveness_does_not_reappear_as_an_automatic_return_claim():
    amounts = SettlementAmounts(original_remaining=0, original_paid=4_000,
        return_paid=800, return_forgiven=1_200)
    preview = change_settlement_preview(new_share_amount_cents=3_000, amounts=amounts)
    assert preview.requires_explicit_settlement
    assert preview.default_settlement_net == 0
    assert preview.cash_based_settlement_net == -200


def test_an_explicit_earlier_settlement_is_not_silently_replaced_by_a_cash_formula():
    preview = change_settlement_preview(new_share_amount_cents=3_000,
        amounts=SettlementAmounts(original_remaining=0, original_paid=4_000, return_remaining=500),
        previous_custom_settlement=True)
    assert preview.requires_explicit_settlement
    assert preview.default_settlement_net == -500
    assert preview.cash_based_settlement_net == -1_000


@pytest.mark.parametrize("net", [-MONEY_MINOR_MAX, -1, 0, 1, MONEY_MINOR_MAX])
def test_each_accepted_target_is_nonnegative_and_only_one_direction_is_outstanding(net):
    original, returned = settlement_targets(net)
    assert original - returned == net
    assert min(original, returned) == 0
    assert 0 <= original <= MONEY_MINOR_MAX
    assert 0 <= returned <= MONEY_MINOR_MAX


@pytest.mark.parametrize("net", [True, "10", MONEY_MINOR_MAX + 1, -MONEY_MINOR_MAX - 1])
def test_invalid_signed_commands_do_not_silently_change_money(net):
    with pytest.raises(AppError) as error:
        settlement_targets(net)
    assert error.value.error == "debt_amount_invalid"


def test_cumulative_cash_outside_one_command_keeps_current_terms_for_explicit_review():
    preview = change_settlement_preview(new_share_amount_cents=MONEY_MINOR_MAX,
        amounts=SettlementAmounts(original_remaining=500, return_paid=MONEY_AGGREGATE_MAX))
    assert preview.requires_explicit_settlement
    assert preview.default_settlement_net == 500
    assert preview.cash_based_settlement_net is None
