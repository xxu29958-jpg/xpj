"""Settings-free upload reference resolution and tenant confinement."""

from __future__ import annotations

from pathlib import Path

from app.errors import AppError, PathTraversalError
from app.tenant_contract import DEFAULT_TENANT_ID

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
}
UPLOAD_REFERENCE_PREFIX = "uploads"


def _is_under_path(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


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


def _is_legacy_unscoped_upload(candidate: Path, upload_root: Path, tenant_id: str) -> bool:
    """Allow pre-v0.3 paths shaped as uploads/YYYY/MM/file for the default ledger only."""
    if tenant_id != DEFAULT_TENANT_ID:
        return False
    try:
        parts = candidate.relative_to(upload_root).parts
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


def upload_reference_for_path_in_root(
    path: Path,
    *,
    upload_root: Path,
    legacy_backend_root: Path | None = None,
) -> str:
    """Return the stable DB reference for a file under an explicit upload root."""
    resolved = path.resolve()
    if legacy_backend_root is not None:
        try:
            return resolved.relative_to(legacy_backend_root).as_posix()
        except ValueError:
            pass
    try:
        relative_to_upload_root = resolved.relative_to(upload_root.resolve())
    except ValueError as exc:
        raise PathTraversalError("Upload file escaped configured upload directory") from exc
    return f"{UPLOAD_REFERENCE_PREFIX}/{relative_to_upload_root.as_posix()}"


def resolve_upload_reference_in_root(
    relative_path: str | None,
    *,
    upload_root: Path,
    legacy_backend_root: Path | None = None,
) -> Path | None:
    """Resolve a relative upload reference strictly under ``upload_root``."""
    parts = _normalized_upload_parts(relative_path)
    if not parts:
        return None

    resolved_upload_root = upload_root.resolve()
    legacy_candidate: Path | None = None
    if legacy_backend_root is not None:
        legacy_candidate = (legacy_backend_root / Path(*parts)).resolve()
        if _is_under_path(legacy_candidate, resolved_upload_root):
            return legacy_candidate
    if parts[0] == UPLOAD_REFERENCE_PREFIX:
        candidate = (resolved_upload_root / Path(*parts[1:])).resolve()
    elif legacy_candidate is not None:
        candidate = legacy_candidate
    else:
        return None
    if not _is_under_path(candidate, resolved_upload_root):
        return None
    return candidate


def resolve_upload_path_for_tenant_in_root(
    relative_path: str | None,
    tenant_id: str,
    *,
    upload_root: Path,
    legacy_backend_root: Path | None = None,
) -> Path | None:
    """Confine a relative upload path to ``upload_root/<tenant_id>`` (or legacy default ledger)."""
    resolved_upload_root = upload_root.resolve()
    candidate = resolve_upload_reference_in_root(
        relative_path,
        upload_root=resolved_upload_root,
        legacy_backend_root=legacy_backend_root,
    )
    if candidate is None:
        return None
    tenant_dir = (resolved_upload_root / tenant_id).resolve()
    if not _is_under_path(candidate, tenant_dir) and not _is_legacy_unscoped_upload(
        candidate, resolved_upload_root, tenant_id
    ):
        return None
    return candidate


def resolve_protected_image_in_root(
    relative_path: str | None,
    tenant_id: str,
    *,
    upload_root: Path,
    legacy_backend_root: Path | None = None,
) -> tuple[Path, str]:
    """Resolve an existing tenant-confined image file under an explicit upload root."""
    if not relative_path:
        raise AppError("image_not_found", status_code=404)
    candidate = resolve_upload_path_for_tenant_in_root(
        relative_path,
        tenant_id,
        upload_root=upload_root,
        legacy_backend_root=legacy_backend_root,
    )
    if candidate is None or not candidate.is_file():
        raise AppError("image_not_found", status_code=404)
    return candidate, MEDIA_TYPES.get(candidate.suffix.lower(), "application/octet-stream")


__all__ = [
    "MEDIA_TYPES",
    "UPLOAD_REFERENCE_PREFIX",
    "resolve_protected_image_in_root",
    "resolve_upload_path_for_tenant_in_root",
    "resolve_upload_reference_in_root",
    "upload_reference_for_path_in_root",
]
