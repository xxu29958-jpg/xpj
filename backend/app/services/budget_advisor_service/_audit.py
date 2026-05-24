"""v1.1 Batch 2: AI budget advisor audit log + provider status.

Each invocation of an outbound advisor (anything other than ``empty`` /
``mock``) writes a single row to ``budget_advisor_audit_logs``. The
Owner Console "AI 状态" panel reads those rows to surface:

* current provider config (with secrets masked),
* whether the owner has explicitly confirmed AI calls
  (``BUDGET_ADVISOR_OWNER_CONFIRMED``), and
* the most recent call result + timestamp.

The input hash is sha256 over the outbound-guarded JSON payload — same
bytes that actually leave the box. We never store the payload itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BudgetAdvisorAuditLog
from app.services.time_service import ensure_utc, now_utc, to_iso

LIVE_PROVIDER_NAMES = frozenset({"openai_compat", "openai-compat", "openai", "deepseek", "siliconflow"})


def is_live_provider(name: str | None) -> bool:
    """Return True for any provider that actually phones home."""

    if name is None:
        return False
    return name.strip().lower() in LIVE_PROVIDER_NAMES


@dataclass(frozen=True)
class AdvisorStatus:
    provider: str
    model: str | None
    base_url: str | None
    owner_confirmed: bool
    is_live: bool
    needs_confirmation: bool
    last_called_at: str | None
    last_success: bool | None
    last_error_code: str | None
    last_suggestion_count: int | None
    last_duration_ms: int | None


def compute_input_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mask_base_url(value: str | None) -> str | None:
    """Strip credentials embedded in a URL so the status response can
    surface the endpoint without leaking ``user:pass@host`` even if the
    owner accidentally put one there. The path, query, and fragment are
    preserved because endpoints like ``/v1`` are part of the legitimate
    configuration the owner needs to see when debugging."""

    if not value:
        return value
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(value)
    if not parsed.username and not parsed.password:
        return value
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def record_audit_row(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None,
    provider: str,
    model: str | None,
    base_url: str | None,
    month: str | None,
    input_hash: str,
    success: bool,
    error_code: str | None = None,
    suggestion_count: int = 0,
    duration_ms: int | None = None,
    called_at: datetime | None = None,
) -> BudgetAdvisorAuditLog:
    cfg = get_settings()
    row = BudgetAdvisorAuditLog(
        tenant_id=tenant_id,
        actor_account_id=actor_account_id,
        provider=provider,
        model=model,
        base_url=mask_base_url(base_url),
        month=month,
        input_hash=input_hash,
        success=1 if success else 0,
        error_code=error_code,
        suggestion_count=int(max(suggestion_count, 0)),
        duration_ms=duration_ms,
        retention_days=max(int(cfg.budget_advisor_audit_retention_days), 0),
        called_at=called_at or now_utc(),
    )
    db.add(row)
    db.commit()
    return row


def latest_audit_row(db: Session, *, tenant_id: str) -> BudgetAdvisorAuditLog | None:
    return db.scalar(
        select(BudgetAdvisorAuditLog)
        .where(BudgetAdvisorAuditLog.tenant_id == tenant_id)
        .order_by(BudgetAdvisorAuditLog.called_at.desc())
        .limit(1)
    )


def recent_audit_rows(db: Session, *, tenant_id: str, limit: int = 10) -> list[BudgetAdvisorAuditLog]:
    safe_limit = max(1, min(int(limit), 50))
    return list(
        db.scalars(
            select(BudgetAdvisorAuditLog)
            .where(BudgetAdvisorAuditLog.tenant_id == tenant_id)
            .order_by(BudgetAdvisorAuditLog.called_at.desc())
            .limit(safe_limit)
        )
    )


def cleanup_expired_audit_logs(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = 500,
) -> int:
    """Delete audit rows whose per-row retention window has elapsed."""

    threshold = now or now_utc()
    rows = list(
        db.scalars(
            select(BudgetAdvisorAuditLog)
            .where(BudgetAdvisorAuditLog.retention_days > 0)
            .order_by(BudgetAdvisorAuditLog.called_at.asc())
            .limit(max(1, min(int(batch_size), 5000)))
        )
    )
    expired: list[BudgetAdvisorAuditLog] = []
    for row in rows:
        called_at = ensure_utc(row.called_at) or row.called_at
        if called_at + timedelta(days=row.retention_days) <= threshold:
            expired.append(row)
    for row in expired:
        db.delete(row)
    if expired:
        db.commit()
    return len(expired)


def advisor_status_for_tenant(db: Session, *, tenant_id: str) -> AdvisorStatus:
    cfg = get_settings()
    provider = (cfg.budget_advisor_provider or "empty").strip().lower()
    is_live = is_live_provider(provider)
    latest = latest_audit_row(db, tenant_id=tenant_id)
    return AdvisorStatus(
        provider=provider,
        model=cfg.budget_advisor_model or None,
        base_url=mask_base_url(cfg.budget_advisor_base_url or None),
        owner_confirmed=cfg.budget_advisor_owner_confirmed,
        is_live=is_live,
        # ``empty`` / ``mock`` never need owner confirmation because they
        # don't leave the box. ``openai_compat`` and friends do.
        needs_confirmation=is_live and not cfg.budget_advisor_owner_confirmed,
        last_called_at=to_iso(ensure_utc(latest.called_at)) if latest else None,
        last_success=bool(latest.success) if latest else None,
        last_error_code=latest.error_code if latest else None,
        last_suggestion_count=latest.suggestion_count if latest else None,
        last_duration_ms=latest.duration_ms if latest else None,
    )


__all__ = [
    "AdvisorStatus",
    "advisor_status_for_tenant",
    "cleanup_expired_audit_logs",
    "compute_input_hash",
    "is_live_provider",
    "latest_audit_row",
    "mask_base_url",
    "recent_audit_rows",
    "record_audit_row",
    "LIVE_PROVIDER_NAMES",
]
