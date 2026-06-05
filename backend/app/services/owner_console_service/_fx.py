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
    source_url: str
    auto_enabled: bool
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
        source_url=cfg.fx_rate_ecb_url if source == "ecb" else cfg.fx_rate_frankfurter_url,
        auto_enabled=cfg.fx_rate_auto_sync_enabled,
        sync_times=cfg.fx_rate_sync_times,
        sync_timezone=cfg.fx_rate_sync_timezone,
        success_count=status.success_count,
        failed_count=status.failed_count,
        last_error=status.last_error,
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
