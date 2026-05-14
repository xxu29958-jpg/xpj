from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import DashboardCardsResponse, DashboardCardsUpdateRequest
from app.services.dashboard_service import list_dashboard_cards, update_dashboard_cards
from app.tenants import AuthContext


router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)


@router.get("/cards", response_model=DashboardCardsResponse)
def get_dashboard_cards(
    surface: str = Query(default="android"),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DashboardCardsResponse:
    return list_dashboard_cards(db, tenant_id=auth.tenant_id, surface=surface)


@router.put("/cards", response_model=DashboardCardsResponse)
def put_dashboard_cards(
    payload: DashboardCardsUpdateRequest,
    surface: str = Query(default="android"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DashboardCardsResponse:
    return update_dashboard_cards(
        db,
        tenant_id=auth.tenant_id,
        surface=surface,
        payload=payload,
    )
