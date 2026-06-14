"""ADR-0049 Debt domain service (slice 1: create / list / get).

Public face mirrors ``goal_service``: the route layer imports these names and
never reaches into the ``_create`` / ``_query`` / ``_fold`` submodules. The
submodules exist only to keep each file under the 500-line layering budget.

Slice 1 exposes external/manual Debt creation plus ledger-scoped list/get with
the derived ``remaining`` / ``paid`` fold. Fold-changing writes (repayment /
adjustment / void) and the §2.1 parent-row serialization land in slice 2.
"""

from __future__ import annotations

from app.services.debt_service._create import create_debt
from app.services.debt_service._fold import (
    compute_paid,
    compute_remaining,
    derive_status,
)
from app.services.debt_service._query import (
    debt_response,
    get_debt,
    get_debt_response,
    list_debts,
)

__all__ = [
    "compute_paid",
    "compute_remaining",
    "create_debt",
    "debt_response",
    "derive_status",
    "get_debt",
    "get_debt_response",
    "list_debts",
]
