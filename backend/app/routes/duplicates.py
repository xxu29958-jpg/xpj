from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import ExpenseResponse
from app.services.expense_service import list_duplicate_expenses
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/duplicates",
    tags=["duplicates"],
)


@router.get("", response_model=list[ExpenseResponse])
def get_duplicates(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> list[ExpenseResponse]:
    return list_duplicate_expenses(db, auth.tenant_id)
