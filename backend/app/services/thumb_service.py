from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.errors import PathTraversalError
from app.services.file_service import resolve_upload_path_for_tenant, upload_reference_for_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StagedThumbnail:
    """One unpublished thumbnail whose unique file is owned by its caller."""

    source_reference: str
    staging_path: Path
    final_path: Path
    final_reference: str


def _discard_attempt_path(path: Path, *, event: str) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # Attempt-unique files are not independent product truth. Preserve the
        # caller's result/error and let grace-based orphan GC retry cleanup.
        logger.warning(
            "event=%s error_type=%s",
            event,
            type(exc).__name__,
            extra={
                "event": event,
                "error_type": type(exc).__name__,
            },
        )


def _tenant_upload_dir(tenant_id: str) -> Path:
    return (get_settings().upload_dir / tenant_id).resolve()


def _is_under_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _thumbnail_source(relative_path: str | None, tenant_id: str) -> Path | None:
    settings = get_settings()
    if not settings.generate_thumbnail or not relative_path:
        return None
    source = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if source is None or not _is_under_path(source, settings.upload_dir):
        return None
    return source if source.is_file() else None


def _render_thumbnail(source: Path, target: Path, size: tuple[int, int]) -> bool:
    try:
        from PIL import Image

        if source.suffix.lower() == ".heic":
            from pillow_heif import register_heif_opener

            register_heif_opener()
    except ImportError:
        return False

    try:
        with Image.open(source) as image:
            image.thumbnail(size)
            rgb = image.convert("RGB")
            rgb.save(target, format="JPEG", quality=82, optimize=True)
    except (Image.DecompressionBombError, OSError, RecursionError, ValueError):
        return False
    return True


def stage_thumbnail(
    relative_path: str | None,
    *,
    tenant_id: str,
    size: tuple[int, int] = (512, 512),
) -> StagedThumbnail | None:
    """Render a unique thumbnail without publishing its attempt final."""
    source = _thumbnail_source(relative_path, tenant_id)
    if source is None:
        return None

    thumbnail_dir = source.parent / "thumbs"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    attempt_id = uuid4().hex
    final_path = thumbnail_dir / f"{source.stem}.{attempt_id}.jpg"
    try:
        final_reference = upload_reference_for_path(final_path)
    except PathTraversalError:
        return None
    with tempfile.NamedTemporaryFile(
        dir=thumbnail_dir,
        prefix=f".{source.stem}.{attempt_id}.",
        suffix=".staging.jpg",
        delete=False,
    ) as temporary:
        staging_path = Path(temporary.name)

    staged: StagedThumbnail | None = None
    try:
        if not _render_thumbnail(source, staging_path, size):
            return None
        staged = StagedThumbnail(
            source_reference=relative_path,
            staging_path=staging_path,
            final_path=final_path,
            final_reference=final_reference,
        )
        return staged
    finally:
        if staged is None:
            _discard_attempt_path(
                staging_path,
                event="thumbnail_staging_cleanup_failed",
            )


def publish_staged_thumbnail_attempt(staged: StagedThumbnail) -> str:
    """Atomically publish one attempt to its own unique final path."""
    staged.staging_path.replace(staged.final_path)
    return staged.final_reference


def discard_staged_thumbnail(staged: StagedThumbnail | None) -> None:
    if staged is not None:
        _discard_attempt_path(
            staged.staging_path,
            event="thumbnail_staging_cleanup_failed",
        )


def discard_published_thumbnail_attempt(staged: StagedThumbnail | None) -> None:
    if staged is not None:
        _discard_attempt_path(
            staged.final_path,
            event="thumbnail_attempt_cleanup_failed",
        )


def resolve_protected_thumbnail(relative_path: str | None, tenant_id: str) -> tuple[Path, str] | None:
    if not relative_path:
        return None
    candidate = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if candidate is None:
        return None
    if not candidate.is_file():
        return None
    return candidate, "image/jpeg"
