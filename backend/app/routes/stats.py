from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import verify_app_token
from app.database import get_db
from app.schemas import LifestyleStatsResponse, MonthlyStatsResponse
from app.services.expense_service import lifestyle_stats, monthly_stats


router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
    dependencies=[Depends(verify_app_token)],
)


@router.get("/monthly", response_model=MonthlyStatsResponse)
def get_monthly_stats(month: str | None = None, db: Session = Depends(get_db)) -> MonthlyStatsResponse:
    target_month = month or datetime.now(UTC).strftime("%Y-%m")
    return MonthlyStatsResponse(**monthly_stats(db, target_month))


@router.get("/lifestyle", response_model=LifestyleStatsResponse)
def get_lifestyle_stats(month: str | None = None, db: Session = Depends(get_db)) -> LifestyleStatsResponse:
    target_month = month or datetime.now(UTC).strftime("%Y-%m")
    return LifestyleStatsResponse(**lifestyle_stats(db, target_month))
