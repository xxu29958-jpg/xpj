"""Learning feedback dual tables (v1.2).

Two append-only tables back the v1.2 "建议层不污染账本" contract:

* :class:`AlgorithmDecision` — every time an algorithm produces a
  *suggestion* (proposed category, candidate duplicate pair, recurring
  pattern guess, budget P50/P75 hint), one row lands here. Writing a row
  never mutates the ledger; it only records "the system thought this".
* :class:`LedgerLearningEvent` — every time the user reacts to a
  decision (accept / reject / edit / ignore) one row lands here. Manual
  edits *without* a corresponding decision also write here with
  ``event_type='manual_override'``, so the personalisation signal is
  not lost when the user changes something the system never suggested.

Account-canonical rules:

* Both tables are tenant-scoped (``tenant_id`` = ledger id) and never
  span tenants — the learning signal is per-ledger, family ledger
  members share it.
* Neither table is a source of truth for the ledger itself. Anything
  that's actually applied to an expense still goes through the
  ordinary mutation paths (expense_service / rule_service / ...).
* Rows are append-only. ``status`` flips on the decision (``active`` /
  ``superseded`` / ``withdrawn``) but we never delete: the historical
  decision is required to interpret a later event.
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


class AlgorithmDecision(Base):
    """One suggestion produced by an algorithm at a point in time.

    ``decision_type`` is the discriminator other modules switch on:

    * ``category_suggestion`` — pending expense → category proposal
    * ``duplicate_candidate`` — candidate (expense_a, expense_b) pair
    * ``merchant_inference`` — OCR merchant alias guess
    * ``recurring_candidate`` — recurring pattern hypothesis
    * ``budget_suggestion`` — P50 / P75 derived monthly target

    ``status`` transitions:

    * ``active`` — initial state, suggestion will be shown by the UI
    * ``superseded`` — same (decision_type, subject) got a newer
      decision via :func:`supersede_decision`; ``superseded_by_id``
      points at the replacement
    * ``withdrawn`` — algorithm-governance action: owner used the
      v1.2 "one-click rollback" to retire an entire algorithm version
    * ``accepted`` — user explicitly accepted this suggestion via the
      pending-suggestion accept endpoint; the UI will not show it
      again on this subject
    * ``dismissed`` — user explicitly rejected this suggestion, OR
      the subject's lifecycle ended (expense confirmed / rejected /
      deleted) so the suggestion is no longer relevant; same UI
      effect as ``accepted`` but different reason

    Only ``active`` rows are surfaced to the UI / cleanup leaves them
    alone regardless of age. Every other status is eligible for
    retention pruning.

    ``algorithm_version`` is the small free-form string identifying
    *which* version produced this row (``category-rules-v1`` vs.
    ``category-ml-v2``). The v1.2 versioning + one-shot rollback story
    (P3 in the v1.2 backlog) reads this column.

    ``output_payload`` carries the full algorithm output as JSON text;
    consumers ``json.loads`` it. Kept as ``Text`` for parity with the
    rest of the schema (no JSON1 dependency, easy to backup-diff).
    """

    __tablename__ = "algorithm_decisions"
    __table_args__ = (
        Index(
            "ix_algorithm_decisions_tenant_type_created",
            "tenant_id",
            "decision_type",
            "created_at",
        ),
        Index(
            "ix_algorithm_decisions_tenant_subject",
            "tenant_id",
            "subject_kind",
            "subject_id",
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
        ForeignKey("ledgers.ledger_id", name="fk_algorithm_decisions_tenant"),
        nullable=False,
        index=True,
    )
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # ``subject_id`` is intentionally not a foreign key — it can point
    # to expenses / merchants / months and we don't want a hard FK that
    # blocks expense deletion. Application layer is responsible for the
    # consistency check.
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    superseded_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "algorithm_decisions.id",
            name="fk_algorithm_decisions_superseded_by",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    # v1.2 follow-up: per-row retention window (days). The cleanup
    # service in :mod:`learning_cleanup_service` deletes rows older
    # than ``created_at + retention_days``. ``0`` opts a row out of
    # retention (kept forever).
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )


class LedgerLearningEvent(Base):
    """One user reaction to an :class:`AlgorithmDecision`.

    ``decision_id`` is nullable on purpose: a user who manually edits a
    field the system never suggested still produces a learning event
    (``event_type='manual_override'``), and that signal is just as
    important as accept/reject of an explicit suggestion.

    Both ``subject_kind`` and ``subject_id`` are duplicated from the
    decision row so day-to-day queries ("show me every event on
    expense N") don't need a join.

    ``actor_account_id`` is nullable to leave room for system-emitted
    events (e.g. a decision that expired after N days with no user
    action — ``event_type='timeout_ignore'``); user-initiated events
    always populate it.
    """

    __tablename__ = "ledger_learning_events"
    __table_args__ = (
        Index(
            "ix_ledger_learning_events_tenant_type_created",
            "tenant_id",
            "event_type",
            "created_at",
        ),
        Index(
            "ix_ledger_learning_events_decision",
            "decision_id",
        ),
        Index(
            "ix_ledger_learning_events_tenant_subject",
            "tenant_id",
            "subject_kind",
            "subject_id",
        ),
        # v1.2 ops: indexed canonical marker for "has the user rejected
        # this exact advice before?" queries. Replaces the prior
        # ``before_payload.contains('{"category":"X"}')`` LIKE scan
        # with an O(index) equality lookup.
        Index(
            "ix_ledger_learning_events_signal_lookup",
            "tenant_id",
            "event_type",
            "signal_type",
            "signal_hash",
            "created_at",
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
        ForeignKey("ledgers.ledger_id", name="fk_ledger_learning_events_tenant"),
        nullable=False,
        index=True,
    )
    decision_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "algorithm_decisions.id",
            name="fk_ledger_learning_events_decision",
        ),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("accounts.id", name="fk_ledger_learning_events_actor"),
        nullable=True,
    )
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v1.2 ops (signal_hash indexing): structured marker fields that
    # back the "has the user rejected this exact advice?" lookup.
    # JSON columns above remain for audit / human inspection; the
    # query-path filters on these instead of LIKE-scanning JSON text.
    #
    # ``signal_type`` mirrors ``decision_type`` from the registry
    # (``category_suggestion`` / ``duplicate_candidate`` / ...). The
    # column is nullable because manual_override events without a
    # corresponding decision don't always have a typed signal.
    #
    # ``signal_hash`` is the SHA-256 hex of the canonical JSON encoding
    # of the marker dict (e.g. ``{"category": "餐饮"}`` for category
    # suggestions). Equal hashes mean "logically the same advice".
    #
    # ``signal_payload`` is the same marker as a readable JSON string
    # so Owner Console / debugging can show "what the user reacted to"
    # without decoding ``before_payload`` and guessing which fields
    # actually mattered.
    signal_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signal_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )
