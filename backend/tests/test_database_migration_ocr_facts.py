"""ocr_facts composite (expense_id, tenant_id) FK migration."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.database._migrations._ocr_facts import (
    _migrate_ocr_facts,
    _ocr_facts_has_composite_expense_fk,
)
from app.models import Account, Expense, Ledger

_LEGACY_OCR_FACTS_DDL = """
CREATE TABLE ocr_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    expense_id INTEGER NOT NULL,
    ocr_provider VARCHAR(64) NOT NULL,
    ocr_model VARCHAR(120),
    raw_text TEXT,
    parsed_amount_cents INTEGER,
    parsed_merchant VARCHAR(255),
    parsed_category VARCHAR(64),
    parsed_expense_time DATETIME,
    parse_confidence FLOAT,
    extracted_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL,
    retention_days INTEGER NOT NULL DEFAULT 180,
    CONSTRAINT ck_ocr_facts_provider_valid CHECK (
        ocr_provider IN ('empty','mock','rapidocr','local_llm','manual_text','legacy_expense_column')
    ),
    CONSTRAINT fk_ocr_facts_tenant FOREIGN KEY (tenant_id) REFERENCES ledgers(ledger_id),
    CONSTRAINT fk_ocr_facts_expense FOREIGN KEY (expense_id) REFERENCES expenses(id)
)
"""


def _seed_two_ledgers_and_expense() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        db.add(Ledger(ledger_id="other_tenant", name="other", owner_account_id=owner.id))
        expense = Expense(
            tenant_id="owner",
            amount_cents=100,
            merchant="m",
            category="其他",
            source="pytest",
            raw_text="",
            status="confirmed",
            expense_time=datetime(2026, 5, 1, tzinfo=UTC),
            confirmed_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        db.add(expense)
        db.commit()
        return expense.id


def _install_legacy_ocr_facts(expense_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ocr_facts"))
        conn.execute(text(_LEGACY_OCR_FACTS_DDL))
        conn.execute(text("CREATE UNIQUE INDEX ix_ocr_facts_public_id ON ocr_facts (public_id)"))
        conn.execute(
            text("CREATE INDEX ix_ocr_facts_tenant_expense ON ocr_facts (tenant_id, expense_id)")
        )
        # Valid fact: same ledger as the expense.
        conn.execute(
            text(
                "INSERT INTO ocr_facts "
                "(public_id, tenant_id, expense_id, ocr_provider, extracted_at, created_at) "
                "VALUES ('valid-1', 'owner', :eid, 'mock', '2026-05-01 00:00:00', '2026-05-01 00:00:00')"
            ),
            {"eid": expense_id},
        )
        # Cross-tenant orphan: the single-column legacy FK allowed it, the new
        # composite FK forbids it (expense actually belongs to 'owner').
        conn.execute(
            text(
                "INSERT INTO ocr_facts "
                "(public_id, tenant_id, expense_id, ocr_provider, extracted_at, created_at) "
                "VALUES ('orphan-1', 'other_tenant', :eid, 'mock', '2026-05-01 00:00:00', '2026-05-01 00:00:00')"
            ),
            {"eid": expense_id},
        )


def test_ocr_facts_migration_adds_composite_fk_and_drops_cross_tenant_orphans(
    *, identity
) -> None:
    expense_id = _seed_two_ledgers_and_expense()
    _install_legacy_ocr_facts(expense_id)

    with engine.begin() as conn:
        assert _ocr_facts_has_composite_expense_fk(conn) is False

    with engine.begin() as conn:
        _migrate_ocr_facts(conn, {"ocr_facts", "expenses", "ledgers"})

    with engine.begin() as conn:
        assert _ocr_facts_has_composite_expense_fk(conn) is True
        surviving = {
            row["public_id"]
            for row in conn.execute(
                text("SELECT public_id FROM ocr_facts")
            ).mappings()
        }
        assert surviving == {"valid-1"}  # cross-tenant orphan dropped
        violations = list(
            conn.execute(text("PRAGMA foreign_key_check(ocr_facts)")).mappings()
        )
        assert violations == []


def test_ocr_facts_migration_is_idempotent(*, identity) -> None:
    expense_id = _seed_two_ledgers_and_expense()
    _install_legacy_ocr_facts(expense_id)

    with engine.begin() as conn:
        _migrate_ocr_facts(conn, {"ocr_facts", "expenses", "ledgers"})
    # Second pass must detect the composite FK and no-op (no rename/rebuild).
    with engine.begin() as conn:
        _migrate_ocr_facts(conn, {"ocr_facts", "expenses", "ledgers"})
        assert _ocr_facts_has_composite_expense_fk(conn) is True
        # The ocr_facts_legacy rebuild table must not be left behind.
        leftover = conn.execute(
            text("SELECT name FROM sqlite_master WHERE name = 'ocr_facts_legacy'")
        ).first()
        assert leftover is None
