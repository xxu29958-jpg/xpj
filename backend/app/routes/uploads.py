from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.network_boundary import is_loopback_request, upload_link_remote_key
from app.schemas import UploadResponse
from app.services.expense_service import create_pending_expense, enrich_pending_expense
from app.services.file_service import SavedUpload, delete_saved_upload, save_upload, save_upload_bytes
from app.services.identity_service import (
    authenticate_upload_link,
    find_active_upload_link,
    is_legacy_upload_token,
    upload_link_default_timezone,
)
from app.services.permission_service import require_create_pending_expense
from app.services.upload_link_throttle_service import (
    assert_daily_budget_available,
    enforce_remote_interval,
    record_upload_bytes,
    resolve_limits,
)
from app.tenants import AuthContext

if TYPE_CHECKING:
    from app.models import Expense, UploadLink

router = APIRouter(prefix="/api", tags=["uploads"])
upload_link_router = APIRouter(tags=["uploads"])
logger = logging.getLogger("ticketbox.upload")

IOS_SHORTCUT_FILE_FIELDS = ("file", "image", "photo", "screenshot")


async def _read_raw_body_limited(request: Request) -> bytes:
    limit = get_settings().max_upload_size_bytes
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise AppError("file_too_large", status_code=413)
        chunks.append(chunk)
    return b"".join(chunks)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


async def _save_request_upload(request: Request, tenant_id: str) -> tuple[SavedUpload, dict[str, int]]:
    timing_ms: dict[str, int] = {}
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        try:
            form_context = request.form(
                max_files=4,
                max_fields=12,
                max_part_size=get_settings().max_upload_size_bytes,
            )
            form_started_at = perf_counter()
            async with form_context as form:
                timing_ms["form_parse_ms"] = _elapsed_ms(form_started_at)
                for field_name in IOS_SHORTCUT_FILE_FIELDS:
                    value = form.get(field_name)
                    if isinstance(value, UploadFile):
                        save_started_at = perf_counter()
                        saved_file = await save_upload(value, tenant_id)
                        timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
                        return saved_file, timing_ms

                for value in form.values():
                    if isinstance(value, UploadFile):
                        save_started_at = perf_counter()
                        saved_file = await save_upload(value, tenant_id)
                        timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
                        return saved_file, timing_ms
        except StarletteHTTPException as exc:
            detail = str(exc.detail).lower()
            if "maximum size" in detail or "too large" in detail:
                raise AppError("file_too_large", status_code=413) from exc
            raise AppError("invalid_request", status_code=422) from exc

        raise AppError("invalid_request", "表单里没有找到图片文件。", status_code=422)

    read_started_at = perf_counter()
    body = await _read_raw_body_limited(request)
    timing_ms["body_read_ms"] = _elapsed_ms(read_started_at)
    if not body:
        raise AppError("invalid_request", status_code=422)

    save_started_at = perf_counter()
    saved_file = save_upload_bytes(
        body,
        tenant_id=tenant_id,
        filename=request.headers.get("X-Upload-Filename"),
        content_type=content_type,
    )
    timing_ms["file_save_ms"] = _elapsed_ms(save_started_at)
    return saved_file, timing_ms


def _upload_response(
    expense: Expense,
    saved_file: SavedUpload,
    duration_ms: int,
    timing_ms: dict[str, int],
) -> UploadResponse:
    return UploadResponse(
        id=expense.id,
        public_id=expense.public_id,
        status=expense.status,
        message="uploaded",
        image_hash=expense.image_hash or "",
        thumbnail_path=expense.thumbnail_path,
        duplicate_status=expense.duplicate_status,
        duplicate_of_id=expense.duplicate_of_id,
        upload_size_bytes=saved_file.size_bytes,
        duration_ms=duration_ms,
        timing_ms=timing_ms,
    )


def _create_pending_or_cleanup(db: Session, saved_file: SavedUpload, tenant_id: str, *, source: str) -> Expense:
    try:
        return create_pending_expense(db, saved_file, tenant_id, source=source, run_enrichment=False)
    except Exception:
        delete_saved_upload(saved_file)
        raise


async def _handle_upload(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    auth: AuthContext,
    db: Session,
    source: str,
    endpoint: str,
    timezone_name: str | None = None,
) -> UploadResponse:
    started_at = perf_counter()
    saved_file, timing_ms = await _save_request_upload(request, auth.ledger_id)
    db_started_at = perf_counter()
    expense = _create_pending_or_cleanup(db, saved_file, auth.ledger_id, source=source)
    timing_ms["db_create_ms"] = _elapsed_ms(db_started_at)
    duration_ms = _elapsed_ms(started_at)
    timing_ms["total_ms"] = duration_ms
    logger.info(
        "upload accepted endpoint=%s ledger=%s expense_id=%s bytes=%s media_type=%s duration_ms=%s timing_ms=%s duplicate=%s",
        endpoint,
        auth.ledger_id,
        expense.id,
        saved_file.size_bytes,
        saved_file.media_type,
        duration_ms,
        json.dumps(timing_ms, ensure_ascii=False, sort_keys=True),
        expense.duplicate_status,
    )
    background_tasks.add_task(enrich_pending_expense, expense.id, auth.ledger_id, timezone_name)
    return _upload_response(expense, saved_file, duration_ms, timing_ms)


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
    background_tasks: BackgroundTasks,
    timezone: str | None = Header(default=None, alias="X-Timezone"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> UploadResponse:
    return await _handle_upload(
        request=request,
        background_tasks=background_tasks,
        auth=auth,
        db=db,
        source="Android截图",
        endpoint="android_app",
        timezone_name=timezone,
    )


def _load_upload_link(db: Session, upload_key: str) -> UploadLink:
    link = find_active_upload_link(db, upload_key=upload_key)
    if link is None:
        raise AppError("invalid_token", status_code=401)
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
    background_tasks: BackgroundTasks,
    tz: str | None = None,
    timezone: str | None = Header(default=None, alias="X-Timezone"),
    db: Session = Depends(get_db),
) -> UploadResponse:
    auth = authenticate_upload_link(db, upload_key)
    require_create_pending_expense(auth)
    link = _load_upload_link(db, upload_key)
    limits = resolve_limits(link)
    is_loopback = is_loopback_request(request)
    # Per-remote interval and daily budget apply to public traffic only.
    # Loopback callers are the local owner / their own automation; we
    # already trust them via the surrounding network gate. The daily
    # budget would also block legitimate bulk imports from the owner.
    if not is_loopback:
        remote_key = upload_link_remote_key(request)
        enforce_remote_interval(
            db, link=link, remote_key=remote_key, limits=limits
        )
        assert_daily_budget_available(
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
    response = await _handle_upload(
        request=request,
        background_tasks=background_tasks,
        auth=auth,
        db=db,
        source="iPhone截图",
        endpoint="ios_upload_link",
        timezone_name=resolved_timezone,
    )
    if not is_loopback:
        record_upload_bytes(
            db, link=link, bytes_used=int(response.upload_size_bytes or 0)
        )
    return response
