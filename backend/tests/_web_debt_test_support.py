"""Pure fixture builders shared by the Web debt projection tests."""

from __future__ import annotations

from types import SimpleNamespace


def stub_debt(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "public_id": "dbt_1",
        "counterparty_label": "招商信用卡",
        "counterparty_type": "external",
        "direction": "i_owe",
        "status": "open",
        "remaining_amount_cents": 50000,
        "principal_amount_cents": 50000,
        "paid_amount_cents": 0,
        "home_currency_code": "CNY",
        "original_currency_code": None,
        "viewer_is_debtor": None,
        "is_forgiven": False,
        "row_version": 1,
        "source_type": "manual",
        # Non-installment defaults keep the schedule card absent unless a test
        # explicitly supplies the installment contract.
        "debt_kind": "unspecified",
        "installment_count": None,
        "installment_period_months": None,
        "installment_paid_count": None,
        "installment_payoff_date": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)
