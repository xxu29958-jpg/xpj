"""OCR facts table — append-only snapshot of every OCR extraction (v1.2 P0).

Goal: separate "what the OCR pipeline saw" from "what the user confirmed".
Today the ``expenses`` row stores both (``raw_text`` / ``confidence`` /
``ocr_draft_fields`` are OCR-side; ``amount_cents`` / ``merchant`` /
``category`` are user-confirmed but seeded from OCR). Future ledger
mutations should only ever touch the confirmed side, while learning
signals (P1) read the OCR side via this table.

Step-1 of the rollout (this revision) introduces the table and a write
helper. Step-2 (later) wires the helper into the three OCR paths
(``enrich_pending_expense``, ``retry_expense_ocr``,
``recognize_expense_text``). Step-3 (much later) migrates the legacy
columns off ``expenses`` once every consumer has been moved.

The table is append-only — each successful OCR extraction creates a
new row, with ``extracted_at`` distinguishing them. That lets us see
"OCR ran twice on the same expense, the second run was a manual
retry" by row count alone, no diff arithmetic needed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class OcrFact(Base):
    """One OCR extraction outcome attached to an expense.

    ``ocr_provider`` / ``ocr_model`` capture *which* component produced
    the row, so per-version learning ("local_llm v3 is better than
    local_llm v2 on amount detection") becomes a SQL aggregation. The
    parsed-* columns hold the structured guess; ``raw_text`` keeps the
    full text the user can search if the structured guess is wrong.
    """

    __tablename__ = "ocr_facts"
    __table_args__ = (
        Index("ix_ocr_facts_tenant_expense", "tenant_id", "expense_id"),
        Index(
            "ix_ocr_facts_tenant_provider_extracted",
            "tenant_id",
            "ocr_provider",
            "extracted_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36),
        default=lambda: str(uuid4()),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_ocr_facts_tenant"),
        nullable=False,
        index=True,
    )
    expense_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("expenses.id", name="fk_ocr_facts_expense"),
        nullable=False,
        index=True,
    )
    ocr_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parsed_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_expense_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parse_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
