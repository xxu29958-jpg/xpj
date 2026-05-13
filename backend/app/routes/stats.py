from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.schemas import LifestyleStatsResponse, MonthlyStatsResponse
from app.services.stats_service import lifestyle_stats, monthly_stats
from app.services.time_service import current_month
from app.tenants import AuthContext


router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
)


@router.get("/monthly", response_model=MonthlyStatsResponse)
def get_monthly_stats(
    month: str | None = None,
    tag: str | None = None,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> MonthlyStatsResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
    return MonthlyStatsResponse(**monthly_stats(db, target_month, auth.tenant_id, timezone_name=timezone_name, tag=tag))


@router.get("/lifestyle", response_model=LifestyleStatsResponse)
def get_lifestyle_stats(
    month: str | None = None,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> LifestyleStatsResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
    return LifestyleStatsResponse(**lifestyle_stats(db, target_month, auth.tenant_id, timezone_name=timezone_name))
