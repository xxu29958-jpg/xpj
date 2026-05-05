from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_tenant
from app.config import get_settings
from app.database import get_db
from app.schemas import LifestyleStatsResponse, MonthlyStatsResponse
from app.services.expense_service import lifestyle_stats, monthly_stats
from app.services.time_service import current_month
from app.tenants import Tenant


router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
)


@router.get("/monthly", response_model=MonthlyStatsResponse)
def get_monthly_stats(
    month: str | None = None,
    tenant: Tenant = Depends(get_current_app_tenant),
    db: Session = Depends(get_db),
) -> MonthlyStatsResponse:
    target_month = month or current_month(get_settings().ocr_default_timezone)
    return MonthlyStatsResponse(**monthly_stats(db, target_month, tenant.id))


@router.get("/lifestyle", response_model=LifestyleStatsResponse)
def get_lifestyle_stats(
    month: str | None = None,
    tenant: Tenant = Depends(get_current_app_tenant),
    db: Session = Depends(get_db),
) -> LifestyleStatsResponse:
    target_month = month or current_month(get_settings().ocr_default_timezone)
    return LifestyleStatsResponse(**lifestyle_stats(db, target_month, tenant.id))
