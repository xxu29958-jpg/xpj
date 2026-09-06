"""Owner Console FX panel aggregator.

Composes the FX-sync status snapshot (from the scheduler), the configured
transport, and the latest stored rates (from ``fx_rates``) into one view model
so the route layer never touches the DB or config directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.fx_constants import FX_SOURCE_ECB
from app.models import FxRate
from app.services.fx_rate_scheduler import fx_rate_sync_status

_SYNC_FAILURE_MESSAGES = {
    "provider_unavailable": "暂时无法取得参考汇率，已保留上次汇率。",
    "storage_unavailable": "本次任务暂时无法访问数据库，已保留上次汇率。",
    "sync_failed": "本次同步未完成，已保留上次汇率。",
}


@dataclass
class FxRowVM:
    currency: str
    rate: str
    rate_date: str
    source: str
    fetched_at: datetime | None


@dataclass
class FxPanelVM:
    source: str
    auto_enabled: bool
    scheduler_running: bool
    scheduler_config_error: bool
    sync_times: str
    sync_timezone: str
    success_count: int
    failed_count: int
    last_error: str | None
    last_success_at: datetime | None
    rows: list[FxRowVM]
    latest_date: str | None


def get_fx_panel_vm(db: Session, *, home_currency_code: str) -> FxPanelVM:
    cfg = get_settings()
    home = (home_currency_code or "").strip().upper()
    rows = db.scalars(
        select(FxRate)
        .where(FxRate.source == FX_SOURCE_ECB)
        .where(FxRate.home_currency_code == home)
        .order_by(FxRate.rate_date.desc(), FxRate.currency_code.asc())
        .limit(30)
    ).all()
    status = fx_rate_sync_status()
    source = (cfg.fx_rate_source or "frankfurter").strip().lower()
    return FxPanelVM(
        source=source,
        auto_enabled=cfg.fx_rate_auto_sync_enabled,
        scheduler_running=status.scheduler_running,
        scheduler_config_error=status.scheduler_config_error,
        sync_times=cfg.fx_rate_sync_times,
        sync_timezone=cfg.fx_rate_sync_timezone,
        success_count=status.success_count,
        failed_count=status.failed_count,
        last_error=(
            _SYNC_FAILURE_MESSAGES.get(status.last_error, _SYNC_FAILURE_MESSAGES["sync_failed"])
            if status.last_error
            else None
        ),
        last_success_at=status.last_success_at,
        rows=[
            FxRowVM(
                currency=row.currency_code,
                rate=format(row.rate_to_home, "f"),
                rate_date=row.rate_date.isoformat(),
                source=row.source,
                fetched_at=row.fetched_at,
            )
            for row in rows
        ],
        latest_date=rows[0].rate_date.isoformat() if rows else None,
    )
