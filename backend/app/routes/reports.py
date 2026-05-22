from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import get_db
from app.schemas import ReportsOverviewResponse
from app.services.reports_service import export_reports_overview_csv, reports_overview
from app.services.time_service import current_month
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
)


@router.get("/overview", response_model=ReportsOverviewResponse)
def get_reports_overview(
    month: str | None = None,
    granularity: Literal["day", "week", "month"] = "day",
    top_n: int = Query(default=8, ge=1, le=20),
    merchant_category: str | None = Query(default=None, max_length=64),
    ranking_metric: Literal["amount", "count"] = "amount",
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ReportsOverviewResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
    return ReportsOverviewResponse(
        **reports_overview(
            db,
            month=target_month,
            tenant_id=auth.tenant_id,
            timezone_name=timezone_name,
            granularity=granularity,
            top_n=top_n,
            merchant_category=merchant_category,
            ranking_metric=ranking_metric,
        )
    )


@router.get("/overview.csv")
def get_reports_overview_csv(
    month: str | None = None,
    granularity: Literal["day", "week", "month"] = "day",
    top_n: int = Query(default=8, ge=1, le=20),
    merchant_category: str | None = Query(default=None, max_length=64),
    ranking_metric: Literal["amount", "count"] = "amount",
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> Response:
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
    content = "\ufeff" + export_reports_overview_csv(
        db,
        month=target_month,
        tenant_id=auth.tenant_id,
        timezone_name=timezone_name,
        granularity=granularity,
        top_n=top_n,
        merchant_category=merchant_category,
        ranking_metric=ranking_metric,
    )
    filename = f"ticketbox-reports-overview-{target_month}-{granularity}"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
