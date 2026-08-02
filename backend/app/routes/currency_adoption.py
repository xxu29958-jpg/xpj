from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_admin_context
from app.database import get_db
from app.network_boundary import require_maintenance_local
from app.schemas import (
    CurrencyAdoptionConfirmRequest,
    CurrencyAdoptionPreviewResponse,
    CurrencyAdoptionReceiptResponse,
)
from app.services.currency_adoption_service import (
    adopt_currency_binding,
    adoption_preview,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/maintenance/currency-binding",
    tags=["maintenance"],
    dependencies=[Depends(require_maintenance_local)],
)


@router.get("/adoption", response_model=CurrencyAdoptionPreviewResponse)
def get_currency_adoption_preview(
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> CurrencyAdoptionPreviewResponse:
    _ = auth
    return CurrencyAdoptionPreviewResponse(**adoption_preview(db).__dict__)


@router.post("/adoption", response_model=CurrencyAdoptionReceiptResponse)
def post_currency_adoption(
    payload: CurrencyAdoptionConfirmRequest,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> CurrencyAdoptionReceiptResponse:
    receipt = adopt_currency_binding(
        db,
        auth=auth,
        idempotency_key=idempotency_key,
        expected_contract_version=payload.currency_contract_version,
        home_code=payload.home_currency_code,
        expected_state=payload.expected_state,
        expected_revision=payload.expected_binding_revision,
        expected_evidence_sha256=payload.expected_evidence_sha256,
        reason=payload.reason,
    )
    return CurrencyAdoptionReceiptResponse(**receipt.__dict__)
