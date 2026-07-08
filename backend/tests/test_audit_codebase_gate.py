"""Regression tests for the codebase audit hard gate."""

from __future__ import annotations

import ast
import importlib
import sys
import textwrap
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load() -> object:
    return importlib.reload(importlib.import_module("_audit_codebase"))


def _load_gate() -> object:
    return importlib.reload(importlib.import_module("codebase_audit_gate"))


def _n_plus_one_hits(source: str) -> list:
    mod = _load()
    items: list = []
    tree = ast.parse(textwrap.dedent(source))
    mod._NPlusOneVisitor(Path("fixture.py"), items).visit(tree)
    return items


_N_PLUS_ONE_FLAGGED_CASES = {
    "business loop": """
        def load_rows(db, rows):
            for row in rows:
                db.scalar(select(Foo).where(Foo.id == row.foo_id))
    """,
    "named retry body query": """
        def retry_body_query(db):
            for attempt in range(MAX_RETRIES):
                db.scalar(select(Row).limit(1))
    """,
    "discard retry body query": """
        def discard_retry_body_query(db):
            for _ in range(MAX_RETRIES):
                db.scalar(select(Row).limit(1))
    """,
    "range len integrity recovery": """
        def range_len_integrity_query(db, rows):
            for index in range(len(rows)):
                try:
                    db.flush()
                except IntegrityError:
                    db.scalar(select(Row).limit(1))
    """,
    "outer business loop retry recovery": """
        def nested_retry_recovery_query(db, rows):
            for row in rows:
                for attempt in range(MAX_RETRIES):
                    try:
                        db.flush()
                    except IntegrityError:
                        db.scalar(select(Row).where(Row.id == row.id))
    """,
    "dynamic retry recovery": """
        def dynamic_retry_recovery_query(db, config):
            for attempt in range(config.retries):
                try:
                    db.flush()
                except IntegrityError:
                    db.scalar(select(Row).limit(1))
    """,
    "mixed retry budget recovery": """
        def mixed_retry_recovery_query(db, rows):
            for attempt in range(max(MAX_RETRIES, len(rows))):
                try:
                    db.flush()
                except IntegrityError:
                    db.scalar(select(Row).limit(1))
    """,
    "while true query": """
        def while_true_query(db):
            while True:
                db.scalar(select(Row).limit(1))
                break
    """,
    "while condition query": """
        def while_condition_query(db):
            while db.scalar(select(Row).limit(1)):
                break
    """,
    "page loop item query": """
        def page_loop_item_query(db, batch_size):
            last_id = 0
            while True:
                rows = list(
                    db.scalars(
                        select(Row)
                        .where(Row.id > last_id)
                        .order_by(Row.id.asc())
                        .limit(batch_size)
                    )
                )
                if not rows:
                    break
                last_id = rows[-1].id
                for row in rows:
                    db.scalar(select(Item).where(Item.row_id == row.id))
    """,
    "limited query in business for loop": """
        def limited_query_by_parent(db, ledgers):
            for ledger in ledgers:
                rows = list(
                    db.scalars(
                        select(Expense)
                        .where(Expense.ledger_id == ledger.id)
                        .order_by(Expense.id.asc())
                        .limit(10)
                    )
                )
                consume(rows)
    """,
    "limited query in non-keyset while loop": """
        def limited_query_while_waiting(db, ledger):
            keep_loading = True
            while keep_loading:
                rows = list(
                    db.scalars(
                        select(Expense)
                        .where(Expense.ledger_id == ledger.id)
                        .order_by(Expense.id.asc())
                        .limit(10)
                    )
                )
                keep_loading = False
                consume(rows)
    """,
}

_N_PLUS_ONE_IGNORED_CASES = {
    "named retry budget": """
        def allocate(db):
            for attempt in range(MAX_RETRIES):
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    db.scalar(select(Row).limit(1))
                    continue
    """,
    "discard retry budget": """
        def allocate_discard(db):
            for _ in range(MAX_RETRIES):
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    db.scalar(select(Row).limit(1))
                    continue
    """,
    "two-arg retry budget": """
        def allocate_one_indexed(db):
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    db.scalar(select(Row).limit(1))
                    continue
    """,
    "top-level keyset page fetch": """
        def paged(db, batch_size):
            last_id = 0
            while True:
                rows = list(
                    db.scalars(
                        select(Row)
                        .where(Row.id > last_id)
                        .order_by(Row.id.asc())
                        .limit(batch_size)
                    )
                )
                if not rows:
                    break
                last_id = rows[-1].id
    """,
}


def test_codebase_known_debt_baseline_returns_zero() -> None:
    gate = _load_gate()
    assert gate.evaluate_debt(dict(gate.CODEBASE_DEBT_LIMITS)) == 0


def test_codebase_debt_regression_returns_one() -> None:
    gate = _load_gate()
    counts = dict(gate.CODEBASE_DEBT_LIMITS)
    counts["long_functions"] += 1
    assert gate.evaluate_debt(counts) == 1


def test_codebase_main_propagates_audit_regression(monkeypatch) -> None:
    mod = _load()
    gate = _load_gate()

    def fake_audit() -> dict[str, int]:
        counts = dict(gate.CODEBASE_DEBT_LIMITS)
        counts["long_functions"] += 1
        return counts

    monkeypatch.setattr(mod, "AUDITS", (fake_audit,))
    assert mod.main() == 1


def test_n_plus_one_flags_business_loop_query() -> None:
    for name, source in _N_PLUS_ONE_FLAGGED_CASES.items():
        assert len(_n_plus_one_hits(source)) == 1, name


def test_n_plus_one_ignores_bounded_integrity_recovery_read() -> None:
    for name, source in _N_PLUS_ONE_IGNORED_CASES.items():
        assert _n_plus_one_hits(source) == [], name
