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
    "LOCAL_REF_PREFIX",
    "get_expense",
    "local_ref_storage_key",
    "resolve_expense",
]


# An Expense is editable while ``pending`` (draft) or ``confirmed``
# (user-owned). Anything else (``rejected``, ``deleted``) is frozen.
EDITABLE_STATUSES = {"pending", "confirmed"}

# Issue #65: a client may reference a not-yet-synced expense by a device-local
# ref ``local:{client_ref}`` instead of a server id.
LOCAL_REF_PREFIX = "local:"


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
    """
    if isinstance(ref, str) and ref.startswith(LOCAL_REF_PREFIX):
        if device_id is None:
            return None
        client_ref = ref[len(LOCAL_REF_PREFIX):]
        return db.scalar(
            ledger_scoped_select(Expense, tenant_id).where(
                Expense.draft_idempotency_key == local_ref_storage_key(device_id, client_ref)
            )
        )
    return db.scalar(
        ledger_scoped_select(Expense, tenant_id).where(Expense.id == int(ref))
    )


def get_expense(db: Session, expense_id: int, tenant_id: str) -> Expense:
    expense = resolve_expense(db, tenant_id, expense_id)
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense
