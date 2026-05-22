"""v0.4-alpha3 — Smart Ledger insights endpoints (read-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.schemas import (
    DataQualitySummaryResponse,
    RecurringCandidateItem,
    RecurringCandidatesResponse,
)
from app.services.data_quality_service import data_quality_summary
from app.services.insights_service import recurring_candidates
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/insights",
    tags=["insights"],
)


@router.get("/recurring-candidates", response_model=RecurringCandidatesResponse)
def get_recurring_candidates(
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RecurringCandidatesResponse:
    tz = timezone or get_settings().ocr_default_timezone
    items = recurring_candidates(db, tenant_id=auth.tenant_id, timezone_name=tz)
    return RecurringCandidatesResponse(
        items=[RecurringCandidateItem(**item) for item in items],
    )


@router.get("/data-quality", response_model=DataQualitySummaryResponse)
def get_data_quality_summary(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DataQualitySummaryResponse:
    summary = data_quality_summary(db, tenant_id=auth.tenant_id)
    return DataQualitySummaryResponse(**summary.to_dict())
