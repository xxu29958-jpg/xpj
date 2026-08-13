"""PG round-trip of 20260617_0001 (add repayment_drafts, ADR-0049 §杠杆③ slice 3a).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries
``repayment_drafts``) then ``alembic stamp head``, so the guarded ``create_table`` body
never runs on the normal path — which means a divergence between the migration's
hand-written ``create_table`` and the ORM would ship UNDETECTED by the deployment path.
This drives the migration directly on PostgreSQL: create_all → stamp the tested
revision → downgrade past 20260617_0001 (drops the table) → upgrade to that
revision (re-creates it via the migration body). It separately asserts the
current ORM/C07 shape and the historical migration-built shape, including
columns, nullability, CHECKs, unique constraints, and indexes.

Marked ``real_db`` below because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.database import engine
from app.database_model_registry import Base
from tests._infra.c07_alembic import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_NOT_NULL_COLUMNS = (
    "id",
    "public_id",
    "tenant_id",
    "created_by_account_id",
    "source",
    "amount_cents",
    "home_currency_code",
    "captured_at",
    "draft_idempotency_key",
    "status",
    "created_at",
)
_NULLABLE_COLUMNS = (
    "merchant_label",
    "committed_debt_public_id",
    "committed_repayment_public_id",
    "resolved_at",
    "resolved_by_account_id",
)
_COMMON_CHECK_CONSTRAINTS = {
    "ck_repayment_drafts_status_valid",
    "ck_repayment_drafts_home_currency_format",
}
_LEGACY_AMOUNT_CHECK = "ck_repayment_drafts_amount_positive"
_C07_AMOUNT_CHECK = "ck_repayment_drafts_amount_cents_money_bounds"
_C07_SOURCE_REVISION = "20260722_0001"
_INDEXES = {
    "ix_repayment_drafts_public_id",
    "ix_repayment_drafts_tenant_id",
    "ix_repayment_drafts_tenant_status",
}


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _columns() -> dict[str, dict]:
    return {col["name"]: col for col in inspect(engine).get_columns("repayment_drafts")}


def _check_names() -> set[str]:
    return {cc["name"] for cc in inspect(engine).get_check_constraints("repayment_drafts")}


def _unique_names() -> set[str]:
    return {uc["name"] for uc in inspect(engine).get_unique_constraints("repayment_drafts")}


def _idem_constraint_columns() -> list[str]:
    for uc in inspect(engine).get_unique_constraints("repayment_drafts"):
        if uc["name"] == "uq_repayment_drafts_idem":
            return list(uc["column_names"])
    raise AssertionError("uq_repayment_drafts_idem missing from repayment_drafts")


def _index_names() -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes("repayment_drafts")}


def _assert_full_shape(*, c07: bool, account_scoped: bool) -> None:
    cols = _columns()
    for name in _NOT_NULL_COLUMNS:
        assert name in cols, f"{name} missing from repayment_drafts"
        assert cols[name]["nullable"] is False, f"{name} should be NOT NULL"
    for name in _NULLABLE_COLUMNS:
        assert name in cols, f"{name} missing from repayment_drafts"
        assert cols[name]["nullable"] is True, f"{name} should be nullable"
    amount_type = str(cols["amount_cents"]["type"]).lower()
    if c07:
        assert "bigint" in amount_type or amount_type == "int8"
    else:
        assert amount_type in {"integer", "int4"}
    expected_checks = _COMMON_CHECK_CONSTRAINTS | {
        _C07_AMOUNT_CHECK if c07 else _LEGACY_AMOUNT_CHECK
    }
    absent_check = _LEGACY_AMOUNT_CHECK if c07 else _C07_AMOUNT_CHECK
    assert _check_names() >= expected_checks, (
        f"missing CHECK(s): {expected_checks - _check_names()}"
    )
    assert absent_check not in _check_names()
    assert "uq_repayment_drafts_idem" in _unique_names(), "missing dedup unique constraint"
    # Issue #224 (C3): the dedup unique is ACCOUNT-scoped — assert the column set, not
    # just the name, so a tenant-wide regression fails here.
    expected_idem_columns = (
        ["tenant_id", "created_by_account_id", "draft_idempotency_key"]
        if account_scoped
        else ["tenant_id", "draft_idempotency_key"]
    )
    assert _idem_constraint_columns() == expected_idem_columns
    assert _index_names() >= _INDEXES, f"missing index(es): {_INDEXES - _index_names()}"


def _reset_empty_database() -> None:
    reset_public_schema(engine)


def _drop_alembic_version() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _alembic_cfg():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    return cfg


def _run_alembic(action, *args) -> None:
    run_alembic_for_test(engine, _alembic_cfg(), action, *args)


def test_add_repayment_drafts_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape(c07=True, account_scoped=True)

        _run_alembic(command.stamp, "20260617_0001")
        _run_alembic(command.downgrade, "20260616_0002")
        assert "repayment_drafts" not in _table_names()  # downgrade drops it

        _run_alembic(command.upgrade, "20260617_0001")
        # First prove the historical create_table body exactly, before later
        # migrations replace its tenant-scoped idempotency and amount CHECK.
        _assert_full_shape(c07=False, account_scoped=False)

        # Do not cross C07 from this synthetic shape: only the recreated
        # repayment_drafts carrier is int4 while every untouched current-ORM
        # money table is int8. The C07 migration correctly rejects that mixed
        # state. Reset before exercising a true all-int4 source-to-head path.

        _reset_empty_database()
        _run_alembic(command.upgrade, _C07_SOURCE_REVISION)
        _assert_full_shape(c07=False, account_scoped=True)
        _run_alembic(command.upgrade, "head")
        _assert_full_shape(c07=True, account_scoped=True)
    finally:
        _reset_empty_database()
        _drop_alembic_version()
