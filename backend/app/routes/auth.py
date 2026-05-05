from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_app_tenant
from app.schemas import AuthCheckResponse
from app.tenants import Tenant


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check", response_model=AuthCheckResponse)
def check_auth(tenant: Tenant = Depends(get_current_app_tenant)) -> AuthCheckResponse:
    return AuthCheckResponse(tenant_name=tenant.name)
