"""PG round-trip of 20260617_0001 (add repayment_drafts, ADR-0049 §杠杆③ slice 3a).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries
``repayment_drafts``) then ``alembic stamp head``, so the guarded ``create_table`` body
never runs on the normal path — which means a divergence between the migration's
hand-written ``create_table`` and the ORM would ship UNDETECTED by the deployment path.
This drives the migration directly on PostgreSQL: create_all → stamp head → downgrade past
20260617_0001 (drops the table) → upgrade to head (re-creates it via the migration body),
then REFLECTS the migration-built table and asserts its columns / nullability / CHECK
constraints / unique constraint / indexes — not just that the table name exists, so a
dropped CHECK / unique / index / column in the migration fails HERE (mirrors the four
sibling alembic round-trip tests).

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``) because it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

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
_CHECK_CONSTRAINTS = {
    "ck_repayment_drafts_amount_positive",
    "ck_repayment_drafts_status_valid",
    "ck_repayment_drafts_home_currency_format",
}
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


def _index_names() -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes("repayment_drafts")}


def _assert_full_shape() -> None:
    cols = _columns()
    for name in _NOT_NULL_COLUMNS:
        assert name in cols, f"{name} missing from repayment_drafts"
        assert cols[name]["nullable"] is False, f"{name} should be NOT NULL"
    for name in _NULLABLE_COLUMNS:
        assert name in cols, f"{name} missing from repayment_drafts"
        assert cols[name]["nullable"] is True, f"{name} should be nullable"
    assert _check_names() >= _CHECK_CONSTRAINTS, (
        f"missing CHECK(s): {_CHECK_CONSTRAINTS - _check_names()}"
    )
    assert "uq_repayment_drafts_idem" in _unique_names(), "missing dedup unique constraint"
    assert _index_names() >= _INDEXES, f"missing index(es): {_INDEXES - _index_names()}"


def _reset_empty_database() -> None:
    Base.metadata.drop_all(bind=engine)


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
    cfg = _alembic_cfg()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, *args)


def test_add_repayment_drafts_round_trips_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        _assert_full_shape()  # the current ORM shape

        _run_alembic(command.stamp, "20260617_0001")
        _run_alembic(command.downgrade, "20260616_0002")
        assert "repayment_drafts" not in _table_names()  # downgrade drops it

        _run_alembic(command.upgrade, "head")
        # Re-created via the migration's hand-written create_table — assert the FULL
        # shape (columns/nullability/CHECKs/unique/indexes), not just the table name, so
        # a migration↔ORM divergence (dropped CHECK / unique / index / column) fails here.
        _assert_full_shape()
    finally:
        _reset_empty_database()
        _drop_alembic_version()
