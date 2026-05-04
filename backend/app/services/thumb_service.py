from __future__ import annotations

from pathlib import Path

from app.config import BACKEND_ROOT, get_settings


def generate_thumbnail(relative_path: str | None, *, size: tuple[int, int] = (512, 512)) -> str | None:
    settings = get_settings()
    if not settings.generate_thumbnail or not relative_path:
        return None

    source = (BACKEND_ROOT / relative_path).resolve()
    try:
        source.relative_to(settings.upload_dir)
    except ValueError:
        return None
    if not source.is_file() or source.suffix.lower() == ".heic":
        return None

    try:
        from PIL import Image
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
        return None

    return thumbnail_path.relative_to(BACKEND_ROOT).as_posix()


def resolve_protected_thumbnail(relative_path: str | None) -> tuple[Path, str] | None:
    if not relative_path:
        return None
    candidate = (BACKEND_ROOT / relative_path).resolve()
    settings = get_settings()
    try:
        candidate.relative_to(settings.upload_dir)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate, "image/jpeg"
