"""backfill expense.raw_text into ocr_facts.

Revision ID: bb00c453bf29
Revises: c5b9a324c535
Create Date: 2026-05-25

v1.2 OCR single-source migration **step 3 of 5**. Steps 1 (helper) and
2 (consumer switch) are already on main. This revision inserts a
``ocr_provider='legacy_expense_column'`` fact for every expense that
still relies on ``expenses.raw_text`` as its only OCR text source —
i.e. expenses where ``raw_text`` is non-empty but no existing fact
carries non-empty ``raw_text``. After this lands, every consumer that
goes through ``read_ocr_text`` finds a fact for those rows, so step 4
can drop the legacy-column fallback without losing data.

Design notes:

* **Idempotent** — re-running the migration is a no-op because the
  inserted legacy rows now carry non-empty ``raw_text``, which causes
  the ``NOT EXISTS`` guard to skip them on the second pass.
* **Real OCR wins** — if a real provider has already populated a fact
  with non-empty ``raw_text`` (the normal case for any expense that
  was OCR'd post-step-1), no legacy row is inserted. The latest-fact
  selector keeps returning the real provider's text.
* **Empty fact + legacy text** — an expense whose only fact has
  ``raw_text IS NULL/''`` but whose ``expense.raw_text`` is non-empty
  *does* get a legacy row. ``extracted_at`` is set to
  ``coalesce(MAX(existing fact extracted_at), expense.created_at)``
  so the new row ties the latest existing row on extracted_at and
  wins the ``(extracted_at DESC, id DESC)`` tie-break via its
  autoincrement id. Future real OCR runs use ``now_utc()`` which is
  strictly larger, so they still take over after the migration.
* **Downgrade safe** — every backfilled row carries the sentinel
  provider, so the reverse direction is a plain DELETE that leaves
  real OCR facts alone.

Performance: home-server SQLite, single-table INSERT...SELECT with a
correlated subquery for ``extracted_at``. We materialise the candidate
list in Python so we can attach per-row UUIDs (SQLite has no native
generator) without changing the read shape of ``ocr_facts``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb00c453bf29"
down_revision: str | Sequence[str] | None = "c5b9a324c535"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEGACY_PROVIDER = "legacy_expense_column"


def _backfill_legacy_raw_text(bind: sa.engine.Connection) -> int:
    """Insert a legacy_expense_column fact for every expense that
    still needs one. Returns the number of rows inserted.

    Exposed for tests to drive the same logic without round-tripping
    through alembic.
    """

    candidates = bind.execute(
        sa.text(
            """
            SELECT
                e.id AS expense_id,
                e.tenant_id AS tenant_id,
                e.raw_text AS raw_text,
                COALESCE(
                    (
                        SELECT MAX(f.extracted_at)
                        FROM ocr_facts f
                        WHERE f.expense_id = e.id
                          AND f.tenant_id = e.tenant_id
                    ),
                    e.created_at
                ) AS extracted_at
            FROM expenses e
            WHERE e.raw_text IS NOT NULL
              AND e.raw_text <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM ocr_facts f
                  WHERE f.expense_id = e.id
                    AND f.tenant_id = e.tenant_id
                    AND f.raw_text IS NOT NULL
                    AND f.raw_text <> ''
              )
            """
        )
    ).mappings().all()

    if not candidates:
        return 0

    now = datetime.now(UTC)
    rows = [
        {
            "public_id": str(uuid4()),
            "tenant_id": row["tenant_id"],
            "expense_id": row["expense_id"],
            "ocr_provider": LEGACY_PROVIDER,
            "raw_text": row["raw_text"],
            "extracted_at": row["extracted_at"] or now,
            "created_at": now,
            "retention_days": 180,
        }
        for row in candidates
    ]

    bind.execute(
        sa.text(
            """
            INSERT INTO ocr_facts (
                public_id, tenant_id, expense_id, ocr_provider,
                raw_text, extracted_at, created_at, retention_days
            )
            VALUES (
                :public_id, :tenant_id, :expense_id, :ocr_provider,
                :raw_text, :extracted_at, :created_at, :retention_days
            )
            """
        ),
        rows,
    )
    return len(rows)


def upgrade() -> None:
    _backfill_legacy_raw_text(op.get_bind())


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM ocr_facts WHERE ocr_provider = :provider"
        ).bindparams(provider=LEGACY_PROVIDER)
    )
