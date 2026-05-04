from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import verify_app_token
from app.schemas import AuthCheckResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check", response_model=AuthCheckResponse, dependencies=[Depends(verify_app_token)])
def check_auth() -> AuthCheckResponse:
    return AuthCheckResponse()
