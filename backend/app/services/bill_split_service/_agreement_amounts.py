"""Settlement suggestions over the existing two Debt folds, never a new fold."""

from dataclasses import dataclass

from app.money_contract import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX, MoneySign, ensure_money_minor


@dataclass(frozen=True)
class SettlementAmounts:
    original_remaining: int
    return_remaining: int = 0
    original_paid: int = 0
    return_paid: int = 0
    original_forgiven: int = 0
    return_forgiven: int = 0


@dataclass(frozen=True)
class SettlementPreview:
    default_settlement_net: int
    cash_based_settlement_net: int | None
    requires_explicit_settlement: bool


def change_settlement_preview(
    *, new_share_amount_cents: int, amounts: SettlementAmounts,
    previous_custom_settlement: bool = False,
) -> SettlementPreview:
    share = ensure_money_minor(new_share_amount_cents, sign=MoneySign.NONNEGATIVE,
        label="bill_split_change.new_share", error_code="debt_amount_invalid")
    cash_reference = share - amounts.original_paid + amounts.return_paid
    explicit = bool(amounts.original_forgiven or amounts.return_forgiven or previous_custom_settlement)
    # Historical cash can accumulate across many agreements. A single new command
    # cannot silently clamp that reference to its smaller accepted money envelope.
    explicit = explicit or abs(cash_reference) > MONEY_MINOR_MAX
    default = amounts.original_remaining - amounts.return_remaining if explicit else cash_reference
    return SettlementPreview(default_settlement_net=default,
        cash_based_settlement_net=cash_reference if abs(cash_reference) <= MONEY_AGGREGATE_MAX else None,
        requires_explicit_settlement=explicit)


def settlement_targets(settlement_net_amount_cents: int) -> tuple[int, int]:
    """Positive means receiver still pays sender; negative means sender returns money."""
    net = ensure_money_minor(settlement_net_amount_cents, sign=MoneySign.SIGNED,
        label="bill_split_change.settlement_net", error_code="debt_amount_invalid")
    return max(net, 0), max(-net, 0)
