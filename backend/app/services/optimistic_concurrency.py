"""ADR-0038 optimistic-concurrency claim helpers — ADR-0041 row_version CAS.

Used by every endpoint that mutates a row gated by ``expected_row_version``:

- expense PATCH / confirm / reject / mark-not-duplicate / OCR retry /
  items replace / splits replace / confirmed batch update
- expense recognize-text / items acknowledge-mismatch
- merchant_alias PATCH / DELETE
- category_rule PATCH / DELETE
- rule_application apply / rollback (Alpha3 engine — same atomic shape)

Two layers:

* :func:`row_version_predicate` builds the SQL ``column == expected_row_version``
  comparator. ``row_version`` is a monotonic ``Integer NOT NULL`` so this is a
  plain integer equality — dialect-safe by construction. (ADR-0041 retired the
  old ``updated_at`` comparator: its SQLite-naive vs Postgres-aware-timestamptz
  handling hung OCC correctness on a tz-strip workaround, and its ~15ms equal-
  timestamp window let ABA stale tokens through. The monotonic counter fixes
  both.)
* :func:`claim_row_with_token` / :func:`delete_row_with_token` build the atomic
  ``UPDATE / DELETE WHERE tenant_id, id, row_version = expected`` and return
  ``rowcount``. The **disambiguation** (rowcount=0 → ``not_found`` 404 vs
  ``state_conflict`` 409 vs terminal-status idempotency) stays in the caller
  because each endpoint's terminal rules differ — confirm has ``confirmed`` as
  idempotent, OCR retry doesn't, rule PATCH has no terminal at all,
  rule_application returns ``None`` instead of raising.

:func:`bump_row_version` is for the non-helper mutation paths (see its docstring).

Not abstracted: the caller's choice of ``db.rollback()`` vs ``db.expire_all()``
on the failure path. The two are not equivalent if a caller adds a pre-claim
flush, so the cleanup stays a deliberate per-caller choice.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.ledger_scope import ledger_filter

__all__ = [
    "bump_row_version",
    "claim_row_with_token",
    "delete_row_with_token",
    "row_version_predicate",
]


def bump_row_version(instance: Any) -> None:
    """Atomically increment a loaded ORM row's ``row_version`` (ADR-0041).

    For non-helper mutation paths that set ``updated_at`` directly on a loaded
    instance — lazy thumbnail gen, background image cleanup, async enrichment,
    recurring reactivate/archive, … . Emits a SQL ``row_version =
    row_version + 1`` expression on flush (NOT a Python read-modify-write) so a
    concurrent writer can't make the monotonic counter regress.

    Do NOT call this on a row already claimed via :func:`claim_row_with_token`
    in the same operation (the claim bumps it; a second bump double-counts), nor
    on a freshly-constructed row (those start at ``row_version=1`` on insert).
    After flush the attribute is expired — ``db.refresh`` to read it back as int.
    """
    instance.row_version = type(instance).row_version + 1


def row_version_predicate(column, value: int) -> ColumnElement:
    """SQL predicate matching ``column == expected_row_version`` (ADR-0041).

    ``row_version`` is a monotonic ``Integer NOT NULL`` — plain integer
    equality, dialect-safe by construction (no tz normalisation, no ABA window).
    """
    return column == value


def claim_row_with_token(
    db: Session,
    model,
    *,
    pk_id: int,
    tenant_id: str,
    expected_row_version: int,
    set_values: dict[str, Any],
    extra_where: tuple = (),
    synchronize_session: bool | str = "auto",
) -> int:
    """Atomic UPDATE ``WHERE tenant_id, id, row_version = expected [+extra]``.

    Returns ``rowcount`` so the caller can branch on ``== 1`` (claim succeeded)
    vs ``== 0`` (row not visible / status filter mismatch / token stale). The
    caller owns the rowcount=0 disambiguation because endpoint-specific
    terminal-status rules don't generalise (confirm has ``confirmed`` as
    idempotent, etc.).

    ``set_values`` MUST include ``updated_at`` (retained for display/sort) — the
    helper does not inject it because terminal claims own the timestamp tuple
    (e.g. ``status=confirmed, confirmed_at=now, updated_at=now``). The helper
    DOES auto-inject ``row_version = row_version + 1`` (the CAS increment);
    callers must NOT pass ``row_version`` in ``set_values``.

    ``model`` must be ledger-scoped (have a ``tenant_id`` column);
    :func:`ledger_filter` fails loudly if the caller passes a non-tenant model.

    ``synchronize_session`` defaults to ``"auto"``. The injected
    ``row_version + 1`` is a SQL expression the evaluate strategy can't compute
    in Python, so SQLAlchemy expires ``row_version`` on matched in-session rows
    (no error); any caller that reads the mutated row back through the identity
    map after ``db.commit()`` should ``db.expire_all()`` first
    (``expire_on_commit=False`` on ``SessionLocal``). Callers that don't read
    back pass ``synchronize_session=False`` explicitly.
    """
    stmt = (
        sa_update(model)
        .where(ledger_filter(model, tenant_id))
        .where(model.id == pk_id)
        .where(row_version_predicate(model.row_version, expected_row_version))
    )
    for predicate in extra_where:
        stmt = stmt.where(predicate)
    result = db.execute(
        stmt.values(**set_values, row_version=model.row_version + 1).execution_options(
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
    expected_row_version: int,
) -> int:
    """Atomic DELETE ``WHERE tenant_id, id, row_version = expected``.

    Returns ``rowcount``; caller disambiguates rowcount=0 into 404 / 409.
    """
    stmt = (
        sa_delete(model)
        .where(ledger_filter(model, tenant_id))
        .where(model.id == pk_id)
        .where(row_version_predicate(model.row_version, expected_row_version))
    )
    result = db.execute(stmt)
    return int(result.rowcount or 0)
