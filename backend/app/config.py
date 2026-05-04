from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_sqlite_url(raw: str) -> str:
    prefix = "sqlite:///"
    if not raw.startswith(prefix):
        return raw

    db_path = Path(raw[len(prefix):])
    if not db_path.is_absolute():
        db_path = BACKEND_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return prefix + db_path.resolve().as_posix()


@dataclass(frozen=True)
class Settings:
    upload_token: str
    app_token: str
    admin_token: str
    database_url: str
    upload_dir: Path
    max_upload_size_mb: int
    delete_image_after_confirm: bool
    generate_thumbnail: bool
    delete_image_after_days: int
    ocr_provider: str

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
    if not upload_dir.is_absolute():
        upload_dir = BACKEND_ROOT / upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        upload_token=os.getenv("UPLOAD_TOKEN", "replace-with-random-upload-token"),
        app_token=os.getenv("APP_TOKEN", "replace-with-random-app-token"),
        admin_token=os.getenv("ADMIN_TOKEN", "replace-with-random-admin-token"),
        database_url=_resolve_sqlite_url(os.getenv("DATABASE_URL", "sqlite:///data/ticketbox.db")),
        upload_dir=upload_dir.resolve(),
        max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")),
        delete_image_after_confirm=_bool_env("DELETE_IMAGE_AFTER_CONFIRM", False),
        generate_thumbnail=_bool_env("GENERATE_THUMBNAIL", True),
        delete_image_after_days=int(os.getenv("DELETE_IMAGE_AFTER_DAYS", "0")),
        ocr_provider=os.getenv("OCR_PROVIDER", "empty").strip().lower(),
    )
