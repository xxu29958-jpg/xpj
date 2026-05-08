from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_app_context
from app.schemas import AuthCheckResponse
from app.tenants import AuthContext


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check", response_model=AuthCheckResponse)
def check_auth(auth: AuthContext = Depends(get_current_app_context)) -> AuthCheckResponse:
    return AuthCheckResponse(tenant_name=auth.tenant_name)
