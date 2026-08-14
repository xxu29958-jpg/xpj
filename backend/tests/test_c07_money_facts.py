"""Mutation-sensitive tests for the C07 semantic financial-fact digest."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

import app.models  # noqa: F401 - register declarative model tables
from app import (
    app_meta_observation,
    canonical_money_facts,
    canonical_money_facts_contract,
)
from app.database_model_registry import Base
from tests._infra.database_model_registry_probes import (
    assert_runtime_database_free_imports,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_MONEY_FACT_VECTOR_SHA256 = (
    "9700fd8212155284c5c63c1f46e53fbe12463aa30f66c0dfd2cc2717b894ade7"
)
PUBLISHED_MONEY_FACT_MANIFEST_SHA256 = (
    "febe40244bc39b73cfcf6cfc87c3cbf97fcb2db34b1aab98ca765ff361ef1075"
)


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
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement, *args, **kwargs):
        self.executions.append((str(statement), kwargs))
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


def test_app_meta_read_is_a_runtime_database_free_engine_observation() -> None:
    connection = _MoneyConnection([])

    assert (
        app_meta_observation.read_app_meta_value(connection, "home_currency")
        == "CNY"
    )
    app_root = Path(__file__).resolve().parents[1] / "app"
    assert not (app_root / "c07_money_facts.py").exists()
    assert not (app_root / "c07_money_facts_contract.py").exists()
    assert not (app_root / "database" / "_c07_app_meta.py").exists()
    assert (
        canonical_money_facts.MONEY_FACTS_SCHEMA
        == canonical_money_facts_contract.MONEY_FACTS_SCHEMA
    )
    assert_runtime_database_free_imports(
        BACKEND_ROOT,
        "app.app_meta_observation",
        "app.canonical_money_facts_contract",
        "app.canonical_money_facts",
    )


def test_app_meta_read_ignores_hostile_search_path() -> None:
    from app.database import engine

    key = f"money_fact_observer_{uuid4().hex}"
    schema = f"money_fact_decoy_{uuid4().hex}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            quoted_schema = connection.dialect.identifier_preparer.quote_identifier(
                schema
            )
            connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            connection.execute(
                text(
                    f"CREATE TABLE {quoted_schema}.app_meta "
                    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO public.app_meta (key, value, updated_at) "
                    "VALUES (:key, :value, CURRENT_TIMESTAMP)"
                ),
                {"key": key, "value": "public-value"},
            )
            connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.app_meta (key, value) "
                    "VALUES (:key, :value)"
                ),
                {"key": key, "value": "decoy-value"},
            )
            connection.execute(
                text(f"SET LOCAL search_path TO {quoted_schema}, public")
            )

            assert (
                app_meta_observation.read_app_meta_value(connection, key)
                == "public-value"
            )
        finally:
            transaction.rollback()


def test_published_digest_vector_pins_bytes_and_primary_key_order(
    monkeypatch,
) -> None:
    context_columns = (
        "unicode_context",
        "decimal_context",
        "date_context",
        "datetime_context",
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_COLUMNS_V1",
        (
            SimpleNamespace(table="ledger_rows", column="amount_cents"),
            SimpleNamespace(table="ledger_rows", column="fee_cents"),
        ),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_FACT_TABLES",
        ("ledger_rows",),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_FACT_CONTEXT_COLUMNS_V1",
        (("ledger_rows", context_columns),),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "inspect",
        lambda _connection: SimpleNamespace(
            get_pk_constraint=lambda _table: {"constrained_columns": ["id"]},
            get_columns=lambda _table: [
                {"name": name}
                for name in (
                    "id",
                    "amount_cents",
                    "fee_cents",
                    *context_columns,
                )
            ],
        ),
    )
    connection = _MoneyConnection(
        [
            (
                UUID("11111111-1111-4111-8111-111111111111"),
                -123,
                None,
                "票据-α",
                Decimal("7.500"),
                date(2026, 8, 14),
                datetime(2026, 8, 14, 4, 5, 6, tzinfo=UTC),
            )
        ],
        installation_currency="JPY",
    )

    assert (
        canonical_money_facts.canonical_money_facts_sha256(connection)
        == PUBLISHED_MONEY_FACT_VECTOR_SHA256
    )
    assert connection.executions == [
        (
            'SELECT "id", "amount_cents", "fee_cents", "unicode_context", '
            '"decimal_context", "date_context", "datetime_context" FROM '
            '"ledger_rows" ORDER BY "id"',
            {"execution_options": {"stream_results": True, "yield_per": 1000}},
        )
    ]


def _install_ledger_manifest(monkeypatch) -> None:
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_COLUMNS_V1",
        (
            SimpleNamespace(table="ledger_rows", column="amount_cents"),
            SimpleNamespace(table="ledger_rows", column="fee_cents"),
        ),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_FACT_TABLES",
        ("ledger_rows",),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "MONEY_FACT_CONTEXT_COLUMNS_V1",
        (
            (
                "ledger_rows",
                ("public_id", "currency_code", "exchange_rate"),
            ),
        ),
    )
    monkeypatch.setattr(
        canonical_money_facts,
        "inspect",
        lambda connection: _Inspector(),
    )


def _digest(
    rows: list[tuple[object, ...]],
    *,
    installation_currency: object = "CNY",
) -> str:
    return canonical_money_facts.canonical_money_facts_sha256(
        _MoneyConnection(
            rows,
            installation_currency=installation_currency,
        )
    )


def test_semantic_manifest_binds_currency_scope_and_projection_state() -> None:
    manifest_payload = {
        "schema": canonical_money_facts.MONEY_FACTS_SCHEMA,
        "installation_currency_key": (
            canonical_money_facts.INSTALLATION_HOME_CURRENCY_KEY
        ),
        "money_columns": [
            (contract.table, contract.column)
            for contract in canonical_money_facts.MONEY_COLUMNS_V1
        ],
        "context_columns": canonical_money_facts.MONEY_FACT_CONTEXT_COLUMNS_V1,
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert manifest_sha256 == PUBLISHED_MONEY_FACT_MANIFEST_SHA256

    contexts = dict(canonical_money_facts.MONEY_FACT_CONTEXT_COLUMNS_V1)

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
    contexts = dict(canonical_money_facts.MONEY_FACT_CONTEXT_COLUMNS_V1)
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
        canonical_money_facts,
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
