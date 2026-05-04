from __future__ import annotations

import hashlib
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


def _extension_for(file: UploadFile) -> str:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower().removeprefix(".")
    if suffix in ALLOWED_EXTENSIONS:
        return suffix

    content_type = (file.content_type or "").lower()
    if content_type in CONTENT_TYPE_EXTENSION:
        return CONTENT_TYPE_EXTENSION[content_type]

    raise AppError("unsupported_file_type", status_code=400)


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


async def save_upload(file: UploadFile) -> SavedUpload:
    settings = get_settings()
    ext = _extension_for(file)
    now = datetime.now(UTC)
    target_dir = settings.upload_dir / now.strftime("%Y") / now.strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{secrets.token_hex(16)}.{ext}"
    target_path = target_dir / filename
    hasher = hashlib.sha256()
    total_size = 0
    header = b""
    image_header_checked = False

    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > settings.max_upload_size_bytes:
                    raise AppError("file_too_large", status_code=413)
                if not image_header_checked:
                    header = (header + chunk)[:32]
                    if len(header) >= 12 or ext in {"jpg", "jpeg", "png"}:
                        if not _looks_like_allowed_image(ext, header):
                            raise AppError("unsupported_file_type", status_code=400)
                        image_header_checked = True
                hasher.update(chunk)
                output.write(chunk)
            if total_size == 0 or not image_header_checked:
                raise AppError("unsupported_file_type", status_code=400)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    relative_path = target_path.relative_to(BACKEND_ROOT).as_posix()
    return SavedUpload(
        relative_path=relative_path,
        image_hash=hasher.hexdigest(),
        media_type=MEDIA_TYPES.get(target_path.suffix.lower(), "application/octet-stream"),
    )


def resolve_protected_image(relative_path: str | None) -> tuple[Path, str]:
    if not relative_path:
        raise AppError("image_not_found", status_code=404)

    settings = get_settings()
    candidate = (BACKEND_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(settings.upload_dir)
    except ValueError as exc:
        raise AppError("image_not_found", status_code=404) from exc

    if not candidate.is_file():
        raise AppError("image_not_found", status_code=404)

    return candidate, MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
