"""backfill signal_type / signal_hash / signal_payload on legacy events.

Revision ID: c5b9a324c535
Revises: feea26ff79a4
Create Date: 2026-05-25

The prior revision (feea26ff79a4) added the three signal_* columns but
left existing rows with NULL signal_hash. The read paths
(``_count_recent_rejects`` / ``_has_recent_reject``) handled that via
an OR(indexed, LIKE) branch — but SQLite's planner frequently turns
OR into a full scan, defeating the index entirely.

This revision walks every ``ledger_learning_events`` row with NULL
signal_hash, inspects its ``before_payload``, and computes the
canonical marker / hash for the two registered marker-shaped types:

* ``category_suggestion`` — payload key is exactly ``{"category": X}``
* ``duplicate_candidate`` — payload keys are exactly
  ``{"amount_cents": N, "merchant": M}`` (order irrelevant)

Rows whose payload doesn't match either shape stay NULL; they were
written by paths that don't participate in the feedback-de-dup loop.

Hash computation is inlined here (sha256 of sort-key JSON) rather than
imported from ``app.services.learning_service._algorithm_registry``
because alembic env imports are fragile and we want this migration to
keep working even after the registry module is renamed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5b9a324c535"
down_revision: str | Sequence[str] | None = "feea26ff79a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_hash(marker: dict) -> str:
    encoded = json.dumps(marker, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _infer_signal(payload_text: str | None) -> tuple[str, dict] | None:
    """Pick a (signal_type, canonical marker) from a legacy
    ``before_payload``. Returns ``None`` when the payload doesn't match
    either registered marker shape.
    """

    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    keys = set(payload.keys())
    # category_suggestion marker — exactly one key, "category".
    if keys == {"category"} and isinstance(payload.get("category"), str):
        return "category_suggestion", {"category": payload["category"]}
    # duplicate_candidate marker — exactly {"amount_cents", "merchant"}.
    if keys == {"amount_cents", "merchant"}:
        amount = payload.get("amount_cents")
        merchant = payload.get("merchant")
        if isinstance(amount, int) and isinstance(merchant, str):
            return "duplicate_candidate", {
                "amount_cents": amount,
                "merchant": merchant,
            }
    return None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, before_payload FROM ledger_learning_events "
            "WHERE signal_hash IS NULL"
        )
    ).all()
    if not rows:
        return

    updates: list[tuple[str, str, str, int]] = []
    for row_id, before_payload in rows:
        inferred = _infer_signal(before_payload)
        if inferred is None:
            continue
        signal_type, marker = inferred
        signal_hash = _canonical_hash(marker)
        signal_payload = json.dumps(
            marker, sort_keys=True, ensure_ascii=False
        )
        updates.append((signal_type, signal_hash, signal_payload, row_id))

    if not updates:
        return
    bind.execute(
        sa.text(
            "UPDATE ledger_learning_events "
            "SET signal_type = :signal_type, "
            "    signal_hash = :signal_hash, "
            "    signal_payload = :signal_payload "
            "WHERE id = :row_id"
        ),
        [
            {
                "signal_type": signal_type,
                "signal_hash": signal_hash,
                "signal_payload": signal_payload,
                "row_id": row_id,
            }
            for signal_type, signal_hash, signal_payload, row_id in updates
        ],
    )


def downgrade() -> None:
    # Backfill is data-only. The reverse can't tell what was
    # originally written vs. backfilled without an audit column, so
    # this is a no-op. Operators who need to actually roll back the
    # backfill should restore from the pre-migration backup.
    pass
