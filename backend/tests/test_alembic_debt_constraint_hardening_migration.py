"""PG round-trip of 20260618_0001 (ADR-0049 #4 member-repayment + draft constraint backstops).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries the FKs +
CHECKs) then ``alembic stamp head``, so the migration's ADD bodies never run on the normal
path — a divergence between the migration and the ORM would ship UNDETECTED by deployment.
This drives the migration directly on PostgreSQL: create_all → stamp head → downgrade past
20260618_0001 (drops the constraints) → upgrade to head (re-adds them via the migration body).

It asserts the migration-built constraints are STRUCTURALLY IDENTICAL to the ORM-built ones —
FK referent table/columns and CHECK predicate sqltext, not just the constraint NAME — so a
same-name migration↔ORM divergence (a wrong FK referent or a tautology CHECK predicate, the
exact failure mode the single-source design guards and which no machine diff otherwise
enforces) fails HERE.

The ``create_all`` step is ALSO the only automated proof that the nullable circular FK pair
(repayments.proposal_id <-> member_repayment_proposals.committed_repayment_id) builds on a
fresh DB — without ``use_alter=True`` on the committed_repayment_id side it would raise
CircularDependencyError at table-sort time.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``): it issues DDL via its own
``engine.begin()`` connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

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


def test_debt_constraint_backstops_round_trip_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        # create_all builds the final ORM shape on a fresh DB — and proves the circular
        # FK pair (use_alter on committed_repayment_id) does NOT deadlock table creation.
        Base.metadata.create_all(bind=engine)
        expected_fks, expected_checks = _capture_orm_definitions()

        _run_alembic(command.stamp, _REVISION)
        _run_alembic(command.downgrade, _PRIOR_HEAD)
        _assert_absent()  # downgrade drops all six by name

        _run_alembic(command.upgrade, "head")
        # Re-added via the migration's guarded ADD bodies — assert each constraint is back AND
        # structurally identical to the ORM (referent/predicate), so a same-name divergence fails.
        _assert_matches(expected_fks, expected_checks)
    finally:
        _reset_empty_database()
        _drop_alembic_version()
