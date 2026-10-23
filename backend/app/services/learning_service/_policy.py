"""Independent ledger/version execution and feedback eligibility controls."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppMeta
from app.services.app_meta_service import get_value
from app.services.time_service import now_utc

PolicyAxis = Literal["new_suggestions", "training"]


def _policy_key(tenant_id: str, decision_type: str, version: str, axis: PolicyAxis) -> str:
    identity = json.dumps([tenant_id, decision_type, version, axis], ensure_ascii=False)
    return "learning-policy:" + hashlib.sha256(identity.encode()).hexdigest()[:48]


def policy_enabled(db: Session, *, tenant_id: str, decision_type: str, version: str, axis: PolicyAxis) -> bool:
    value = get_value(db, _policy_key(tenant_id, decision_type, version, axis))
    return value is None or json.loads(value)["enabled"]


def set_policy(db: Session, *, tenant_id: str, decision_type: str, version: str, axis: PolicyAxis, enabled: bool) -> None:
    """Change one axis; the caller owns its transaction, never ledger facts."""
    value = json.dumps({"tenant_id": tenant_id, "decision_type": decision_type,
        "version": version, "axis": axis, "enabled": enabled}, ensure_ascii=False, sort_keys=True)
    command = insert(AppMeta).values(key=_policy_key(tenant_id, decision_type, version, axis), value=value, updated_at=now_utc())
    db.execute(command.on_conflict_do_update(index_elements=[AppMeta.key],
        set_={"value": command.excluded.value, "updated_at": command.excluded.updated_at}))
