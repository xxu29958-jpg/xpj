from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.auth import get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.network_boundary import is_loopback_request, upload_link_remote_key
from app.routes._upload_request import handle_upload
from app.schemas import UploadResponse
from app.services.identity_service import (
    UPLOAD_LINK_INVALID_MESSAGE,
    authenticate_upload_link,
    find_active_upload_link,
    is_legacy_upload_token,
    lock_and_revalidate_upload_link_commit_context,
    upload_link_default_timezone,
)
from app.services.permission_service import require_create_pending_expense
from app.services.upload_link_throttle_service import (
    enforce_remote_interval,
    finalize_upload_bytes,
    release_upload_bytes,
    reserve_upload_bytes,
    resolve_limits,
)
from app.tenants import AuthContext

if TYPE_CHECKING:
    from app.models import UploadLink

router = APIRouter(prefix="/api", tags=["uploads"])
upload_link_router = APIRouter(tags=["uploads"])


def _reject_legacy_upload_endpoint(upload_token: str | None) -> None:
    """Legacy-detector for retired Upload-Token endpoints.

    v0.3 retired ``Upload-Token`` auth entirely. The two routes below stay
    registered only to give old iOS Shortcuts / Android builds a
    machine-readable hint (``legacy_auth_removed``) so they know to re-pair —
    a bare 404 would silently break those clients. Any other value still gets
    a normal ``invalid_token`` so this isn't a probe-friendly oracle.
    """

    if is_legacy_upload_token(upload_token):
        raise AppError(
            "legacy_auth_removed",
            "请使用新版 iOS 上传链接。",
            status_code=401,
        )
    raise AppError("invalid_token", status_code=401)


@router.get("/upload/check", include_in_schema=False)
def upload_check_legacy_gone(
    upload_token: str | None = Header(default=None, alias="Upload-Token"),
) -> None:
    _reject_legacy_upload_endpoint(upload_token)


@router.post("/upload-screenshot", include_in_schema=False)
async def upload_screenshot_legacy_gone(
    upload_token: str | None = Header(default=None, alias="Upload-Token"),
) -> None:
    _reject_legacy_upload_endpoint(upload_token)


@router.post(
    "/app/upload-screenshot",
    response_model=UploadResponse,
)
async def app_upload_screenshot(
    request: Request,
    timezone: str | None = Header(default=None, alias="X-Timezone"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> UploadResponse:
    return await handle_upload(
        request=request,
        tenant_id=auth.ledger_id,
        db=db,
        source="Android截图",
        endpoint="android_app",
        initiator_account_id=auth.account_id,
        initiator_device_id=auth.device_id,
        timezone_name=timezone,
    )


def _load_upload_link(db: Session, upload_key: str) -> UploadLink:
    link = find_active_upload_link(db, upload_key=upload_key)
    if link is None:
        raise AppError("invalid_token", UPLOAD_LINK_INVALID_MESSAGE, status_code=401)
    return link


def _declared_content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


@upload_link_router.post(
    "/u/{upload_key}",
    response_model=UploadResponse,
)
async def upload_link_screenshot(
    upload_key: str,
    request: Request,
    tz: str | None = None,
    timezone: str | None = Header(default=None, alias="X-Timezone"),
    db: Session = Depends(get_db),
) -> UploadResponse:
    auth = authenticate_upload_link(db, upload_key)
    require_create_pending_expense(auth)
    link = _load_upload_link(db, upload_key)
    limits = resolve_limits(link)
    is_loopback = is_loopback_request(request)
    reservation = None
    # Per-remote interval and daily budget apply to public traffic only.
    # Loopback callers are the local owner / their own automation; we
    # already trust them via the surrounding network gate. The daily
    # budget would also block legitimate bulk imports from the owner.
    if not is_loopback:
        remote_key = upload_link_remote_key(request)
        enforce_remote_interval(db, link=link, remote_key=remote_key, limits=limits)
        db.commit()
        reservation = reserve_upload_bytes(
            db,
            link=link,
            declared_content_length=_declared_content_length(request),
            limits=limits,
        )
    resolved_timezone = (
        (timezone or "").strip()
        or (tz or "").strip()
        or (upload_link_default_timezone(db, upload_key) or "").strip()
        or get_settings().ocr_default_timezone
    )
    reservation_finalized = False

    def revalidate_before_commit() -> None:
        refreshed_auth = lock_and_revalidate_upload_link_commit_context(
            db,
            upload_key=upload_key,
            expected_auth=auth,
        )
        require_create_pending_expense(refreshed_auth)

    try:
        response = await handle_upload(
            request=request,
            tenant_id=auth.ledger_id,
            db=db,
            source="iPhone截图",
            endpoint="ios_upload_link",
            initiator_account_id=auth.account_id,
            initiator_device_id=auth.device_id,
            timezone_name=resolved_timezone,
            max_size_bytes=(reservation.reserved_bytes if reservation and reservation.reserved_bytes > 0 else None),
            commit_guard=revalidate_before_commit,
        )
        finalize_upload_bytes(
            db,
            reservation=reservation,
            bytes_used=int(response.upload_size_bytes or 0),
        )
        reservation_finalized = True
        return response
    finally:
        if not reservation_finalized:
            release_upload_bytes(db, reservation=reservation)
