from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import (
    RuntimeCompatibilitySnapshotResponse,
    RuntimeCurrencyCapabilityResponse,
    RuntimeProductCapabilitiesResponse,
)
from app.services.runtime_compatibility_service import runtime_compatibility_snapshot
from app.tenants import AuthContext

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get(
    "/runtime-compatibility",
    response_model=RuntimeCompatibilitySnapshotResponse,
)
def get_runtime_compatibility(
    response: Response,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RuntimeCompatibilitySnapshotResponse:
    _ = auth
    snapshot = runtime_compatibility_snapshot(db)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return RuntimeCompatibilitySnapshotResponse(
        contract=snapshot.contract,
        observed_at=snapshot.observed_at,
        api_version=snapshot.api_version,
        api_version_header=snapshot.api_version_header,
        read_compatibility=snapshot.read_compatibility,
        write_compatibility=snapshot.write_compatibility,
        legacy_write_compatibility=snapshot.legacy_write_compatibility,
        capabilities=RuntimeProductCapabilitiesResponse(
            currency=RuntimeCurrencyCapabilityResponse(**snapshot.currency.__dict__),
        ),
    )
