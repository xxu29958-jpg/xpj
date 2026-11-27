from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.config import BACKEND_ROOT, get_settings
from app.errors import AppError
from app.schemas.image_source import ImageSourceContext
from app.services.image_source_evidence import image_source_evidence, original_image_context
from app.services.upload_path_resolver import (
    MEDIA_TYPES as MEDIA_TYPES,
)
from app.services.upload_path_resolver import (
    UPLOAD_REFERENCE_PREFIX as UPLOAD_REFERENCE_PREFIX,
)
from app.services.upload_path_resolver import (
    resolve_protected_image_in_root,
    resolve_upload_path_for_tenant_in_root,
    resolve_upload_reference_in_root,
    upload_reference_for_path_in_root,
)

# Pre-decode caps: PIL.verify() only checks magic bytes, so a tiny file
# can still decode to billions of pixels and bomb the thumbnail step.
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_DIMENSION = 12_000

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}
CONTENT_TYPE_EXTENSION = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heic",
}
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}


@dataclass(frozen=True)
class SavedUpload:
    relative_path: str
    image_hash: str
    image_perceptual_hash: str | None
    media_type: str
    size_bytes: int
    image_evidence: dict | None = None


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


def _register_pil_decoders(ext: str) -> None:
    if ext == "heic":
        from pillow_heif import register_heif_opener

        register_heif_opener()


def _image_size_within_cap(data: bytes) -> bool:
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        return False
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        return False
    return width * height <= MAX_IMAGE_PIXELS


def _is_decodable_image(ext: str, data: bytes) -> bool:
    try:
        from PIL import Image, UnidentifiedImageError

        _register_pil_decoders(ext)
        with Image.open(BytesIO(data)) as image:
            image.verify()
        return _image_size_within_cap(data)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return False


def _sanitize_image_bytes(ext: str, data: bytes) -> tuple[bytes, str]:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        _register_pil_decoders(ext)
        with Image.open(BytesIO(data)) as image:
            if not image.getexif() and not image.info:
                return data, "jpg" if ext == "jpeg" else ext
            image = ImageOps.exif_transpose(image)
            output = BytesIO()
            if ext in {"jpg", "jpeg"}:
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                image.save(output, format="JPEG", quality=95, optimize=True)
                return output.getvalue(), "jpg"
            if ext == "png":
                image.save(output, format="PNG", optimize=True)
                return output.getvalue(), "png"
            if ext == "webp":
                image.save(output, format="WEBP", quality=95, method=6)
                return output.getvalue(), "webp"
            if ext == "heic":
                image.save(output, format="HEIF", quality=95)
                return output.getvalue(), "heic"
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise AppError("unsupported_file_type", status_code=400) from exc
    raise AppError("unsupported_file_type", status_code=400)


def compute_image_perceptual_hash(data: bytes) -> str | None:
    """Return a 64-bit average hash for visual duplicate detection."""

    pixels: list[int] = []
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("L").resize((8, 8))
            pixel_source = (
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )
            pixels = [int(pixel) for pixel in pixel_source]
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        pixels = []
    return _average_hash_from_pixels(pixels) if pixels else None


def _average_hash_from_pixels(pixels: list[int]) -> str:
    avg = sum(int(pixel) for pixel in pixels) / len(pixels)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if int(pixel) >= avg else 0)
    return f"{bits:016x}"


async def read_upload_bytes(
    file: UploadFile,
    *,
    max_size_bytes: int | None = None,
) -> bytes:
    """Read and close one upload under the existing per-image byte limit."""
    limit = get_settings().max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    data = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            data.extend(chunk)
            if len(data) > limit:
                raise AppError("file_too_large", status_code=413)
    finally:
        await file.close()

    return bytes(data)


def _validated_upload_extension(
    data: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
    max_size_bytes: int | None = None,
) -> str:
    settings = get_settings()
    limit = settings.max_upload_size_bytes
    if max_size_bytes is not None:
        limit = max(0, min(limit, int(max_size_bytes)))
    if len(data) > limit:
        raise AppError("file_too_large", status_code=413)
    if not data:
        raise AppError("unsupported_file_type", status_code=400)

    header = data[:32]
    header_ext = _extension_from_header(header)
    metadata_ext = _extension_from_metadata(filename, content_type)
    ext = header_ext or metadata_ext
    if ext is None or not _looks_like_allowed_image(ext, header) or not _is_decodable_image(ext, data):
        raise AppError("unsupported_file_type", status_code=400)
    return ext


def save_upload_bytes(
    data: bytes,
    *,
    tenant_id: str,
    filename: str | None = None,
    content_type: str | None = None,
    max_size_bytes: int | None = None,
    before_publish: Callable[[str], None] | None = None,
    source_context: ImageSourceContext | None = None,
) -> SavedUpload:
    ext = _validated_upload_extension(
        data, filename=filename, content_type=content_type, max_size_bytes=max_size_bytes,
    )
    original = original_image_context(data)
    sanitized_data, ext = _sanitize_image_bytes(ext, data)
    evidence = image_source_evidence(original, sanitized_data, source_context)
    return _store_admitted_image(sanitized_data, tenant_id=tenant_id, ext=ext,
        before_publish=before_publish, image_evidence=evidence)


def save_original_replenishment_bytes(
    data: bytes,
    *,
    tenant_id: str,
    expected_sha256: str,
    filename: str | None = None,
    content_type: str | None = None,
    max_size_bytes: int | None = None,
    before_publish: Callable[[str], None] | None = None,
) -> SavedUpload:
    """Admit only the known original, then publish it under a new unique path.

    An already admitted JPEG must not be encoded again. Camera inputs whose raw
    digest differs may match after the ordinary upload privacy normalization.
    The caller owns authorization, receipts and publishing the new reference.
    """
    ext = _validated_upload_extension(
        data, filename=filename, content_type=content_type, max_size_bytes=max_size_bytes,
    )
    expected = (expected_sha256 or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise AppError("image_replenishment_mismatch", status_code=409)
    admitted = data
    if hashlib.sha256(admitted).hexdigest() != expected:
        admitted, ext = _sanitize_image_bytes(ext, data)
        if hashlib.sha256(admitted).hexdigest() != expected:
            raise AppError("image_replenishment_mismatch", status_code=409)
    return _store_admitted_image(admitted, tenant_id=tenant_id, ext=ext, before_publish=before_publish)


def _store_admitted_image(data: bytes, *, tenant_id: str, ext: str,
                          before_publish: Callable[[str], None] | None = None,
                          image_evidence: dict | None = None) -> SavedUpload:
    settings = get_settings()
    image_perceptual_hash = compute_image_perceptual_hash(data)

    now = datetime.now(UTC)
    target_dir = settings.upload_dir / tenant_id / now.strftime("%Y") / now.strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    require_upload_storage(bytes_to_write=len(data))

    filename = f"{secrets.token_hex(16)}.{ext}"
    target_path = target_dir / filename
    hasher = hashlib.sha256(data)
    relative_path = upload_reference_for_path(target_path)
    if before_publish is not None:
        before_publish(relative_path)

    # Claim a fresh path before entering compensation. A collision must never
    # overwrite or delete an earlier upload's original.
    output = target_path.open("xb")
    try:
        with output as stream:
            stream.write(data)
    except Exception:  # noqa: BLE001 - failed image sanitation must clean up the partial file.
        target_path.unlink(missing_ok=True)
        raise

    return SavedUpload(
        relative_path=relative_path,
        image_hash=hasher.hexdigest(),
        image_perceptual_hash=image_perceptual_hash,
        media_type=MEDIA_TYPES.get(target_path.suffix.lower(), "application/octet-stream"),
        # Report bytes actually written to disk (post-sanitization), not the raw
        # request body — the daily byte budget reconciles against storage cost.
        size_bytes=len(data),
        image_evidence=image_evidence,
    )


def require_upload_storage(*, bytes_to_write: int = 0) -> None:
    """Keep the configured original-store reserve before publication and admission."""
    settings = get_settings()
    if shutil.disk_usage(settings.upload_dir).free - bytes_to_write < settings.upload_min_free_bytes:
        raise AppError("upload_storage_full", status_code=507)


def upload_reference_for_path(path: Path) -> str:
    """Return the stable DB reference for a file under configured UPLOAD_DIR."""

    return upload_reference_for_path_in_root(
        path,
        upload_root=get_settings().upload_dir.resolve(),
        legacy_backend_root=BACKEND_ROOT,
    )


def _resolve_upload_reference(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    return resolve_upload_reference_in_root(
        relative_path,
        upload_root=get_settings().upload_dir.resolve(),
        legacy_backend_root=BACKEND_ROOT,
    )


def delete_relative_upload(relative_path: str | None) -> None:
    if not relative_path:
        return

    candidate = _resolve_upload_reference(relative_path)
    if candidate is None:
        return
    candidate.unlink(missing_ok=True)


def _tenant_upload_dir(tenant_id: str) -> Path:
    return (get_settings().upload_dir / tenant_id).resolve()


def resolve_upload_path_for_tenant(relative_path: str | None, tenant_id: str) -> Path | None:
    if not relative_path:
        return None
    return resolve_upload_path_for_tenant_in_root(
        relative_path,
        tenant_id,
        upload_root=get_settings().upload_dir.resolve(),
        legacy_backend_root=BACKEND_ROOT,
    )


def resolve_protected_image(relative_path: str | None, tenant_id: str) -> tuple[Path, str]:
    """Resolve a relative image path that the caller has already authorized.

    The caller verifies that the *expense row* belongs to ``tenant_id`` (the API
    path does this via the tenant-scoped ``get_expense``). This function is the
    compensating control: beyond filesystem safety it confines resolution to the
    caller's own tenant subtree, so passing a mismatched ``tenant_id`` yields
    ``image_not_found`` instead of leaking another tenant's file. It enforces:

    - reject empty / missing paths
    - reject absolute paths and Windows drive specs
    - reject ``..`` traversal that escapes the uploads root
    - require the resolved file to live inside the uploads root
    - require the file to live under ``uploads/<tenant>/`` (tenant isolation);
      unscoped legacy paths are the one exception, below

    Legacy v0.2 paths (``uploads/YYYY/MM/foo.png`` without a tenant prefix) are
    accepted only for the default legacy ledger as long as they remain inside
    the uploads root. New uploads are written under ``uploads/<tenant>/...`` but
    old files are not moved on startup (see docs/runbook/ROLLBACK.md).
    """

    if not relative_path:
        raise AppError("image_not_found", status_code=404)
    return resolve_protected_image_in_root(
        relative_path,
        tenant_id,
        upload_root=get_settings().upload_dir.resolve(),
        legacy_backend_root=BACKEND_ROOT,
    )
