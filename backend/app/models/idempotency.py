"""Request idempotency keys — ADR-0042 §4.1.

A dedicated table because an UPDATE (the bulk of the outbox-routed mutate
surface) has no freshly-inserted row to hang a key on, unlike the INSERT-only
``draft_idempotency_key`` on ``expenses``.

One row per ``(tenant_id, idempotency_key)``. The key is generated client-side
at mutation-intent time (UUID v4) and carried on both the direct request and,
if that fails with ``IOException``, the persisted outbox row that replays it.
The server claims the key BEFORE the OCC ``row_version`` check (see
``app.services.idempotency``); a replay that hits a ``succeeded`` row returns
the resource's canonical current state without re-running the OCC claim, which
is what closes the committed-but-unseen false-409 gap.

``status`` is the concurrency placeholder: an in-flight claim writes
``in_progress`` first (atomic unique-conflict claim), flips to ``succeeded`` in
the SAME transaction as the business mutation. ``resource_type`` /
``resource_id`` locate an ordinary mutated resource so a replay can re-serialise
its canonical current shape. Aggregate commands with no single canonical
resource may store only their successful typed result in ``response_body``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class ApiIdempotencyKey(Base):
    """One request-idempotency record for an outbox-routed mutation."""

    __tablename__ = "api_idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'succeeded')",
            name="ck_api_idempotency_keys_status_valid",
        ),
        # ADR-0042 §4.1: the key is unique per tenant, not globally — the same
        # client-generated UUID across two ledgers stays distinct. Composite so
        # ``(tenant_id)`` lookups ride the leftmost prefix (no separate FK index
        # needed). Unique so the atomic insert-or-conflict claim works.
        Index(
            "ix_api_idempotency_keys_tenant_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
        # Drives the expiry GC sweep (deferred to a later slice; ADR-0042 §4.10).
        Index("ix_api_idempotency_keys_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_api_idempotency_keys_tenant"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # canonical(operation + target + body + expected_row_version) sha256 hex (64).
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Locate an ordinary mutated resource so replay can re-serialise current state.
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Aggregate commands have no single canonical resource that can reconstruct
    # their result counts.  Store only their successful typed payload; ordinary
    # resource mutations keep this NULL and continue re-serialising current state.
    response_body: Mapped[dict[str, object] | None] = mapped_column(JSON(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set by the helper to ``created_at + retention``; the retention floor is an
    # ADR-0042 §4.10 correctness constraint (≥ max outbox unresolved-row life).
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
