from __future__ import annotations

import hashlib
from io import BytesIO
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import UploadFile

from app.config import BACKEND_ROOT, get_settings
from app.errors import AppError


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

    relative_path = target_path.relative_to(BACKEND_ROOT).as_posix()
    return SavedUpload(
        relative_path=relative_path,
        image_hash=hasher.hexdigest(),
        media_type=MEDIA_TYPES.get(target_path.suffix.lower(), "application/octet-stream"),
        size_bytes=len(data),
    )


def delete_relative_upload(relative_path: str | None) -> None:
    if not relative_path:
        return

    settings = get_settings()
    candidate = (BACKEND_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(settings.upload_dir)
    except ValueError:
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


def resolve_protected_image(relative_path: str | None, tenant_id: str) -> tuple[Path, str]:
    """Resolve a relative image path that the caller has already authorized.

    The caller is responsible for verifying that the owning expense belongs to
    ``tenant_id``. This function only enforces filesystem-level safety:

    - reject empty / missing paths
    - reject absolute paths and Windows drive specs
    - reject ``..`` traversal that escapes the uploads root
    - require the resolved file to live inside the uploads root

    Legacy v0.2 paths (``uploads/YYYY/MM/foo.png`` without a tenant prefix) are
    accepted as long as they remain inside the uploads root. New uploads are
    written under ``uploads/<tenant>/...`` but old files are not moved on
    startup (see docs/ROLLBACK.md).
    """

    if not relative_path:
        raise AppError("image_not_found", status_code=404)

    raw = str(relative_path)
    # Reject absolute paths, Windows drive specs, and explicit traversal tokens
    # before touching the filesystem so the error surface is uniform.
    if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        raise AppError("image_not_found", status_code=404)
    normalized_parts = Path(raw.replace("\\", "/")).parts
    if any(part == ".." for part in normalized_parts):
        raise AppError("image_not_found", status_code=404)

    settings = get_settings()
    candidate = (BACKEND_ROOT / raw).resolve()
    if not _is_under_path(candidate, settings.upload_dir):
        raise AppError("image_not_found", status_code=404)

    if not candidate.is_file():
        raise AppError("image_not_found", status_code=404)

    return candidate, MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
