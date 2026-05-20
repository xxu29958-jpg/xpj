from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.errors import PathTraversalError
from app.services.file_service import resolve_upload_path_for_tenant, upload_reference_for_path


def _tenant_upload_dir(tenant_id: str) -> Path:
    return (get_settings().upload_dir / tenant_id).resolve()


def _is_under_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def generate_thumbnail(
    relative_path: str | None,
    *,
    tenant_id: str,
    size: tuple[int, int] = (512, 512),
) -> str | None:
    settings = get_settings()
    if not settings.generate_thumbnail or not relative_path:
        return None

    source = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if source is None or not _is_under_path(source, settings.upload_dir):
        return None
    if not source.is_file():
        return None

    try:
        from PIL import Image

        if source.suffix.lower() == ".heic":
            from pillow_heif import register_heif_opener

            register_heif_opener()
    except ImportError:
        return None

    thumbnail_dir = source.parent / "thumbs"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = thumbnail_dir / f"{source.stem}.jpg"

    try:
        with Image.open(source) as image:
            image.thumbnail(size)
            rgb = image.convert("RGB")
            rgb.save(thumbnail_path, format="JPEG", quality=82, optimize=True)
    except Exception:
        # PIL raises many flavors here (UnidentifiedImageError, OSError,
        # ValueError, sometimes RecursionError on malformed input).
        # Thumbnail is optional — return None so the caller treats this
        # row as "no thumbnail" rather than failing the upload.
        return None

    try:
        return upload_reference_for_path(thumbnail_path)
    except PathTraversalError:
        # Resolved path escaped the upload root — refuse to surface it.
        return None


def resolve_protected_thumbnail(relative_path: str | None, tenant_id: str) -> tuple[Path, str] | None:
    if not relative_path:
        return None
    candidate = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if candidate is None:
        return None
    if not candidate.is_file():
        return None
    return candidate, "image/jpeg"
