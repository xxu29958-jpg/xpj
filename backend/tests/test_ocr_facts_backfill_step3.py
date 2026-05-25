"""v1.2 OCR single-source migration — step 3 backfill.

Verifies the ``bb00c453bf29`` data migration that inserts a
``legacy_expense_column`` fact for every expense that still relies on
``expenses.raw_text`` as its only OCR text source.

The migration's logic lives in ``_backfill_legacy_raw_text`` so these
tests drive it with the test engine instead of round-tripping through
alembic. That keeps the test fast *and* stays in sync with what
``upgrade()`` actually runs (the wrapper is a one-liner).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.database import SessionLocal, engine
from app.models import Expense, OcrFact
from app.services.learning_service import (
    OcrFactDraft,
    read_ocr_text,
    record_ocr_fact,
)
from migrations.versions.bb00c453bf29_backfill_expense_raw_text_to_ocr_facts import (
    LEGACY_PROVIDER,
    _backfill_legacy_raw_text,
)


def _seed_expense(
    *,
    tenant_id: str = "owner",
    raw_text: str | None = "shop receipt 25.50",
    created_at: datetime | None = None,
) -> int:
    """Insert a minimal expense and return its id. Uses the same
    pattern as the read-single-source tests so the schema stays in
    sync."""

    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            source="pytest",
            raw_text=raw_text,
            status="pending",
        )
        if created_at is not None:
            expense.created_at = created_at
            expense.updated_at = created_at
        db.add(expense)
        db.commit()
        return expense.id


def _all_facts(expense_id: int) -> list[OcrFact]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(OcrFact).where(OcrFact.expense_id == expense_id)
            )
        )


def test_backfill_inserts_legacy_fact_when_no_facts_exist(
    *, identity,
) -> None:
    expense_id = _seed_expense(raw_text="legacy column body")
    with engine.begin() as conn:
        inserted = _backfill_legacy_raw_text(conn)
    assert inserted == 1
    facts = _all_facts(expense_id)
    assert len(facts) == 1
    assert facts[0].ocr_provider == LEGACY_PROVIDER
    assert facts[0].raw_text == "legacy column body"
    assert facts[0].tenant_id == "owner"
    # retention_days default must come through so cleanup_service can
    # treat backfilled rows like any other fact.
    assert facts[0].retention_days == 180


def test_backfill_skips_expenses_with_existing_text_fact(
    *, identity,
) -> None:
    expense_id = _seed_expense(raw_text="legacy column body")
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="real ocr text",
            ),
        )
        db.commit()

    with engine.begin() as conn:
        inserted = _backfill_legacy_raw_text(conn)
    assert inserted == 0
    facts = _all_facts(expense_id)
    assert len(facts) == 1
    assert facts[0].ocr_provider == "local_llm"
    assert facts[0].raw_text == "real ocr text"


def test_backfill_adds_legacy_when_existing_fact_is_text_empty(
    *, identity,
) -> None:
    """An OCR pass that produced structured data but no raw_text leaves
    the expense effectively text-less from the fact's point of view.
    The backfill must still insert a legacy row so step-4 can drop the
    column fallback without losing the text."""

    earlier = datetime(2026, 5, 1, tzinfo=UTC)
    expense_id = _seed_expense(
        raw_text="legacy column body", created_at=earlier
    )
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text=None,
                parsed_amount_cents=2550,
            ),
            now=earlier + timedelta(minutes=5),
        )
        db.commit()

    with engine.begin() as conn:
        inserted = _backfill_legacy_raw_text(conn)
    assert inserted == 1

    facts = _all_facts(expense_id)
    assert len(facts) == 2
    by_provider = {f.ocr_provider: f for f in facts}
    assert by_provider[LEGACY_PROVIDER].raw_text == "legacy column body"
    assert by_provider["local_llm"].raw_text is None

    # The latest-fact selector must now pick the legacy row — its
    # extracted_at ties the empty fact's, but the higher autoincrement
    # id wins the (extracted_at desc, id desc) tie-break.
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        # Clear the legacy column so we can prove the helper found the
        # text via the facts table, not the fallback.
        expense.raw_text = None
        text = read_ocr_text(db, tenant_id="owner", expense=expense)
    assert text == "legacy column body"


def test_backfill_is_idempotent(*, identity) -> None:
    expense_id = _seed_expense(raw_text="legacy column body")
    with engine.begin() as conn:
        first = _backfill_legacy_raw_text(conn)
        second = _backfill_legacy_raw_text(conn)
    assert first == 1
    assert second == 0
    facts = _all_facts(expense_id)
    assert len(facts) == 1


def test_backfill_skips_empty_or_null_raw_text(*, identity) -> None:
    null_expense = _seed_expense(raw_text=None)
    empty_expense = _seed_expense(raw_text="")
    with engine.begin() as conn:
        inserted = _backfill_legacy_raw_text(conn)
    assert inserted == 0
    assert _all_facts(null_expense) == []
    assert _all_facts(empty_expense) == []


def test_backfill_is_tenant_scoped(*, identity) -> None:
    """Two tenants both have backfill candidates. Each expense gets a
    fact with the right tenant_id — no cross-pollution."""

    owner_expense = _seed_expense(tenant_id="owner", raw_text="owner-text")
    tester_expense = _seed_expense(
        tenant_id="tester_1", raw_text="tester-text"
    )
    with engine.begin() as conn:
        inserted = _backfill_legacy_raw_text(conn)
    assert inserted == 2

    owner_facts = _all_facts(owner_expense)
    tester_facts = _all_facts(tester_expense)
    assert len(owner_facts) == 1
    assert owner_facts[0].tenant_id == "owner"
    assert owner_facts[0].raw_text == "owner-text"
    assert len(tester_facts) == 1
    assert tester_facts[0].tenant_id == "tester_1"
    assert tester_facts[0].raw_text == "tester-text"


def test_downgrade_removes_only_legacy_rows(*, identity) -> None:
    """Downgrade must drop only ``legacy_expense_column`` rows. Real
    OCR facts written by ``record_ocr_fact`` are untouched, otherwise
    a rollback would lose user data."""

    expense_id = _seed_expense(raw_text="legacy column body")
    with SessionLocal() as db:
        # A real provider's fact — must survive downgrade.
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="real ocr text",
            ),
        )
        # An additional legacy row inserted directly (simulating what
        # the migration would have written before downgrade).
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider=LEGACY_PROVIDER,
                raw_text="legacy column body",
            ),
        )
        db.commit()

    # Mirror the migration's downgrade() against the test engine.
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM ocr_facts WHERE ocr_provider = :provider"),
            {"provider": LEGACY_PROVIDER},
        )

    facts = _all_facts(expense_id)
    assert len(facts) == 1
    assert facts[0].ocr_provider == "local_llm"
    assert facts[0].raw_text == "real ocr text"
