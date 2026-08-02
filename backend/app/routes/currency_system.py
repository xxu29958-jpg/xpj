from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context
from app.database import get_db
from app.schemas import (
    CurrencyCapabilityResponse,
    RuntimeCompatibilitySnapshotResponse,
    RuntimeCurrencyCapabilityResponse,
    RuntimeProductCapabilitiesResponse,
)
from app.services.currency_binding_service import (
    get_capability,
    readable_or_initialization_home_currency_code,
)
from app.services.runtime_compatibility_service import runtime_compatibility_snapshot
from app.tenants import AuthContext

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get(
    "/currency-capability",
    response_model=CurrencyCapabilityResponse,
    deprecated=True,
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
    return CurrencyCapabilityResponse(
        **{
            **capability.__dict__,
            # Preserve the legacy endpoint's CNY-only initialization contract.
            # Current clients use /runtime-compatibility for non-CNY setup.
            "initialization_offer": readable_or_initialization_home_currency_code(
                db
            )
            if capability.state == "EMPTY"
            else None,
        }
    )


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
