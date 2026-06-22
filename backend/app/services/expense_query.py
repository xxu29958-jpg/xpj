"""Read-only expense lookups + lifecycle constants shared across services.

Sits below ``expense_service`` and ``receipt_item_service`` so both can
import from here without forming an import cycle.

``expense_service`` re-exports ``get_expense``, ``resolve_expense`` and
``EDITABLE_STATUSES`` from this module so existing call sites
(``from app.services.expense_service import EDITABLE_STATUSES, get_expense``)
keep working unchanged.

``resolve_expense`` (issue #65 slice 2) is the SINGLE entry point for turning a
client-supplied expense reference into a row: a server id, or a device-local
``local:{client_ref}`` ref that resolves through the ``draft_idempotency_key``
composite written by ``create_manual_expense``. Service-layer lookups go through
it instead of scattering ``ledger_scoped_select(Expense, …).where(Expense.id == …)``;
``scripts/_audit_expense_resolve.py`` enforces that.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense

__all__ = [
    "EDITABLE_STATUSES",
    "FIRST_WRITE_ROW_VERSION",
    "LOCAL_REF_PREFIX",
    "get_expense",
    "local_ref_storage_key",
    "resolve_expense",
    "resolve_expense_for_mutation",
]


# An Expense is editable while ``pending`` (draft) or ``confirmed``
# (user-owned). Anything else (``rejected``, ``deleted``) is frozen.
EDITABLE_STATUSES = {"pending", "confirmed"}

# Issue #65: a client may reference a not-yet-synced expense by a device-local
# ref ``local:{client_ref}`` instead of a server id.
LOCAL_REF_PREFIX = "local:"

# Issue #65 slice 3: ``Expense.row_version`` starts at 1 (models/expense.py), so
# 0 is a free sentinel for "the client never saw the server row_version". A
# ``local:{client_ref}`` mutation carrying this sentinel is a FIRST write through
# the local ref — its OCC CAS applies to the row's CURRENT version instead of
# false-409-ing (see ``resolve_expense_for_mutation``).
FIRST_WRITE_ROW_VERSION = 0


def _is_local_ref(ref: int | str) -> bool:
    return isinstance(ref, str) and ref.startswith(LOCAL_REF_PREFIX)


def local_ref_storage_key(device_id: int, client_ref: str) -> str:
    """The ``Expense.draft_idempotency_key`` value for a device-local manual create.

    Single source of truth for the ``{device_id}:{client_ref}`` composite so the
    create side (which STORES it — ``create_manual_expense``) and the resolve side
    (which looks it up — ``resolve_expense``) can never drift. A drift would make a
    ``local:{client_ref}`` mutation silently miss its row.
    """
    return f"{device_id}:{client_ref}"


def resolve_expense(
    db: Session,
    tenant_id: str,
    ref: int | str,
    *,
    device_id: int | None = None,
) -> Expense | None:
    """Resolve a client-supplied expense reference within ``tenant_id`` scope.

    ``ref`` is either a server id (``int``, or its decimal string form) or a
    device-local ref ``local:{client_ref}`` (issue #65). The device namespace is
    built HERE from ``device_id`` — callers pass the device, never the composite key.

    Returns the ``Expense`` or ``None`` when nothing matches in scope (callers raise
    the 404 — see ``get_expense``). A ``local:`` ref with no ``device_id`` resolves
    to ``None``; the route layer (slice 3) supplies the device from its AuthContext.
    A malformed server-id ref (a non-numeric, non-``local:`` string from a widened
    path param) also resolves to ``None`` rather than raising — the caller 404s.
    """
    if _is_local_ref(ref):
        if device_id is None:
            return None
        client_ref = ref[len(LOCAL_REF_PREFIX):]
        return db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(
                Expense.draft_idempotency_key == local_ref_storage_key(device_id, client_ref)
            )
        )
    try:
        server_id = int(ref)
    except (TypeError, ValueError):
        return None
    return db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == server_id)
    )


def resolve_expense_for_mutation(
    db: Session,
    tenant_id: str,
    ref: int | str,
    *,
    device_id: int,
    expected_row_version: int,
) -> tuple[int, int]:
    """Resolve a mutation ref to ``(server_pk, effective_expected_row_version)``.

    The issue #65 slice 3 outbox-routed expense mutation routes take a
    server-id-or-``local:{client_ref}`` string ref. This funnels the resolution
    (raising ``404`` when nothing matches in scope) and decides which OCC version
    the service's CAS should claim:

    * server id, or a ``local:`` ref the client already holds a real version for:
      the client's own ``expected_row_version`` — OCC unchanged.
    * a ``local:{client_ref}`` FIRST write — the client never saw the server
      ``row_version`` so it sends the ``FIRST_WRITE_ROW_VERSION`` sentinel — the
      row's CURRENT ``row_version``. The CAS then applies to current state with no
      false 409, yet a *concurrent* writer that bumped the version between this
      read and the service CAS still loses the CAS (rowcount=0 → real 409). The
      caller keeps feeding the RAW sentinel to the idempotency claim, so a replay
      stays a stable fingerprint (the current version may drift between replays).

    A server-id ref carrying the sentinel is NOT special-cased: ``effective`` stays
    0, the CAS finds no row at version 0 (real rows start at 1) and 409s — a synced
    row must not be blind-written.
    """
    expense = resolve_expense(db, tenant_id, ref, device_id=device_id)
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    effective = expected_row_version
    if _is_local_ref(ref) and expected_row_version == FIRST_WRITE_ROW_VERSION:
        effective = expense.row_version
    return expense.id, effective


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = resolve_expense(db, tenant_id, expense_id)
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense
