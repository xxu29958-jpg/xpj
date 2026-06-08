"""Per-link upload-link quota + per-remote throttle (v1.1 Batch 1).

Public ``/u/{upload_key}`` is the largest attack surface on the public
hostname: knowing the upload_key (a credential) lets anyone POST images
that we then OCR and store. Three independent limits live here, all
DB-backed so they survive restarts and apply across workers:

* ``per_remote_min_interval_seconds`` — minimum gap between two requests
  from the same remote key (CF-Connecting-IP behind tunnel, peer host
  otherwise). Defeats trivial burst floods.
* ``daily_byte_budget`` — hard cap on bytes accepted per UTC day per
  link. Once reached, additional uploads are rejected with 429 until
  midnight UTC.
* (implicit) ``MAX_UPLOAD_SIZE_BYTES`` — already enforced upstream when
  the body is streamed in.

Loopback / fixture traffic typically has the default budget set high and
interval set to 0 (see ``app.config``), so existing tests that hammer
the endpoint synchronously keep working.

This module never raises during cleanup of old rows; it only raises
``AppError`` when the configured limit is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import UploadLink, UploadLinkDailyUsage, UploadLinkRemoteAttempt
from app.services.time_service import ensure_utc, now_utc

# Keep the daily usage table small: rows older than 30 days are dropped
# on next quota check for the same link. The current day is always kept.
_DAILY_USAGE_RETENTION_DAYS = 30
# Remote-attempt rows older than this are pruned — they would never
# satisfy the interval check anyway. Independent from the value above.
_REMOTE_ATTEMPT_RETENTION = timedelta(days=1)


@dataclass(frozen=True)
class UploadLinkLimits:
    daily_byte_budget: int
    per_remote_min_interval_seconds: int

    @property
    def has_byte_budget(self) -> bool:
        return self.daily_byte_budget > 0

    @property
    def has_interval(self) -> bool:
        return self.per_remote_min_interval_seconds > 0


@dataclass(frozen=True)
class UploadBudgetReservation:
    upload_link_id: int
    ymd: str
    reserved_bytes: int


def _ymd(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def resolve_limits(link: UploadLink) -> UploadLinkLimits:
    """Merge link-level overrides with server defaults.

    A link-level value of NULL means "follow the server default";
    interval defaults to 0 (no throttle). The server-default daily
    budget is generous (200 MiB) but applies to every link unless the
    owner raises it explicitly.
    """

    cfg = get_settings()
    budget_default = max(cfg.upload_link_default_daily_byte_budget, 0)
    interval_default = max(cfg.upload_link_default_per_remote_interval_seconds, 0)
    budget = link.daily_byte_budget if link.daily_byte_budget is not None else budget_default
    interval = link.per_remote_min_interval_seconds or interval_default
    return UploadLinkLimits(
        daily_byte_budget=max(int(budget), 0),
        per_remote_min_interval_seconds=max(int(interval), 0),
    )


def _prune_remote_attempts(db: Session, link_id: int, *, now: datetime) -> None:
    cutoff = now - _REMOTE_ATTEMPT_RETENTION
    db.execute(
        delete(UploadLinkRemoteAttempt)
        .where(UploadLinkRemoteAttempt.upload_link_id == link_id)
        .where(UploadLinkRemoteAttempt.last_attempt_at < cutoff)
    )


def _prune_daily_usage(db: Session, link_id: int, *, now: datetime) -> None:
    keep_after = (now - timedelta(days=_DAILY_USAGE_RETENTION_DAYS)).strftime(
        "%Y-%m-%d"
    )
    db.execute(
        delete(UploadLinkDailyUsage)
        .where(UploadLinkDailyUsage.upload_link_id == link_id)
        .where(UploadLinkDailyUsage.ymd < keep_after)
    )


def enforce_remote_interval(
    db: Session,
    *,
    link: UploadLink,
    remote_key: str,
    limits: UploadLinkLimits | None = None,
) -> None:
    """Reject a request that arrived within the per-remote min interval.

    Always records the new attempt timestamp on the way through, so a
    rejected caller is forced to back off rather than re-trying
    immediately and re-triggering the same window.
    """

    limits = limits or resolve_limits(link)
    now = now_utc()
    _prune_remote_attempts(db, link.id, now=now)
    row = db.scalar(
        select(UploadLinkRemoteAttempt)
        .where(UploadLinkRemoteAttempt.upload_link_id == link.id)
        .where(UploadLinkRemoteAttempt.remote_key == remote_key)
        .limit(1)
    )
    if row is None:
        db.add(
            UploadLinkRemoteAttempt(
                upload_link_id=link.id,
                remote_key=remote_key,
                last_attempt_at=now,
            )
        )
        db.flush()
        return
    last_attempt_at = ensure_utc(row.last_attempt_at) or row.last_attempt_at
    if limits.has_interval:
        elapsed = (now - last_attempt_at).total_seconds()
        if elapsed < limits.per_remote_min_interval_seconds:
            # Bump the timestamp before rejecting so the offender can't
            # spam the endpoint to keep its window open.
            row.last_attempt_at = now
            db.commit()
            retry_after = max(
                int(limits.per_remote_min_interval_seconds - elapsed), 1
            )
            raise AppError(
                "upload_throttled",
                f"上传过于频繁，请 {retry_after} 秒后再试。",
                status_code=429,
            )
    row.last_attempt_at = now
    db.flush()


def _daily_usage(
    db: Session, *, link_id: int, ymd: str, for_update: bool = False
) -> UploadLinkDailyUsage | None:
    stmt = (
        select(UploadLinkDailyUsage)
        .where(UploadLinkDailyUsage.upload_link_id == link_id)
        .where(UploadLinkDailyUsage.ymd == ymd)
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _raise_daily_budget_exhausted(message: str) -> None:
    raise AppError(
        "upload_daily_quota_exhausted",
        message,
        status_code=429,
    )


def _begin_daily_usage_write(db: Session) -> None:
    """Start the quota write critical section.

    Commit any prior (read) transaction so the FOR UPDATE row lock requested by
    ``_daily_usage(..., for_update=True)`` is acquired in a fresh writer
    transaction, held until this critical section commits. PG-only (债 #1): the
    SQLite-only writer-lock statement previously taken here is gone; PG
    serializes via the row lock alone.
    """

    if db.in_transaction():
        db.commit()


def _ensure_daily_usage_row(
    db: Session,
    *,
    link_id: int,
    ymd: str,
    now: datetime,
) -> None:
    if db.in_transaction():
        db.commit()
    if _daily_usage(db, link_id=link_id, ymd=ymd) is not None:
        db.commit()
        return
    db.add(
        UploadLinkDailyUsage(
            upload_link_id=link_id,
            ymd=ymd,
            bytes_total=0,
            request_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def reserve_upload_bytes(
    db: Session,
    *,
    link: UploadLink,
    declared_content_length: int | None = None,
    limits: UploadLinkLimits | None = None,
) -> UploadBudgetReservation:
    """Reserve today's upload-link byte budget before reading the body.

    The reservation is stored in ``bytes_total`` immediately, so concurrent
    workers sharing the DB cannot all pass the preflight check and collectively
    exceed the daily budget. A failed upload releases the reservation; a
    successful upload settles it to the actual byte count.
    """

    limits = limits or resolve_limits(link)
    if not limits.has_byte_budget:
        return UploadBudgetReservation(upload_link_id=link.id, ymd="", reserved_bytes=0)
    declared = declared_content_length if declared_content_length is not None else None
    if declared is not None and declared > limits.daily_byte_budget:
        _raise_daily_budget_exhausted("此次上传将超过今日配额。")

    now = now_utc()
    _prune_daily_usage(db, link.id, now=now)
    ymd = _ymd(now)
    _ensure_daily_usage_row(db, link_id=link.id, ymd=ymd, now=now)

    max_body_bytes = get_settings().max_upload_size_bytes
    _begin_daily_usage_write(db)
    committed = False
    try:
        usage = _daily_usage(db, link_id=link.id, ymd=ymd, for_update=True)
        if usage is None:
            usage = UploadLinkDailyUsage(
                upload_link_id=link.id,
                ymd=ymd,
                bytes_total=0,
                request_count=0,
                created_at=now,
                updated_at=now,
            )
            db.add(usage)
            db.flush()
        used = int(usage.bytes_total or 0)
        remaining = limits.daily_byte_budget - used
        if remaining <= 0:
            _raise_daily_budget_exhausted("今日该上传链接配额已用尽，请明天再试。")
        reserved = (
            max(0, int(declared))
            if declared is not None
            else min(max_body_bytes, remaining)
        )
        if reserved > remaining:
            _raise_daily_budget_exhausted("此次上传将超过今日配额。")
        usage.bytes_total = used + reserved
        usage.updated_at = now
        db.commit()
        committed = True
    finally:
        if not committed:
            db.rollback()
    return UploadBudgetReservation(
        upload_link_id=link.id,
        ymd=ymd,
        reserved_bytes=reserved,
    )


def finalize_upload_bytes(
    db: Session,
    *,
    reservation: UploadBudgetReservation | None,
    bytes_used: int,
) -> None:
    if reservation is None or reservation.reserved_bytes <= 0:
        return
    now = now_utc()
    _begin_daily_usage_write(db)
    committed = False
    try:
        usage = _daily_usage(
            db,
            link_id=reservation.upload_link_id,
            ymd=reservation.ymd,
            for_update=True,
        )
        if usage is None:
            db.rollback()
            return
        delta = max(0, int(reservation.reserved_bytes)) - max(0, int(bytes_used))
        if delta > 0:
            usage.bytes_total = max(0, int(usage.bytes_total or 0) - delta)
        elif delta < 0:
            usage.bytes_total = int(usage.bytes_total or 0) + abs(delta)
        usage.request_count = int(usage.request_count or 0) + 1
        usage.updated_at = now
        db.commit()
        committed = True
    finally:
        if not committed:
            db.rollback()


def release_upload_bytes(
    db: Session,
    *,
    reservation: UploadBudgetReservation | None,
) -> None:
    if reservation is None or reservation.reserved_bytes <= 0:
        return
    now = now_utc()
    try:
        _begin_daily_usage_write(db)
        usage = _daily_usage(
            db,
            link_id=reservation.upload_link_id,
            ymd=reservation.ymd,
            for_update=True,
        )
        if usage is not None:
            usage.bytes_total = max(
                0,
                int(usage.bytes_total or 0) - max(0, int(reservation.reserved_bytes)),
            )
            usage.updated_at = now
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def assert_daily_budget_available(
    db: Session,
    *,
    link: UploadLink,
    declared_content_length: int | None = None,
    limits: UploadLinkLimits | None = None,
) -> int:
    """Refuse the request if today's link budget is already exhausted.

    Called *before* the body is streamed, so a giant upload that would
    blow the budget is rejected without taking the bytes. We use
    ``Content-Length`` when the client provides one; otherwise we only
    reject the trivial "budget already at zero" case here and rely on
    :func:`record_upload_bytes` to finalise the count.

    Returns the bytes-remaining-in-budget so the caller can clamp the
    streaming body limit. ``-1`` means "no budget configured".
    """

    limits = limits or resolve_limits(link)
    if not limits.has_byte_budget:
        return -1
    now = now_utc()
    _prune_daily_usage(db, link.id, now=now)
    ymd = _ymd(now)
    usage = _daily_usage(db, link_id=link.id, ymd=ymd)
    used = usage.bytes_total if usage is not None else 0
    remaining = limits.daily_byte_budget - used
    if remaining <= 0:
        _raise_daily_budget_exhausted("今日该上传链接配额已用尽，请明天再试。")
    if declared_content_length is not None and declared_content_length > remaining:
        _raise_daily_budget_exhausted("此次上传将超过今日配额。")
    return remaining


def record_upload_bytes(db: Session, *, link: UploadLink, bytes_used: int) -> None:
    """Commit ``bytes_used`` against today's link counter.

    Idempotent at the row level: the (link, ymd) row is created on first
    use. ``bytes_used`` may be ``0`` for a metadata-only success — we
    still bump request_count.
    """

    if bytes_used < 0:
        bytes_used = 0
    now = now_utc()
    ymd = _ymd(now)
    usage = _daily_usage(db, link_id=link.id, ymd=ymd)
    if usage is None:
        usage = UploadLinkDailyUsage(
            upload_link_id=link.id,
            ymd=ymd,
            bytes_total=bytes_used,
            request_count=1,
            created_at=now,
            updated_at=now,
        )
        db.add(usage)
    else:
        usage.bytes_total = (usage.bytes_total or 0) + bytes_used
        usage.request_count = (usage.request_count or 0) + 1
        usage.updated_at = now
    db.commit()


__all__ = [
    "UploadBudgetReservation",
    "UploadLinkLimits",
    "assert_daily_budget_available",
    "enforce_remote_interval",
    "finalize_upload_bytes",
    "release_upload_bytes",
    "record_upload_bytes",
    "reserve_upload_bytes",
    "resolve_limits",
]
