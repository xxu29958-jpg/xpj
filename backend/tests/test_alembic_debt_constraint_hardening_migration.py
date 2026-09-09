"""PG round-trip of 20260618_0001 (ADR-0049 #4 member-repayment + draft constraint backstops).

Check current ORM shape independently, then round-trip the frozen migration
on its actual PostgreSQL schema. Never stamp a current schema as a historical one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from app.database import engine
from app.database_model_registry import Base
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_PRIOR_HEAD = "20260617_0001"
_REVISION = "20260618_0001"

# (table, fk_name, referred_table, constrained_columns, referred_columns)
_FOREIGN_KEYS = (
    ("repayments", "fk_repayments_proposal", "member_repayment_proposals", ["proposal_id"], ["id"]),
    ("member_repayment_proposals", "fk_mrp_committed_repayment", "repayments", ["committed_repayment_id"], ["id"]),
    ("member_repayment_proposals", "fk_mrp_supersedes_proposal", "member_repayment_proposals", ["supersedes_proposal_id"], ["id"]),
)
# (table, check_name)
_CHECKS = (
    ("member_repayment_proposals", "ck_mrp_committed_iff_confirmed"),
    ("member_repayment_proposals", "ck_mrp_confirmed_amount_iff_confirmed"),
    ("repayment_drafts", "ck_repayment_drafts_committed_iff_confirmed"),
)


def _fk_def(table: str, name: str) -> tuple | None:
    for fk in inspect(engine).get_foreign_keys(table):
        if fk["name"] == name:
            return (fk["referred_table"], list(fk["constrained_columns"]), list(fk["referred_columns"]))
    return None


def _check_sqltext(table: str, name: str) -> str | None:
    for cc in inspect(engine).get_check_constraints(table):
        if cc["name"] == name:
            return cc.get("sqltext")
    return None


def _capture_orm_definitions() -> tuple[dict, dict]:
    """After create_all: the EXPECTED (ORM single-source) constraint definitions, also asserting
    the FKs point where the spec says (so the baseline itself is verified, not just captured)."""
    fks = {(t, n): _fk_def(t, n) for t, n, *_ in _FOREIGN_KEYS}
    checks = {(t, n): _check_sqltext(t, n) for t, n in _CHECKS}
    for table, name, ref_table, con_cols, ref_cols in _FOREIGN_KEYS:
        assert fks[(table, name)] == (ref_table, con_cols, ref_cols), (
            f"ORM FK {name} def {fks[(table, name)]} != ({ref_table}, {con_cols}, {ref_cols})"
        )
    for table, name in _CHECKS:
        assert checks[(table, name)], f"ORM CHECK {name} missing on {table}"
    return fks, checks


def _assert_matches(expected_fks: dict, expected_checks: dict) -> None:
    # Migration-built defs must EQUAL the ORM defs — referent + predicate, not just name.
    for table, name, *_ in _FOREIGN_KEYS:
        assert _fk_def(table, name) == expected_fks[(table, name)], (
            f"migration FK {name} diverged from ORM: {_fk_def(table, name)} != {expected_fks[(table, name)]}"
        )
    for table, name in _CHECKS:
        assert _check_sqltext(table, name) == expected_checks[(table, name)], (
            f"migration CHECK {name} predicate diverged from ORM: "
            f"{_check_sqltext(table, name)!r} != {expected_checks[(table, name)]!r}"
        )


def _assert_absent() -> None:
    for table, name, *_ in _FOREIGN_KEYS:
        assert _fk_def(table, name) is None, f"FK {name} should be dropped from {table}"
    for table, name in _CHECKS:
        assert _check_sqltext(table, name) is None, f"CHECK {name} should be dropped from {table}"


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


def test_debt_constraint_backstops_round_trip_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        # create_all builds the final ORM shape on a fresh DB — and proves the circular
        # FK pair (use_alter on committed_repayment_id) does NOT deadlock table creation.
        Base.metadata.create_all(bind=engine)
        expected_fks, expected_checks = _capture_orm_definitions()

        _reset_empty_database()
        _run_alembic(command.upgrade, _REVISION)
        _run_alembic(command.downgrade, _PRIOR_HEAD)
        _assert_absent()  # downgrade drops all six by name

        _run_alembic(command.upgrade, _REVISION)
        # Re-added via the migration's guarded ADD bodies — assert each constraint is back AND
        # structurally identical to the ORM (referent/predicate), so a same-name divergence fails.
        _assert_matches(expected_fks, expected_checks)
    finally:
        _reset_empty_database()
        _drop_alembic_version()
