from __future__ import annotations

import hashlib
from io import BytesIO
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile

from app.config import BACKEND_ROOT, get_settings
from app.errors import AppError, PathTraversalError
from app.tenants import DEFAULT_TENANT_ID


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}
CONTENT_TYPE_EXTENSION = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heic",
}
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
UPLOAD_REFERENCE_PREFIX = "uploads"


@dataclass(frozen=True)
class SavedUpload:
    relative_path: str
    image_hash: str
    media_type: str
    size_bytes: int


def _extension_from_metadata(filename: str | None, content_type: str | None) -> str | None:
    filename = filename or ""
    suffix = Path(filename).suffix.lower().removeprefix(".")
    if suffix in ALLOWED_EXTENSIONS:
        return suffix

    content_type = (content_type or "").lower()
    if content_type in CONTENT_TYPE_EXTENSION:
        return CONTENT_TYPE_EXTENSION[content_type]

    return None


def _extension_from_header(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in HEIC_BRANDS:
        return "heic"
    return None


def _looks_like_allowed_image(ext: str, header: bytes) -> bool:
    if ext in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if ext == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == "webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if ext == "heic":
        return len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in HEIC_BRANDS
    return False


def _is_decodable_image(ext: str, data: bytes) -> bool:
    try:
        from PIL import Image

        if ext == "heic":
            from pillow_heif import register_heif_opener

            register_heif_opener()
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except Exception:
        return False
    return True


async def save_upload(file: UploadFile, tenant_id: str) -> SavedUpload:
    data = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            data.extend(chunk)
            if len(data) > get_settings().max_upload_size_bytes:
                raise AppError("file_too_large", status_code=413)
    finally:
        await file.close()

    return save_upload_bytes(
        bytes(data),
        tenant_id=tenant_id,
        filename=file.filename,
        content_type=file.content_type,
    )


def save_upload_bytes(
    data: bytes,
    *,
    tenant_id: str,
    filename: str | None = None,
    content_type: str | None = None,
) -> SavedUpload:
    settings = get_settings()
    if len(data) > settings.max_upload_size_bytes:
        raise AppError("file_too_large", status_code=413)
    if not data:
        raise AppError("unsupported_file_type", status_code=400)

    header = data[:32]
    header_ext = _extension_from_header(header)
    metadata_ext = _extension_from_metadata(filename, content_type)
    ext = header_ext or metadata_ext
    if ext is None or not _looks_like_allowed_image(ext, header) or not _is_decodable_image(ext, data):
        raise AppError("unsupported_file_type", status_code=400)

    now = datetime.now(UTC)
    target_dir = settings.upload_dir / tenant_id / now.strftime("%Y") / now.strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{secrets.token_hex(16)}.{ext}"
    target_path = target_dir / filename
    hasher = hashlib.sha256(data)

    try:
        with target_path.open("wb") as output:
            output.write(data)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    relative_path = upload_reference_for_path(target_path)
    return SavedUpload(
        relative_path=relative_path,
        image_hash=hasher.hexdigest(),
        media_type=MEDIA_TYPES.get(target_path.suffix.lower(), "application/octet-stream"),
        size_bytes=len(data),
    )


def upload_reference_for_path(path: Path) -> str:
    """Return the stable DB reference for a file under configured UPLOAD_DIR."""

    settings = get_settings()
    resolved = path.resolve()
    try:
        return resolved.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        pass
    try:
        relative_to_upload_root = resolved.relative_to(settings.upload_dir.resolve())
    except ValueError as exc:
        raise PathTraversalError("Upload file escaped configured upload directory") from exc
    return f"{UPLOAD_REFERENCE_PREFIX}/{relative_to_upload_root.as_posix()}"


def _normalized_upload_parts(relative_path: str | None) -> tuple[str, ...] | None:
    if not relative_path:
        return None
    raw = str(relative_path)
    if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        return None
    normalized_parts = Path(raw.replace("\\", "/")).parts
    if any(part == ".." for part in normalized_parts):
        return None
    return tuple(str(part) for part in normalized_parts)


def _resolve_upload_reference(relative_path: str | None) -> Path | None:
    parts = _normalized_upload_parts(relative_path)
    if not parts:
        return None

    settings = get_settings()
    upload_dir = settings.upload_dir.resolve()
    legacy_candidate = (BACKEND_ROOT / Path(*parts)).resolve()
    if _is_under_path(legacy_candidate, upload_dir):
        return legacy_candidate
    if parts[0] == UPLOAD_REFERENCE_PREFIX:
        candidate = (upload_dir / Path(*parts[1:])).resolve()
    else:
        # Legacy v0.2 rows stored paths relative to BACKEND_ROOT.
        candidate = legacy_candidate
    if not _is_under_path(candidate, upload_dir):
        return None
    return candidate


def delete_relative_upload(relative_path: str | None) -> None:
    if not relative_path:
        return

    candidate = _resolve_upload_reference(relative_path)
    if candidate is None:
        return
    candidate.unlink(missing_ok=True)


def delete_saved_upload(saved_upload: SavedUpload) -> None:
    delete_relative_upload(saved_upload.relative_path)


def _tenant_upload_dir(tenant_id: str) -> Path:
    return (get_settings().upload_dir / tenant_id).resolve()


def _is_under_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _is_legacy_unscoped_upload(candidate: Path, upload_dir: Path, tenant_id: str) -> bool:
    """Allow pre-v0.3 paths shaped as uploads/YYYY/MM/file.

    New uploads are ledger-scoped under uploads/<ledger_id>/YYYY/MM. Legacy
    rows without a ledger prefix only existed before family ledgers, so they
    belong to the default legacy ledger. Non-default ledgers must migrate those
    files into their own scoped directory before they are readable.
    """
    if tenant_id != DEFAULT_TENANT_ID:
        return False
    try:
        parts = candidate.relative_to(upload_dir).parts
    except ValueError:
        return False
    if len(parts) < 3:
        return False
    year, month = parts[0], parts[1]
    return (
        len(year) == 4
        and year.isdigit()
        and len(month) == 2
        and month.isdigit()
        and 1 <= int(month) <= 12
    )


def resolve_upload_path_for_tenant(relative_path: str | None, tenant_id: str) -> Path | None:
    settings = get_settings()
    candidate = _resolve_upload_reference(relative_path)
    if candidate is None:
        return None

    tenant_dir = _tenant_upload_dir(tenant_id)
    if not _is_under_path(candidate, tenant_dir) and not _is_legacy_unscoped_upload(
        candidate, settings.upload_dir.resolve(), tenant_id
    ):
        return None
    return candidate


def resolve_protected_image(relative_path: str | None, tenant_id: str) -> tuple[Path, str]:
    """Resolve a relative image path that the caller has already authorized.

    The caller is responsible for verifying that the owning expense belongs to
    ``tenant_id``. This function only enforces filesystem-level safety:

    - reject empty / missing paths
    - reject absolute paths and Windows drive specs
    - reject ``..`` traversal that escapes the uploads root
    - require the resolved file to live inside the uploads root

    Legacy v0.2 paths (``uploads/YYYY/MM/foo.png`` without a tenant prefix) are
    accepted only for the default legacy ledger as long as they remain inside
    the uploads root. New uploads are written under ``uploads/<tenant>/...`` but
    old files are not moved on startup (see docs/runbook/ROLLBACK.md).
    """

    if not relative_path:
        raise AppError("image_not_found", status_code=404)

    candidate = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if candidate is None:
        raise AppError("image_not_found", status_code=404)

    if not candidate.is_file():
        raise AppError("image_not_found", status_code=404)

    return candidate, MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
