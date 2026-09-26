from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context
from app.database import get_db
from app.schemas._monthly_arrangement import (
    MonthlyArrangementDto,
    MonthlyArrangementHistory,
    MonthlyArrangementSaveRequest,
    MonthlyArrangementState,
)
from app.services.monthly_arrangement_service import (
    list_monthly_arrangement_history,
    read_monthly_arrangement,
    save_monthly_arrangement,
)
from app.services.spending_contract_service import clean_month
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget/arrangements", tags=["monthly-arrangements"])


@router.get("/{month}", response_model=MonthlyArrangementState)
def get_monthly_arrangement(month: str, auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db)) -> MonthlyArrangementState:
    month = clean_month(month)
    return MonthlyArrangementState(ledger_id=auth.tenant_id, month=month,
        arrangement=read_monthly_arrangement(db, tenant_id=auth.tenant_id, month=month))


@router.put("/{month}", response_model=MonthlyArrangementDto)
def put_monthly_arrangement(month: str, payload: MonthlyArrangementSaveRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context), db: Session = Depends(get_db)) -> MonthlyArrangementDto:
    return save_monthly_arrangement(db, tenant_id=auth.tenant_id, month=month, payload=payload,
        actor_account_id=auth.account_id, idempotency_key=idempotency_key)


@router.get("/{month}/history", response_model=MonthlyArrangementHistory)
def get_monthly_arrangement_history(month: str, before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50), auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db)) -> MonthlyArrangementHistory:
    return list_monthly_arrangement_history(db, tenant_id=auth.tenant_id, month=month,
        before_version=before_version, limit=limit)
