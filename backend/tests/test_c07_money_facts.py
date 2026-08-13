"""Mutation-sensitive tests for the C07 semantic financial-fact digest."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.models  # noqa: F401 - register declarative model tables
from app import c07_money_facts
from app.database import _c07_app_meta
from app.database_model_registry import Base


class _Preparer:
    @staticmethod
    def quote_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'


class _MoneyConnection:
    dialect = SimpleNamespace(identifier_preparer=_Preparer())

    def __init__(
        self,
        rows: list[tuple[object, ...]],
        *,
        installation_currency: object = "CNY",
    ) -> None:
        self.rows = rows
        self.installation_currency = installation_currency

    def execute(self, statement, *args, **kwargs):
        return iter(self.rows)

    def scalar(self, statement, *args, **kwargs):
        return self.installation_currency


class _Inspector:
    @staticmethod
    def get_pk_constraint(table: str) -> dict[str, object]:
        assert table == "ledger_rows"
        return {"constrained_columns": ["id"]}
    @staticmethod
    def get_columns(table: str) -> list[dict[str, str]]:
        assert table == "ledger_rows"
        return [
            {"name": name}
            for name in (
                "id",
                "amount_cents",
                "fee_cents",
                "public_id",
                "currency_code",
                "exchange_rate",
            )
        ]


def test_app_meta_read_stays_behind_database_boundary() -> None:
    connection = _MoneyConnection([])

    assert _c07_app_meta.read_app_meta_value(connection, "home_currency") == "CNY"


def _install_ledger_manifest(monkeypatch) -> None:
    monkeypatch.setattr(
        c07_money_facts,
        "MONEY_COLUMNS_V1",
        (
            SimpleNamespace(table="ledger_rows", column="amount_cents"),
            SimpleNamespace(table="ledger_rows", column="fee_cents"),
        ),
    )
    monkeypatch.setattr(
        c07_money_facts,
        "MONEY_FACT_TABLES",
        ("ledger_rows",),
    )
    monkeypatch.setattr(
        c07_money_facts,
        "MONEY_FACT_CONTEXT_COLUMNS_V1",
        (
            (
                "ledger_rows",
                ("public_id", "currency_code", "exchange_rate"),
            ),
        ),
    )
    monkeypatch.setattr(
        c07_money_facts,
        "inspect",
        lambda connection: _Inspector(),
    )


def _digest(
    rows: list[tuple[object, ...]],
    *,
    installation_currency: object = "CNY",
) -> str:
    return c07_money_facts.canonical_money_facts_sha256(
        _MoneyConnection(
            rows,
            installation_currency=installation_currency,
        )
    )


def test_semantic_manifest_binds_currency_scope_and_projection_state() -> None:
    contexts = dict(c07_money_facts.MONEY_FACT_CONTEXT_COLUMNS_V1)

    assert {
        "home_currency_code",
        "original_currency_code",
        "exchange_rate_to_cny",
        "status",
        "receiver_ledger_id",
        "received_expense_id",
    } <= set(contexts["bill_split_invitations"])
    assert {
        "original_currency_code",
        "exchange_rate_to_cny",
        "exchange_rate_date",
        "exchange_rate_source",
        "status",
    } <= set(contexts["csv_import_rows"])
    assert {"home_currency_code", "original_currency_code", "status"} <= set(
        contexts["expenses"]
    )
    assert {"tenant_id", "status", "archived_at"} <= set(contexts["goals"])
    for table in (
        "bill_split_invitations",
        "budget_categories",
        "budgets",
        "debt_adjustments",
        "debt_forgivenesses",
        "debts",
        "expense_items",
        "expense_splits",
        "expenses",
        "goals",
        "member_repayment_proposals",
        "monthly_income_plans",
        "ocr_facts",
        "recurring_items",
        "repayment_drafts",
        "repayments",
    ):
        assert "public_id" in contexts[table]


def test_semantic_manifest_matches_current_model_shape() -> None:
    contexts = dict(c07_money_facts.MONEY_FACT_CONTEXT_COLUMNS_V1)
    for table, columns in contexts.items():
        actual_columns = set(Base.metadata.tables[table].columns.keys())
        assert set(columns) <= actual_columns


def test_digest_detects_value_row_identity_and_semantic_context_mutation(
    monkeypatch,
) -> None:
    _install_ledger_manifest(monkeypatch)
    baseline_rows = [
        (1, 100, None, "public-1", "CNY", Decimal("1.00000000")),
        (2, -50, 3, "public-2", "USD", Decimal("7.00000000")),
    ]
    digests = {
        _digest(baseline_rows),
        _digest(
            [
                (
                    1,
                    101,
                    None,
                    "public-1",
                    "CNY",
                    Decimal("1.00000000"),
                ),
                baseline_rows[1],
            ]
        ),
        _digest([baseline_rows[0]]),
        _digest(
            [
                baseline_rows[0],
                (
                    3,
                    -50,
                    3,
                    "public-2",
                    "USD",
                    Decimal("7.00000000"),
                ),
            ]
        ),
        _digest(
            [
                baseline_rows[0],
                (
                    2,
                    -50,
                    3,
                    "public-2",
                    "JPY",
                    Decimal("7.00000000"),
                ),
            ]
        ),
        _digest(
            [
                baseline_rows[0],
                (
                    2,
                    -50,
                    3,
                    "public-3",
                    "USD",
                    Decimal("7.00000000"),
                ),
            ]
        ),
    }

    assert all(len(value) == 64 for value in digests)
    assert len(digests) == 6


def test_c07_digest_rejects_public_identity_mutation(monkeypatch) -> None:
    _install_ledger_manifest(monkeypatch)
    baseline = [
        (1, 100, None, "public-1", "CNY", Decimal("1.00000000")),
    ]
    mutated = [
        (1, 100, None, "public-2", "CNY", Decimal("1.00000000")),
    ]

    assert _digest(mutated) != _digest(baseline)


def test_digest_binds_installation_currency_marker(monkeypatch) -> None:
    _install_ledger_manifest(monkeypatch)
    rows = [
        (1, 100, None, "public-1", "CNY", Decimal("1.00000000")),
    ]

    assert _digest(rows, installation_currency="CNY") != _digest(
        rows,
        installation_currency="JPY",
    )


def test_digest_rejects_unexpected_missing_context_column(
    monkeypatch,
) -> None:
    _install_ledger_manifest(monkeypatch)
    monkeypatch.setattr(
        c07_money_facts,
        "MONEY_FACT_CONTEXT_COLUMNS_V1",
        (
            (
                "ledger_rows",
                (
                    "public_id",
                    "currency_code",
                    "exchange_rate",
                    "misspelled_scope",
                ),
            ),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="missing frozen source columns: ledger_rows",
    ):
        _digest(
            [
                (
                    1,
                    100,
                    None,
                    "public-1",
                    "CNY",
                    Decimal("1.00000000"),
                )
            ]
        )
