from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    BudgetMonthlyArchiveRequest,
    BudgetMonthlyArchiveResponse,
    BudgetMonthlyResponse,
    BudgetMonthlyUpdateRequest,
)
from app.services.budget_service import (
    archive_monthly_budget,
    get_monthly_budget,
    upsert_monthly_budget,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/budgets",
    tags=["budgets"],
)


@router.get("/monthly", response_model=BudgetMonthlyResponse)
def get_budget_monthly(
    month: str,
    timezone: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetMonthlyResponse:
    return get_monthly_budget(
        db,
        tenant_id=auth.tenant_id,
        month=month,
        timezone_name=timezone,
    )


@router.put("/monthly/{month}", response_model=BudgetMonthlyResponse)
def put_budget_monthly(
    month: str,
    payload: BudgetMonthlyUpdateRequest,
    timezone: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> BudgetMonthlyResponse:
    return upsert_monthly_budget(
        db,
        tenant_id=auth.tenant_id,
        month=month,
        payload=payload,
        timezone_name=timezone,
    )


@router.delete("/monthly/{month}", response_model=BudgetMonthlyArchiveResponse)
def delete_budget_monthly(
    month: str,
    payload: BudgetMonthlyArchiveRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> BudgetMonthlyArchiveResponse:
    archive_monthly_budget(
        db,
        tenant_id=auth.tenant_id,
        month=month,
        expected_row_version=payload.expected_row_version,
    )
    return BudgetMonthlyArchiveResponse(message="月度预算已移入回收站。")
