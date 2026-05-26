"""ADR-0038 optimistic-concurrency claim helpers.

Used by every endpoint that mutates a row gated by ``expected_updated_at``:

- expense PATCH / confirm / reject / mark-not-duplicate / OCR retry /
  items replace / splits replace / confirmed batch update
  (ADR-0038 PR-2a~2d)
- category_rule PATCH / DELETE (ADR-0038 PR-1)
- rule_application apply / rollback (Alpha3 engine — pre-dates ADR-0038
  but follows the same atomic ``UPDATE WHERE updated_at = expected``
  shape; latent tz-handling bug fixed by this refactor)
- ...followups: merchant alias / recognize-text

Two layers:

* :func:`updated_at_predicate` builds the SQL ``column == expected``
  comparator with SQLite tz handling baked in. ``DateTime(timezone=True)``
  reads back as naive on SQLite, so the bound value has to lose its
  tzinfo or the predicate is silently dialect-dependent. Previously
  copy-pasted in 4 inline sites + 3 module-local helpers (each with
  slightly different behaviour — see commit history).
* :func:`claim_row_with_token` / :func:`delete_row_with_token` build
  the atomic ``UPDATE / DELETE WHERE tenant_id, id, updated_at =
  expected`` and return ``rowcount``. The **disambiguation** (rowcount=0
  → ``not_found`` 404 vs ``state_conflict`` 409 vs terminal-status
  idempotency) stays in the caller because each endpoint's terminal
  rules differ — confirm has ``confirmed`` as idempotent, OCR retry
  doesn't, rule PATCH has no terminal at all, rule_application returns
  ``None`` instead of raising.

Not abstracted: the caller's choice of ``db.rollback()`` vs
``db.expire_all()`` on the failure path. PR-1 uses ``rollback``;
PR-2a/2b/2c use ``expire_all``; the two are not equivalent if a
caller adds a pre-claim flush. Picking one would silently change
behaviour, so the cleanup is deliberately a follow-up review pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.ledger_scope import ledger_filter
from app.services.time_service import ensure_utc

__all__ = [
    "claim_row_with_token",
    "delete_row_with_token",
    "updated_at_predicate",
]


def updated_at_predicate(column, value: datetime | None) -> ColumnElement:
    """SQL predicate matching ``column == expected_updated_at``.

    Normalises ``value`` through ``ensure_utc(...).replace(tzinfo=None)``
    because SQLite reads ``DateTime(timezone=True)`` back as naive;
    binding an aware value would compare unequal (dialect-dependent).
    A naive value (e.g. read directly from an ORM-loaded row on SQLite)
    passes through unchanged because ``ensure_utc`` treats naive as
    UTC and ``.replace(tzinfo=None)`` strips it back.
    """
    if value is None:
        return column.is_(None)
    return column == ensure_utc(value).replace(tzinfo=None)


def claim_row_with_token(
    db: Session,
    model,
    *,
    pk_id: int,
    tenant_id: str,
    expected_updated_at: datetime,
    set_values: dict[str, Any],
    extra_where: tuple = (),
    synchronize_session: bool | str = "auto",
) -> int:
    """Atomic UPDATE ``WHERE tenant_id, id, updated_at = expected [+extra]``.

    Returns ``rowcount`` so the caller can branch on ``== 1`` (claim
    succeeded) vs ``== 0`` (row not visible / status filter mismatch /
    token stale). The caller is responsible for the rowcount=0
    disambiguation because endpoint-specific terminal-status rules
    don't generalise (confirm has ``confirmed`` as idempotent, etc.).

    ``set_values`` MUST include ``updated_at`` — the helper does not
    inject it because terminal-status claims own the timestamp tuple
    (e.g. ``status=confirmed, confirmed_at=now, updated_at=now``).

    ``model`` must be ledger-scoped (have a ``tenant_id`` column);
    :func:`ledger_filter` is used so we fail loudly if the caller
    passes a non-tenant model.

    ``synchronize_session`` defaults to SQLAlchemy's ``"auto"`` so the
    ORM identity-map stays in sync with the UPDATE — important for the
    rule_service path which reads the row back via ``find_rule_for_tenant``
    immediately after. Expense callers explicitly pass ``False`` because
    they ``db.expire_all() + get_expense(...)`` in the success path and
    don't need session syncing (and ``"auto"`` is more expensive at
    scale).
    """
    stmt = (
        sa_update(model)
        .where(ledger_filter(model, tenant_id))
        .where(model.id == pk_id)
        .where(updated_at_predicate(model.updated_at, expected_updated_at))
    )
    for predicate in extra_where:
        stmt = stmt.where(predicate)
    result = db.execute(
        stmt.values(**set_values).execution_options(
            synchronize_session=synchronize_session
        )
    )
    return int(result.rowcount or 0)


def delete_row_with_token(
    db: Session,
    model,
    *,
    pk_id: int,
    tenant_id: str,
    expected_updated_at: datetime,
) -> int:
    """Atomic DELETE ``WHERE tenant_id, id, updated_at = expected``.

    Returns ``rowcount``; caller disambiguates rowcount=0 into 404 / 409.
    """
    stmt = (
        sa_delete(model)
        .where(ledger_filter(model, tenant_id))
        .where(model.id == pk_id)
        .where(updated_at_predicate(model.updated_at, expected_updated_at))
    )
    result = db.execute(stmt)
    return int(result.rowcount or 0)
