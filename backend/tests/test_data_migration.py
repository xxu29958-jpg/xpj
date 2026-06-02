"""ADR-0041 phase-2 data-migration unit tests (dialect-independent).

These build their own throwaway SQLite engines (not the suite's test DB), so
they run identically on the SQLite and PostgreSQL lanes. The PostgreSQL-only
landmines (setval / timestamptz / session_replication_role) are exercised
end-to-end by ``scripts/migration_roundtrip_check.py`` in the backend-postgres
CI lane.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (populate Base.metadata)
from app.database import Base, migrate
from app.database.data_migration import (
    _accepted_bill_split_counts,
    _attach_utc,
    _setval_args,
    _tz_columns,
)
from app.models import AppMeta, BillSplitInvitation, Expense
from app.services.time_service import now_utc


def test_attach_utc_only_touches_naive_datetimes() -> None:
    naive = datetime(2026, 6, 2, 12, 0, 0)
    assert _attach_utc(naive) == datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)

    aware = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)
    assert _attach_utc(aware) is aware

    assert _attach_utc("2026-06-02") == "2026-06-02"
    assert _attach_utc(None) is None


def test_tz_columns_picks_timestamptz_not_date() -> None:
    columns = _tz_columns(Base.metadata.tables["expenses"])
    assert "expense_time" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
    # Date-only columns are tz-naive by design and must not be UTC-attached.
    assert "exchange_rate_date" not in columns


def _seed(source_url: str) -> None:
    engine = create_engine(source_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for amount in (1280, 3680):
            now = now_utc()
            db.add(
                Expense(
                    tenant_id="owner",
                    amount_cents=amount,
                    status="confirmed",
                    expense_time=now,
                    created_at=now,
                    updated_at=now,
                    confirmed_at=now,
                )
            )
        db.commit()
    engine.dispose()


def test_migrate_sqlite_roundtrip_copies_and_reconciles(tmp_path) -> None:
    source_url = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'tgt.db').as_posix()}"
    _seed(source_url)

    report = migrate(source_url, target_url)

    assert report.ok, [check for check in report.checks if check.status == "error"]
    # Every table gets a copy + rowcount + sample check; expenses + the money
    # check are in there too.
    assert any(check.code == "money:confirmed_by_ledger" for check in report.checks)

    target_engine = create_engine(target_url)
    with Session(target_engine) as db:
        amounts = sorted(db.scalars(select(Expense.amount_cents)).all())
    target_engine.dispose()
    assert amounts == [1280, 3680]


def _invitation(
    status: str, receiver_ledger: str | None, received_expense_id: int | None
) -> BillSplitInvitation:
    now = now_utc()
    return BillSplitInvitation(
        sender_account_id=1,
        sender_ledger_id="sender",
        sender_member_id=1,
        sender_expense_id=1,
        sender_display_name="A",
        receiver_account_id=2,
        amount_cents=500,
        home_currency_code="CNY",
        original_currency_code="CNY",
        status=status,
        expires_at=now,
        created_at=now,
        receiver_ledger_id=receiver_ledger,
        receiver_member_id=9 if receiver_ledger else None,
        received_expense_id=received_expense_id,
        accepted_at=now if status == "accepted" else None,
    )


def test_bill_split_received_count_reconciles_only_accepted(tmp_path) -> None:
    """ADR-0041 line 68: the bill_split received-count backstop counts only
    'accepted' invitations, keyed by receiver ledger; the copy preserves it."""
    source_url = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'tgt.db').as_posix()}"

    source_engine = create_engine(source_url)
    Base.metadata.create_all(source_engine)
    with Session(source_engine) as db:
        db.add_all(
            [
                _invitation("accepted", "ledger_a", 101),
                _invitation("accepted", "ledger_a", 102),
                _invitation("accepted", "ledger_b", 103),
                _invitation("invited", None, None),
                _invitation("rejected", None, None),
            ]
        )
        db.commit()
    source_engine.dispose()

    report = migrate(source_url, target_url)
    assert report.ok, [check for check in report.checks if check.status == "error"]

    received = next(c for c in report.checks if c.code == "bill_split:received_count")
    assert received.status == "ok"

    target_engine = create_engine(target_url)
    with target_engine.connect() as target:
        counts = _accepted_bill_split_counts(target)
    target_engine.dispose()
    # invited / rejected excluded; accepted grouped by receiver ledger.
    assert counts == {"ledger_a": 2, "ledger_b": 1}


def test_no_naive_datetime_columns_exist() -> None:
    """``_tz_columns`` only UTC-attaches ``DateTime(timezone=True)`` columns. A
    naive ``DateTime`` instant column added later would be silently skipped and
    mis-stored against a PostgreSQL ``timestamptz`` (the month-boundary offset
    bug this project has hit twice). Lock the invariant: no naive instants."""
    naive = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, DateTime) and not getattr(column.type, "timezone", False)
    ]
    assert not naive, f"these DateTime columns must be timezone=True: {naive}"


def test_setval_args_empty_table_starts_at_one() -> None:
    """Empty table -> first new id is 1 (not 2); non-empty -> next id is max+1."""
    assert _setval_args(0) == (1, False)  # nextval -> 1
    assert _setval_args(5) == (5, True)  # nextval -> 6


def test_sample_reconcile_catches_tampered_highest_id_row(tmp_path) -> None:
    """Head+tail sampling: a corrupted high-id row — outside the lowest-20 head
    window — is still caught (a head-only sampler would falsely pass)."""
    source_url = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'tgt.db').as_posix()}"

    source_engine = create_engine(source_url)
    Base.metadata.create_all(source_engine)
    with Session(source_engine) as db:
        for i in range(45):  # > 2 * _SAMPLE_ROWS, so a gap exists between head and tail
            now = now_utc()
            db.add(
                Expense(
                    tenant_id="owner",
                    amount_cents=100 + i,
                    status="confirmed",
                    expense_time=now,
                    created_at=now,
                    updated_at=now,
                    confirmed_at=now,
                )
            )
        db.commit()
        highest_id = max(db.scalars(select(Expense.id)).all())
    source_engine.dispose()

    assert migrate(source_url, target_url).ok

    target_engine = create_engine(target_url)
    with target_engine.begin() as conn:
        conn.execute(
            text("UPDATE expenses SET amount_cents = 999999 WHERE id = :i"), {"i": highest_id}
        )
    target_engine.dispose()

    report = migrate(source_url, target_url, copy=False)
    sample = next(c for c in report.checks if c.code == "sample:expenses")
    assert sample.status == "error"
    assert str(highest_id) in sample.message
    assert not report.ok


def test_sample_reconcile_covers_natural_pk_tables(tmp_path) -> None:
    """Natural string-PK tables (app_meta) are field-sampled by primary key, not
    only row-counted; a tampered value is caught."""
    source_url = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    target_url = f"sqlite:///{(tmp_path / 'tgt.db').as_posix()}"

    source_engine = create_engine(source_url)
    Base.metadata.create_all(source_engine)
    with Session(source_engine) as db:
        db.add(AppMeta(key="schema_version", value="v0.3", updated_at=now_utc()))
        db.commit()
    source_engine.dispose()

    assert migrate(source_url, target_url).ok

    target_engine = create_engine(target_url)
    with target_engine.begin() as conn:
        conn.execute(text("UPDATE app_meta SET value = 'TAMPERED' WHERE key = 'schema_version'"))
    target_engine.dispose()

    report = migrate(source_url, target_url, copy=False)
    sample = next(c for c in report.checks if c.code == "sample:app_meta")
    assert sample.status == "error"
    assert not report.ok
