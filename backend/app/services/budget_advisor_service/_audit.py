"""v1.1 Batch 2: AI budget advisor audit log + provider status.

Each invocation of an outbound advisor (anything other than ``empty`` /
``mock``) writes a single row to ``budget_advisor_audit_logs``. The
Owner Console "AI 状态" panel reads those rows to surface:

* current provider config (with secrets masked),
* whether the owner has explicitly confirmed AI calls
  (``BUDGET_ADVISOR_OWNER_CONFIRMED``), and
* the most recent call result + timestamp.

The input hash is HMAC-SHA256 over the outbound-guarded JSON payload — same
bytes that actually leave the box, keyed by the local deployment secret. We
never store the payload itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import PLACEHOLDER_SECRETS, get_settings
from app.errors import AppError
from app.models import BudgetAdvisorAuditLog, BudgetAdvisorQuotaLock
from app.services import app_meta_service
from app.services.budget_advisor_service._provider_names import (
    LIVE_PROVIDER_NAMES,
    canonical_provider_name,
    clean_provider_name,
)
from app.services.time_service import ensure_utc, now_utc, to_iso

IN_PROGRESS_ERROR_CODE = "ai_advisor_in_progress"
# ADR-0045 follow-up: a per-install key for the audit input-hash HMAC, key-separated
# from the CSRF signing key (different app_meta row), so neither degrades to the
# public placeholder ADMIN_TOKEN default.
AUDIT_SIGNING_KEY_META = "budget_advisor_audit_key"


def is_live_provider(name: str | None) -> bool:
    """Return True for any provider that actually phones home."""

    return clean_provider_name(name) in LIVE_PROVIDER_NAMES


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


def _audit_signing_secret(db: Session) -> str:
    # ADR-0045: prefer a real operator secret (rejecting the PUBLIC placeholder
    # defaults), else a per-install key persisted in app_meta — never the public
    # constant the old ``... or "xiaopiaojia-budget-advisor-audit-v1"`` chain fell to.
    cfg = get_settings()
    for raw in (cfg.admin_token, cfg.http_bootstrap_secret, cfg.app_token):
        candidate = (raw or "").strip()
        if candidate and candidate not in PLACEHOLDER_SECRETS:
            return candidate
    existing = app_meta_service.get_value(db, AUDIT_SIGNING_KEY_META)
    if existing:
        return existing
    key = secrets.token_urlsafe(32)
    app_meta_service.set_value(db, AUDIT_SIGNING_KEY_META, key)
    return key


def compute_input_hash(db: Session, payload: dict[str, Any]) -> str:
    """HMAC-SHA256 of the outbound payload, keyed by the per-install audit secret
    (ADR-0045). The hash is a write-only tamper-evidence fingerprint — never
    re-verified (the payload itself is never stored), so a key change is harmless."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    secret = _audit_signing_secret(db)
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def enforce_live_call_budget(
    db: Session,
    *,
    tenant_id: str,
    now: datetime | None = None,
) -> None:
    """Fail before an outbound advisor call exceeds configured cost caps."""

    _check_live_call_budget(db, tenant_id=tenant_id, current=now or now_utc())


def _check_live_call_budget(
    db: Session,
    *,
    tenant_id: str,
    current: datetime,
) -> None:
    cfg = get_settings()
    latest = latest_audit_row(db, tenant_id=tenant_id)
    min_interval = int(cfg.budget_advisor_live_min_interval_seconds)
    if min_interval > 0 and latest is not None:
        last_called = ensure_utc(latest.called_at) or latest.called_at
        if last_called + timedelta(seconds=min_interval) > current:
            raise AppError(
                "ai_advisor_rate_limited",
                "AI 预算助手调用过于频繁，请稍后再试。",
                status_code=429,
            )

    daily_limit = int(cfg.budget_advisor_live_daily_call_limit)
    if daily_limit <= 0:
        return
    window_start = current - timedelta(days=1)
    count = db.scalar(
        select(func.count(BudgetAdvisorAuditLog.id))
        .where(BudgetAdvisorAuditLog.tenant_id == tenant_id)
        .where(BudgetAdvisorAuditLog.called_at >= window_start)
    )
    if int(count or 0) >= daily_limit:
        raise AppError(
            "ai_advisor_daily_limit_exceeded",
            "AI 预算助手今日调用次数已达上限。",
            status_code=429,
        )


def _ensure_quota_lock_row(db: Session, *, tenant_id: str, current: datetime) -> None:
    if db.get(BudgetAdvisorQuotaLock, tenant_id) is not None:
        db.commit()
        return
    db.add(BudgetAdvisorQuotaLock(tenant_id=tenant_id, touched_at=current))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _begin_quota_reservation(db: Session) -> None:
    """Start the durable quota reservation critical section.

    SQLite ignores row-level SELECT .. FOR UPDATE, so the shared-DB deployment
    path needs the writer transaction before checking the recent audit window.
    """

    if db.in_transaction():
        db.commit()
    if db.get_bind().dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def reserve_live_call_budget(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int | None,
    provider: str,
    model: str | None,
    base_url: str | None,
    month: str | None,
    input_hash: str,
    now: datetime | None = None,
) -> BudgetAdvisorAuditLog:
    """Durably reserve a live advisor call against tenant cost caps.

    The reservation is an audit row inserted *before* the outbound call. That
    makes daily/min-interval checks durable across multiple workers or app
    instances sharing the same database. If the process dies after reserving,
    the row stays as an in-progress failed attempt and still counts against
    the short cost window, which is the safer failure mode for paid providers.
    """

    cfg = get_settings()
    current = now or now_utc()
    if db.in_transaction():
        db.commit()
    _ensure_quota_lock_row(db, tenant_id=tenant_id, current=current)

    _begin_quota_reservation(db)
    committed = False
    try:
        lock = db.get(BudgetAdvisorQuotaLock, tenant_id, with_for_update=True)
        if lock is None:
            lock = BudgetAdvisorQuotaLock(tenant_id=tenant_id, touched_at=current)
            db.add(lock)
        lock.touched_at = current
        db.flush()
        _check_live_call_budget(db, tenant_id=tenant_id, current=current)
        row = BudgetAdvisorAuditLog(
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            provider=provider,
            model=model,
            base_url=mask_base_url(base_url),
            month=month,
            input_hash=input_hash,
            success=0,
            error_code=IN_PROGRESS_ERROR_CODE,
            suggestion_count=0,
            duration_ms=None,
            retention_days=max(int(cfg.budget_advisor_audit_retention_days), 0),
            called_at=current,
        )
        db.add(row)
        db.flush()
        row_id = row.id
        db.commit()
        committed = True
    finally:
        if not committed:
            db.rollback()

    reserved = db.get(BudgetAdvisorAuditLog, row_id)
    if reserved is None:  # pragma: no cover - committed row should exist
        raise AppError("server_error", status_code=500)
    db.expunge(reserved)
    db.commit()
    return reserved


def complete_live_call_audit_row(
    db: Session,
    *,
    audit_log_id: int,
    success: bool,
    error_code: str | None = None,
    suggestion_count: int = 0,
    duration_ms: int | None = None,
) -> None:
    row = db.get(BudgetAdvisorAuditLog, audit_log_id)
    if row is None:
        return
    row.success = 1 if success else 0
    row.error_code = error_code
    row.suggestion_count = int(max(suggestion_count, 0))
    row.duration_ms = duration_ms
    db.commit()


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
    # ``called_at + retention_days days`` as a SQL expression for the pre-filter
    # ORDER BY / WHERE (the Python loop below is the authoritative check).
    # ``datetime()`` / ``printf()`` are SQLite-only, so branch on dialect
    # (ADR-0041): PostgreSQL builds the same offset with ``make_interval``.
    if db.get_bind().dialect.name == "postgresql":
        expires_at = BudgetAdvisorAuditLog.called_at + func.make_interval(
            0, 0, 0, BudgetAdvisorAuditLog.retention_days
        )
    else:
        expires_at = func.datetime(
            BudgetAdvisorAuditLog.called_at,
            func.printf("+%d days", BudgetAdvisorAuditLog.retention_days),
        )
    rows = list(
        db.scalars(
            select(BudgetAdvisorAuditLog)
            .where(BudgetAdvisorAuditLog.retention_days > 0)
            .where(expires_at <= threshold)
            .order_by(expires_at.asc(), BudgetAdvisorAuditLog.called_at.asc())
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
    provider = canonical_provider_name(cfg.budget_advisor_provider)
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
    "complete_live_call_audit_row",
    "compute_input_hash",
    "enforce_live_call_budget",
    "reserve_live_call_budget",
    "is_live_provider",
    "latest_audit_row",
    "mask_base_url",
    "recent_audit_rows",
    "record_audit_row",
    "LIVE_PROVIDER_NAMES",
]
