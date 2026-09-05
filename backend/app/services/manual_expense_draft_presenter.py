"""Read-only draft binding and canonical creation acknowledgement for Web."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Expense
from app.services.dataset_authority_service import read_dataset_authority
from app.tenants import AuthContext


def manual_draft_scope(db: Session, auth: AuthContext) -> dict[str, str]:
    authority = read_dataset_authority(db)
    return {
        "datasetId": authority.dataset_id,
        "clientGeneration": authority.client_generation,
        "accountId": auth.account_public_id,
        "ledgerId": auth.ledger_id,
        "deviceId": auth.device_public_id,
    }


def manual_draft_ack(db: Session, auth: AuthContext | None, expense: Expense) -> dict | None:
    if auth is None or auth.ledger_id != expense.tenant_id or expense.source != "手动记账":
        return None
    prefix = f"{auth.device_id}:"
    key = expense.draft_idempotency_key or ""
    if not key.startswith(prefix):
        return None
    client_ref = key[len(prefix):]
    if not re.fullmatch(r"[0-9a-f]{32}", client_ref):
        return None
    return {"scope": manual_draft_scope(db, auth), "clientRef": client_ref}
