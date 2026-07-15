"""Account-scoped "My Devices" HTTP routes.

* ``GET  /api/ledgers/{ledger_id}/devices`` — member lists their Account devices
* ``POST /api/ledgers/{ledger_id}/devices/{public_id}/rename`` — member renames
* ``POST /api/ledgers/{ledger_id}/devices/{public_id}/revoke`` — member revokes
* ``POST /api/ledgers/{ledger_id}/devices/{public_id}/delete`` — member removes a
  revoked device permanently (204; must be revoked first)
* ``POST /api/ledgers/{ledger_id}/devices/pairing-codes`` — member mints an add
  code or explicitly recovers one of their existing Devices

Device authority belongs to the authenticated Account, not to the Account's
role in one ledger. A valid Account/Device session can manage only its own
devices; creating a pairing code still requires active membership in the path
ledger. Ledger owners remove another member's access through Membership.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_principal, get_current_ledger_app_context
from app.database import get_db
from app.schemas import (
    AdminDeviceRenameRequest,
    MyDeviceListResponse,
    MyDeviceResponse,
    PairingCodeCreateRequest,
    PairingCodeResponse,
)
from app.services import owner_device_service
from app.services.owner_device_service import MyDevice
from app.tenants import AuthContext, SessionPrincipal

router = APIRouter(tags=["my-devices"])


def _account_device_principal(
    ledger_id: str,
    principal: SessionPrincipal = Depends(get_current_app_principal),
    db: Session = Depends(get_db),
) -> SessionPrincipal:
    return owner_device_service.require_account_device_ledger_route(
        db,
        principal,
        ledger_id,
    )


def _to_response(device: MyDevice) -> MyDeviceResponse:
    summary = device.summary
    return MyDeviceResponse(
        public_id=summary.public_id,
        device_name=summary.device_name,
        platform=summary.platform,
        last_seen_at=summary.last_seen_at,
        created_at=summary.created_at,
        revoked_at=summary.revoked_at,
        is_current=device.is_current,
    )


@router.get("/api/ledgers/{ledger_id}/devices", response_model=MyDeviceListResponse)
def list_my_devices_endpoint(
    ledger_id: str,
    principal: SessionPrincipal = Depends(_account_device_principal),
    db: Session = Depends(get_db),
) -> MyDeviceListResponse:
    devices = owner_device_service.list_my_devices(db, principal)
    return MyDeviceListResponse(devices=[_to_response(d) for d in devices])


@router.post(
    "/api/ledgers/{ledger_id}/devices/{public_id}/rename",
    response_model=MyDeviceResponse,
)
def rename_my_device_endpoint(
    ledger_id: str,
    public_id: str,
    payload: AdminDeviceRenameRequest,
    principal: SessionPrincipal = Depends(_account_device_principal),
    db: Session = Depends(get_db),
) -> MyDeviceResponse:
    device = owner_device_service.rename_my_device(
        db, principal, public_id=public_id, new_name=payload.device_name
    )
    return _to_response(device)


@router.post(
    "/api/ledgers/{ledger_id}/devices/{public_id}/revoke",
    response_model=MyDeviceResponse,
)
def revoke_my_device_endpoint(
    ledger_id: str,
    public_id: str,
    principal: SessionPrincipal = Depends(_account_device_principal),
    db: Session = Depends(get_db),
) -> MyDeviceResponse:
    device = owner_device_service.revoke_my_device(
        db,
        principal,
        public_id=public_id,
    )
    return _to_response(device)


@router.post(
    "/api/ledgers/{ledger_id}/devices/{public_id}/delete",
    status_code=204,
)
def delete_my_device_endpoint(
    ledger_id: str,
    public_id: str,
    principal: SessionPrincipal = Depends(_account_device_principal),
    db: Session = Depends(get_db),
) -> Response:
    owner_device_service.delete_my_device(db, principal, public_id=public_id)
    return Response(status_code=204)


@router.post(
    "/api/ledgers/{ledger_id}/devices/pairing-codes",
    response_model=PairingCodeResponse,
    status_code=201,
)
def create_my_pairing_code_endpoint(
    ledger_id: str,
    payload: PairingCodeCreateRequest,
    auth: AuthContext = Depends(get_current_ledger_app_context),
    db: Session = Depends(get_db),
) -> PairingCodeResponse:
    result = owner_device_service.create_my_pairing_code(
        db,
        auth,
        device_name_hint=payload.device_name_hint,
        recovery_device_public_id=payload.recovery_device_public_id,
        ttl_minutes=payload.ttl_minutes,
    )
    return PairingCodeResponse(
        pairing_code=result.pairing_code,
        ledger_name=result.ledger_name,
        expires_at=result.expires_at,
    )
