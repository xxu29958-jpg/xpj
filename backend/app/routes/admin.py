"""Admin device & UploadLink management API.

v0.3.1-alpha2 Phase 3 / 4. All endpoints require an ``admin``-scope session
token (see :func:`app.auth.get_current_admin_context`). ``app``-scope tokens
must NOT reach this router; the dependency returns ``permission_denied`` before
the body of any handler runs.

URL conventions follow the rest of the codebase: ``POST`` for verbs (revoke /
rotate / rename) and ``GET`` for listings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_admin_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.models import Device
from app.network_boundary import require_admin_network_boundary
from app.schemas import (
    AdminDeviceRenameRequest,
    AdminDeviceResponse,
    AdminUploadLinkCreateRequest,
    AdminUploadLinkResponse,
    AdminUploadLinkSecretResponse,
)
from app.services import admin_service
from app.services.admin_scope_service import manageable_ledger_ids
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_network_boundary)],
)


def _device_response(summary: admin_service.DeviceSummary) -> AdminDeviceResponse:
    return AdminDeviceResponse(**summary.__dict__)


def _link_response(summary: admin_service.UploadLinkSummary) -> AdminUploadLinkResponse:
    return AdminUploadLinkResponse(**summary.__dict__)


def _current_device_public_id(db: Session, auth: AuthContext) -> str:
    device = db.get(Device, auth.device_id)
    return device.public_id if device is not None else ""


@router.get("/devices", response_model=list[AdminDeviceResponse])
def list_devices_endpoint(
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> list[AdminDeviceResponse]:
    return [
        _device_response(s)
        for s in admin_service.list_devices(db, ledger_ids=manageable_ledger_ids(db, auth))
    ]


@router.post(
    "/devices/{public_id}/revoke",
    response_model=AdminDeviceResponse,
)
def revoke_device_endpoint(
    public_id: str,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminDeviceResponse:
    current = _current_device_public_id(db, auth)
    summary = admin_service.revoke_device(
        db,
        public_id=public_id,
        current_device_public_id=current,
        ledger_ids=manageable_ledger_ids(db, auth),
    )
    return _device_response(summary)


@router.post(
    "/devices/{public_id}/rename",
    response_model=AdminDeviceResponse,
)
def rename_device_endpoint(
    public_id: str,
    payload: AdminDeviceRenameRequest,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminDeviceResponse:
    summary = admin_service.rename_device(
        db,
        public_id=public_id,
        new_name=payload.device_name,
        ledger_ids=manageable_ledger_ids(db, auth),
    )
    return _device_response(summary)


@router.get("/upload-links", response_model=list[AdminUploadLinkResponse])
def list_upload_links_endpoint(
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> list[AdminUploadLinkResponse]:
    return [
        _link_response(s)
        for s in admin_service.list_upload_links(db, ledger_ids=manageable_ledger_ids(db, auth))
    ]


@router.post(
    "/upload-links",
    response_model=AdminUploadLinkSecretResponse,
)
def create_upload_link_endpoint(
    payload: AdminUploadLinkCreateRequest,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminUploadLinkSecretResponse:
    target_ledger = (payload.ledger_id or auth.ledger_id or "").strip()
    if not target_ledger:
        raise AppError("invalid_request", "缺少 ledger_id。", status_code=422)
    default_tz = (
        payload.default_timezone or get_settings().ocr_default_timezone or "Asia/Shanghai"
    ).strip() or "Asia/Shanghai"
    summary, secret = admin_service.create_upload_link(
        db,
        ledger_id=target_ledger,
        admin_account_id=auth.account_id,
        default_timezone=default_tz,
        ledger_ids=manageable_ledger_ids(db, auth),
    )
    return AdminUploadLinkSecretResponse(
        link=_link_response(summary),
        upload_url_path=secret.upload_url_path,
        default_timezone=secret.default_timezone,
    )


@router.post(
    "/upload-links/{public_id}/rotate",
    response_model=AdminUploadLinkSecretResponse,
)
def rotate_upload_link_endpoint(
    public_id: str,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminUploadLinkSecretResponse:
    summary, secret = admin_service.rotate_upload_link(
        db,
        public_id=public_id,
        ledger_ids=manageable_ledger_ids(db, auth),
    )
    return AdminUploadLinkSecretResponse(
        link=_link_response(summary),
        upload_url_path=secret.upload_url_path,
        default_timezone=secret.default_timezone,
    )


@router.post(
    "/upload-links/{public_id}/revoke",
    response_model=AdminUploadLinkResponse,
)
def revoke_upload_link_endpoint(
    public_id: str,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminUploadLinkResponse:
    return _link_response(
        admin_service.revoke_upload_link(
            db,
            public_id=public_id,
            ledger_ids=manageable_ledger_ids(db, auth),
        )
    )


@router.post(
    "/upload-links/{public_id}/extend",
    response_model=AdminUploadLinkResponse,
)
def extend_upload_link_endpoint(
    public_id: str,
    auth: AuthContext = Depends(get_current_admin_context),
    db: Session = Depends(get_db),
) -> AdminUploadLinkResponse:
    return _link_response(
        admin_service.extend_upload_link(
            db,
            public_id=public_id,
            ledger_ids=manageable_ledger_ids(db, auth),
        )
    )
