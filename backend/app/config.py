from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, DEFAULT_SUPPORTED_CURRENCY_CODES


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env", encoding="utf-8-sig")

# Hosts considered loopback for outbound calls from the backend (e.g. local
# vision LLM). Anything else makes the URL effectively "off" — see
# _resolve_local_llm_base_url. Owner can extend via env if they really need to
# tunnel a vision model from another host, but that's explicit, not implicit.
_LOOPBACK_OUTBOUND_HOSTS: frozenset[str] = frozenset(
    {"127.0.0.1", "::1", "localhost"}
)


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
    delete_rejected_after_days: int
    orphan_upload_grace_hours: int
    ocr_provider: str
    ocr_auto_run: bool
    ocr_fallback_provider: str
    ocr_min_confidence: float
    ocr_default_timezone: str
    local_llm_base_url: str
    local_llm_model: str
    local_llm_timeout_seconds: int
    tenants_json: str
    enable_http_bootstrap: bool
    http_bootstrap_secret: str
    enable_api_docs: bool
    allow_public_admin_api: bool
    public_base_url: str
    fx_home_currency_code: str
    fx_supported_currency_codes: str
    fx_rate_auto_sync_enabled: bool
    fx_rate_sync_times: str
    fx_rate_sync_timezone: str
    fx_rate_ecb_url: str

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


def _resolve_local_llm_base_url(raw: str | None) -> str:
    """Reduce ``LOCAL_LLM_BASE_URL`` to a loopback HTTP(S) origin or empty.

    Returning empty disables the local LLM OCR provider — the OCR layer surfaces
    a clear error when something tries to use it. Non-loopback hosts here would
    let the owner accidentally ship uploaded receipts (base64) to a remote
    server via env misconfiguration, so we fail-closed.
    """

    if not raw:
        return ""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_OUTBOUND_HOSTS:
        return ""
    return value


def _resolve_public_base_url(raw: str | None) -> str:
    if not raw:
        return ""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    if not (value.startswith("http://") or value.startswith("https://")):
        return ""
    return value


def reset_settings_cache() -> None:
    """Drop the cached ``Settings`` snapshot so the next ``get_settings()``
    re-reads ``os.environ``.

    Production never calls this — settings are immutable for the process
    lifetime. Tests and dev tooling that mutate ``os.environ`` between
    runs use it explicitly. This is the *only* documented escape hatch
    out of the lru_cache; callers that need a per-request settings view
    should refactor to dependency injection instead of widening this
    contract.
    """
    get_settings.cache_clear()


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
        delete_rejected_after_days=int(os.getenv("DELETE_REJECTED_AFTER_DAYS", "0")),
        orphan_upload_grace_hours=int(os.getenv("ORPHAN_UPLOAD_GRACE_HOURS", "24")),
        ocr_provider=os.getenv("OCR_PROVIDER", "empty").strip().lower(),
        ocr_auto_run=_bool_env("OCR_AUTO_RUN", False),
        ocr_fallback_provider=os.getenv("OCR_FALLBACK_PROVIDER", "empty").strip().lower(),
        ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "0.65")),
        ocr_default_timezone=os.getenv("OCR_DEFAULT_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        local_llm_base_url=_resolve_local_llm_base_url(os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1")),
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_llm_timeout_seconds=int(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "60")),
        tenants_json=os.getenv("TENANTS_JSON", "").strip(),
        enable_http_bootstrap=_bool_env("ENABLE_HTTP_BOOTSTRAP", False),
        http_bootstrap_secret=os.getenv("HTTP_BOOTSTRAP_SECRET", "").strip(),
        enable_api_docs=_bool_env("ENABLE_API_DOCS", False),
        allow_public_admin_api=_bool_env("ALLOW_PUBLIC_ADMIN_API", False),
        public_base_url=_resolve_public_base_url(os.getenv("PUBLIC_BASE_URL")),
        fx_home_currency_code=os.getenv("FX_HOME_CURRENCY_CODE", DEFAULT_HOME_CURRENCY_CODE).strip().upper()
        or DEFAULT_HOME_CURRENCY_CODE,
        fx_supported_currency_codes=os.getenv(
            "FX_SUPPORTED_CURRENCY_CODES",
            ",".join(sorted(DEFAULT_SUPPORTED_CURRENCY_CODES)),
        ).strip()
        or ",".join(sorted(DEFAULT_SUPPORTED_CURRENCY_CODES)),
        fx_rate_auto_sync_enabled=_bool_env("FX_RATE_AUTO_SYNC_ENABLED", True),
        fx_rate_sync_times=os.getenv("FX_RATE_SYNC_TIMES", "09:10,23:10").strip() or "09:10,23:10",
        fx_rate_sync_timezone=os.getenv("FX_RATE_SYNC_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        fx_rate_ecb_url=(
            os.getenv(
                "FX_RATE_ECB_URL",
                "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            ).strip()
            or "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
        ),
    )
