from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import CurrencyCapabilityResponse
from app.services.currency_binding_service import get_capability
from app.tenants import AuthContext

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get(
    "/currency-capability",
    response_model=CurrencyCapabilityResponse,
)
def get_currency_capability(
    response: Response,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> CurrencyCapabilityResponse:
    _ = auth
    capability = get_capability(db)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return CurrencyCapabilityResponse(**capability.__dict__)
