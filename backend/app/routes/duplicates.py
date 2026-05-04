from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import verify_app_token
from app.database import get_db
from app.schemas import ExpenseResponse
from app.services.expense_service import list_duplicate_expenses


router = APIRouter(
    prefix="/api/duplicates",
    tags=["duplicates"],
    dependencies=[Depends(verify_app_token)],
)


@router.get("", response_model=list[ExpenseResponse])
def get_duplicates(db: Session = Depends(get_db)) -> list[ExpenseResponse]:
    return list_duplicate_expenses(db)
