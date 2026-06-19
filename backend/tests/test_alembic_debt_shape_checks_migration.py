"""PG round-trip of 20260619_0001 (ADR-0049 P2 Debt 母表 shape CHECK backstops).

``init_db`` on a fresh DB runs ``create_all`` (the current ORM already carries the CHECKs) then
``alembic stamp head``, so the migration's ADD bodies never run on the normal path — a divergence
between the migration and the ORM would ship UNDETECTED by deployment. This drives the migration
directly on PostgreSQL: create_all → stamp 20260619_0001 → downgrade past it (drops the two
CHECKs) → upgrade to head (re-adds them via the migration body).

It asserts the migration-built CHECK predicate sqltext is STRUCTURALLY IDENTICAL to the ORM-built
one (not just the constraint NAME) — so a same-name migration↔ORM divergence (e.g. a tautology
predicate, the exact failure mode the single-source design guards and which no machine diff
otherwise enforces) fails HERE.

Marked ``real_db`` (conftest ``_PG_REAL_DB_NODES``): it issues DDL via its own ``engine.begin()``
connections outside the per-test transaction.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.database import Base, engine

_PRIOR_HEAD = "20260618_0001"
_REVISION = "20260619_0001"

# (check_name,) on the debts table
_CHECKS = (
    "ck_debts_member_has_account",
    "ck_debts_bill_split_has_source_id",
)


def _check_sqltext(name: str) -> str | None:
    for cc in inspect(engine).get_check_constraints("debts"):
        if cc["name"] == name:
            return cc.get("sqltext")
    return None


def _capture_orm_checks() -> dict[str, str]:
    """After create_all: the EXPECTED (ORM single-source) CHECK predicate text — and assert each
    is actually present, so the baseline itself is verified, not merely captured."""
    checks = {name: _check_sqltext(name) for name in _CHECKS}
    for name in _CHECKS:
        assert checks[name], f"ORM CHECK {name} missing on debts after create_all"
    return checks


def _assert_matches(expected: dict[str, str]) -> None:
    for name in _CHECKS:
        assert _check_sqltext(name) == expected[name], (
            f"migration CHECK {name} predicate diverged from ORM: "
            f"{_check_sqltext(name)!r} != {expected[name]!r}"
        )


def _assert_absent() -> None:
    for name in _CHECKS:
        assert _check_sqltext(name) is None, f"CHECK {name} should be dropped from debts"


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


def test_debt_shape_checks_round_trip_on_postgres() -> None:
    from alembic import command

    _reset_empty_database()
    _drop_alembic_version()
    try:
        Base.metadata.create_all(bind=engine)
        expected = _capture_orm_checks()

        _run_alembic(command.stamp, _REVISION)
        _run_alembic(command.downgrade, _PRIOR_HEAD)
        _assert_absent()  # downgrade drops both by name

        _run_alembic(command.upgrade, "head")
        # Re-added via the migration's guarded ADD bodies — assert each CHECK is back AND its
        # predicate is structurally identical to the ORM (not just the name), so a same-name
        # divergence (tautology / wrong column) fails here.
        _assert_matches(expected)
    finally:
        _reset_empty_database()
        _drop_alembic_version()
