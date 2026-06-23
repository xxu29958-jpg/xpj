"""Owner-facing "My Devices" HTTP routes (issue #65 slice 6a).

* ``GET  /api/ledgers/{ledger_id}/devices`` — owner lists the ledger's devices
* ``POST /api/ledgers/{ledger_id}/devices/{public_id}/rename`` — owner renames
* ``POST /api/ledgers/{ledger_id}/devices/{public_id}/revoke`` — owner revokes
* ``POST /api/ledgers/{ledger_id}/devices/pairing-codes`` — owner mints a code
  for "add a device" (the new device then pairs via the existing join flow)

These are the app-token equivalents of the loopback-only ``/api/admin/devices``
and ``/owner`` routes — a normal owner could not manage their devices from the
app before. The ``get_current_member_manager_context`` guard (app token,
path-ledger-bound, owner role) gives 401 (no token) / 403 (viewer/member) / 404
(wrong ledger); the service scopes every op to the path ledger.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_member_manager_context
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
from app.tenants import AuthContext

router = APIRouter(tags=["my-devices"])


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
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> MyDeviceListResponse:
    devices = owner_device_service.list_my_devices(db, auth)
    return MyDeviceListResponse(devices=[_to_response(d) for d in devices])


@router.post(
    "/api/ledgers/{ledger_id}/devices/{public_id}/rename",
    response_model=MyDeviceResponse,
)
def rename_my_device_endpoint(
    ledger_id: str,
    public_id: str,
    payload: AdminDeviceRenameRequest,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> MyDeviceResponse:
    device = owner_device_service.rename_my_device(
        db, auth, public_id=public_id, new_name=payload.device_name
    )
    return _to_response(device)


@router.post(
    "/api/ledgers/{ledger_id}/devices/{public_id}/revoke",
    response_model=MyDeviceResponse,
)
def revoke_my_device_endpoint(
    ledger_id: str,
    public_id: str,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> MyDeviceResponse:
    device = owner_device_service.revoke_my_device(db, auth, public_id=public_id)
    return _to_response(device)


@router.post(
    "/api/ledgers/{ledger_id}/devices/pairing-codes",
    response_model=PairingCodeResponse,
    status_code=201,
)
def create_my_pairing_code_endpoint(
    ledger_id: str,
    payload: PairingCodeCreateRequest,
    auth: AuthContext = Depends(get_current_member_manager_context),
    db: Session = Depends(get_db),
) -> PairingCodeResponse:
    result = owner_device_service.create_my_pairing_code(
        db, auth, device_name_hint=payload.device_name_hint, ttl_minutes=payload.ttl_minutes
    )
    return PairingCodeResponse(
        pairing_code=result.pairing_code,
        ledger_name=result.ledger_name,
        expires_at=result.expires_at,
    )
