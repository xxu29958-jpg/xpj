"""ADR-0029 cross-ledger bill split workflow.

State machine + privacy boundaries. See the ADR for the full rationale;
key load-bearing points:

- **Account-scoped invitation**: sender chooses receiver_account_id; sender
  never knows which ledger receiver will pick.
- **Receiver picks ledger at accept**: ``target_ledger_id`` is supplied in
  the accept request body and the service checks the receiver has write
  role on that ledger.
- **Decoupled accepted expense**: a fresh ``Expense`` is created in the
  receiver's chosen ledger with ``source='bill_split_received'``; it does
  not FK back to sender's expense.
- **Idempotent accept**: ``received_expense_id`` is UNIQUE on the table,
  so re-accepting returns the already-created expense.
- **No chain split**: ``create_invitation`` refuses if the source expense
  itself was a received split.

Audit: LedgerAuditLog gains 5 action values (bill_split_invited /
accepted / rejected / cancelled / expired). The action column is already
a free-form String(64), so no schema change is needed there.

The implementation is split across private sub-modules by lifecycle phase
(``_create`` / ``_query`` / ``_transitions``), DTO serialization
(``_serializers``), immutability enforcement (``_guards``) and shared
constants + member-load + audit helpers (``_common``).
"""

from __future__ import annotations

from app.services.bill_split_service._backfill import (
    backfill_bill_split_debts,
    reconcile_bill_split_debts_if_enabled,
)
from app.services.bill_split_service._common import (
    INVITATION_TTL,
    SPLIT_RECEIVED_SOURCE,
    WRITER_ROLES,
)
from app.services.bill_split_service._create import create_invitation
from app.services.bill_split_service._guards import (
    IMMUTABLE_ON_SPLIT_RECEIVED,
    assert_no_immutable_field_changes,
)
from app.services.bill_split_service._query import (
    get_invitation,
    list_inbox,
    list_sent,
    list_sent_for_expense,
)
from app.services.bill_split_service._serializers import (
    to_inbox_response_dict,
    to_sent_response_dict,
)
from app.services.bill_split_service._transitions import (
    accept_invitation,
    cancel_invitation,
    expire_invitations,
    reject_invitation,
)

__all__ = [
    "IMMUTABLE_ON_SPLIT_RECEIVED",
    "INVITATION_TTL",
    "SPLIT_RECEIVED_SOURCE",
    "WRITER_ROLES",
    "accept_invitation",
    "assert_no_immutable_field_changes",
    "backfill_bill_split_debts",
    "cancel_invitation",
    "create_invitation",
    "expire_invitations",
    "get_invitation",
    "list_inbox",
    "list_sent",
    "list_sent_for_expense",
    "reconcile_bill_split_debts_if_enabled",
    "reject_invitation",
    "to_inbox_response_dict",
    "to_sent_response_dict",
]
