from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    BudgetMonthlyArchiveRequest,
    BudgetMonthlyArchiveResponse,
    BudgetMonthlyResponse,
    BudgetMonthlyUpdateRequest,
)
from app.schemas._budget_history import BudgetHistoryResponse
from app.services.budget_command_service import save_monthly_budget
from app.services.budget_history_service import budget_history
from app.services.budget_service import (
    archive_monthly_budget,
    get_monthly_budget,
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> BudgetMonthlyResponse:
    return save_monthly_budget(
        db,
        tenant_id=auth.tenant_id,
        month=month,
        payload=payload,
        actor_account_id=auth.account_id,
        idempotency_key=idempotency_key,
        timezone_name=timezone,
    )


@router.get("/monthly/{month}/history", response_model=BudgetHistoryResponse)
def get_budget_history(
    month: str,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> BudgetHistoryResponse:
    return budget_history(db, tenant_id=auth.tenant_id, month=month, before_version=before_version, limit=limit)


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
