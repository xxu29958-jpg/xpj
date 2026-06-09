from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, DEFAULT_SUPPORTED_CURRENCY_CODES

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _resolve_data_root(backend_root: Path) -> Path:
    """Writable-data root for files the running backend *creates* — settings
    ``.env`` (Owner Console) and SQLite backups.

    Defaults to ``backend_root`` so a normal source/dev run (and the whole test
    suite) is unchanged. The frozen-EXE launcher (``packaging/launch.py``) sets
    ``TICKETBOX_DATA_DIR`` to a writable ``ticketbox-data/`` folder next to the
    EXE, because ``BACKEND_ROOT`` in a frozen build is PyInstaller's throwaway
    ``_MEIPASS`` extraction dir — anything written there is silently lost on
    restart. Read-only program assets (templates / static / migrations /
    alembic.ini) keep resolving against ``BACKEND_ROOT``.
    """
    raw = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    return Path(raw).resolve() if raw else backend_root


DATA_ROOT = _resolve_data_root(BACKEND_ROOT)
load_dotenv(DATA_ROOT / ".env", encoding="utf-8-sig")

# Hosts considered loopback for outbound calls from the backend (e.g. local
# vision LLM). Anything else makes the URL effectively "off" — see
# _resolve_local_llm_base_url. Owner can extend via env if they really need to
# tunnel a vision model from another host, but that's explicit, not implicit.
_LOOPBACK_OUTBOUND_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    background_task_orphan_grace_seconds: int
    ocr_provider: str
    ocr_auto_run: bool
    ocr_fallback_provider: str
    ocr_min_confidence: float
    ocr_default_timezone: str
    local_llm_base_url: str
    local_llm_model: str
    local_llm_timeout_seconds: int
    local_llm_max_concurrent: int
    local_llm_queue_timeout_seconds: float
    budget_advisor_provider: str
    budget_advisor_base_url: str
    budget_advisor_api_key: str
    budget_advisor_model: str
    budget_advisor_timeout_seconds: int
    budget_advisor_audit_retention_days: int
    budget_advisor_audit_cleanup_auto_enabled: bool
    budget_advisor_audit_cleanup_daily_at: str
    budget_advisor_audit_cleanup_timezone: str
    # ADR-0038 undo: opt-in periodic purge of soft-deleted rows past retention.
    soft_delete_purge_auto_enabled: bool
    budget_advisor_live_min_interval_seconds: int
    budget_advisor_live_daily_call_limit: int
    tenants_json: str
    enable_http_bootstrap: bool
    http_bootstrap_secret: str
    enable_api_docs: bool
    allow_public_admin_api: bool
    public_base_url: str
    cloudflare_access_required: bool
    cloudflare_access_team_domain: str
    cloudflare_access_aud: str
    # Public surface hardening (Batch 1).
    upload_link_default_daily_byte_budget: int
    upload_link_default_per_remote_interval_seconds: int
    upload_link_ttl_days: int
    upload_link_legacy_expiry_spread_days: int
    csv_import_max_bytes: int
    csv_import_max_lines: int
    csv_import_max_cell_bytes: int
    csv_import_apply_lease_minutes: int
    csv_import_row_apply_lease_minutes: int
    # Batch 2: app session token TTL. ``0`` keeps the legacy never-expires
    # behavior (web session tokens are still always TTL-capped). Anything
    # > 0 gives Android tokens a hard expiry; clients should silently
    # rotate via ``/api/auth/refresh`` once inside the soft window.
    app_token_ttl_days: int
    app_token_refresh_window_days: int
    app_token_rotation_grace_seconds: int
    device_cleanup_retention_days: int
    device_cleanup_auto_enabled: bool
    device_cleanup_daily_at: str
    device_cleanup_timezone: str
    # Performance budget (ENGINEERING_RULES §12 — no unbounded queries): the
    # perceptual-hash duplicate check can't filter Hamming distance in SQL, so
    # it scans candidates in Python. Cap how many of the most-recent
    # phash-bearing expenses it sweeps so a large ledger doesn't turn every
    # upload into a full-table scan.
    duplicate_phash_scan_limit: int
    # Batch 2: AI budget advisor live calls require explicit opt-in.
    # ``empty`` / ``mock`` providers do not need this flag.
    budget_advisor_owner_confirmed: bool
    # v1.2 ops: scheduled learning-table cleanup. Disabled by default
    # so existing deployments don't suddenly grow a background thread;
    # enable via env when ready to retire manual cleanup.
    learning_cleanup_auto_enabled: bool
    learning_cleanup_daily_at: str
    learning_cleanup_timezone: str
    fx_home_currency_code: str
    fx_supported_currency_codes: str
    fx_rate_auto_sync_enabled: bool
    fx_rate_sync_times: str
    fx_rate_sync_timezone: str
    fx_rate_source: str
    fx_rate_ecb_url: str
    fx_rate_frankfurter_url: str

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
    """Validate the public base URL the Cloudflare Tunnel (or other reverse
    proxy) hands out for /u/<upload_key>. ``http://`` is only accepted when
    the host is loopback (local dev); over the open internet UploadLink URLs
    must be ``https://`` because the upload_key in the path is a credential.
    Anything else is dropped silently (settings stay empty, Owner Console
    falls back to its "no public URL" UI).
    """

    if not raw:
        return ""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.username or parsed.password:
        return ""
    try:
        _ = parsed.port
    except ValueError:
        return ""
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in _LOOPBACK_OUTBOUND_HOSTS:
        return ""
    return value


def _resolve_cloudflare_access_team_domain(raw: str | None) -> str:
    if not raw:
        return ""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return ""
    if parsed.username or parsed.password:
        return ""
    try:
        if parsed.port is not None:
            return ""
    except ValueError:
        return ""
    if parsed.path or parsed.query or parsed.fragment:
        return ""
    host = (parsed.hostname or "").lower()
    if not host.endswith(".cloudflareaccess.com"):
        return ""
    return f"https://{host}"


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


# ADR-0045: the shipped placeholder token defaults. These are PUBLIC (committed
# in the repo), so they must never be used as a real secret — the CSRF signing key
# (``middleware/csrf.py``) rejects them and derives a real per-install secret instead.
PLACEHOLDER_UPLOAD_TOKEN = "replace-with-random-upload-token"
PLACEHOLDER_APP_TOKEN = "replace-with-random-app-token"
PLACEHOLDER_ADMIN_TOKEN = "replace-with-random-admin-token"
PLACEHOLDER_SECRETS = frozenset({PLACEHOLDER_UPLOAD_TOKEN, PLACEHOLDER_APP_TOKEN, PLACEHOLDER_ADMIN_TOKEN})


@lru_cache
def get_settings() -> Settings:
    upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
    if not upload_dir.is_absolute():
        upload_dir = DATA_ROOT / upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        upload_token=os.getenv("UPLOAD_TOKEN", PLACEHOLDER_UPLOAD_TOKEN),
        app_token=os.getenv("APP_TOKEN", PLACEHOLDER_APP_TOKEN),
        admin_token=os.getenv("ADMIN_TOKEN", PLACEHOLDER_ADMIN_TOKEN),
        # PG-only (debt #4): no SQLite fallback. Real deployments set
        # DATABASE_URL in .env (see docs/runbook/POSTGRES_MIGRATION.md); this
        # localhost default only serves a bare local run with no .env.
        database_url=os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/ticketbox"),
        upload_dir=upload_dir.resolve(),
        max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")),
        delete_image_after_confirm=_bool_env("DELETE_IMAGE_AFTER_CONFIRM", False),
        generate_thumbnail=_bool_env("GENERATE_THUMBNAIL", True),
        delete_image_after_days=int(os.getenv("DELETE_IMAGE_AFTER_DAYS", "0")),
        delete_rejected_after_days=int(os.getenv("DELETE_REJECTED_AFTER_DAYS", "0")),
        orphan_upload_grace_hours=int(os.getenv("ORPHAN_UPLOAD_GRACE_HOURS", "24")),
        background_task_orphan_grace_seconds=max(
            0,
            int(os.getenv("BACKGROUND_TASK_ORPHAN_GRACE_SECONDS", "0")),
        ),
        ocr_provider=os.getenv("OCR_PROVIDER", "empty").strip().lower(),
        ocr_auto_run=_bool_env("OCR_AUTO_RUN", False),
        ocr_fallback_provider=os.getenv("OCR_FALLBACK_PROVIDER", "empty").strip().lower(),
        ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "0.65")),
        ocr_default_timezone=os.getenv("OCR_DEFAULT_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        local_llm_base_url=_resolve_local_llm_base_url(os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1")),
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_llm_timeout_seconds=int(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "60")),
        # Default 2 deliberately allows a little OCR throughput overlap. A
        # single-GPU / single-stream local vision model (e.g. one quantized
        # model in LM Studio) should set LOCAL_LLM_MAX_CONCURRENT=1 to avoid
        # VRAM contention; the queue + LOCAL_LLM_QUEUE_TIMEOUT_SECONDS still
        # bound how long callers wait for a slot.
        local_llm_max_concurrent=max(1, int(os.getenv("LOCAL_LLM_MAX_CONCURRENT", "2"))),
        local_llm_queue_timeout_seconds=max(0.0, float(os.getenv("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS", "5"))),
        # ADR-0036: v1.1 AI budget advisor provider. Default 'empty' = no AI
        # call, local rules only. 'openai_compat' covers ollama / vLLM /
        # llama.cpp / LM Studio locally + OpenAI / DeepSeek / SiliconFlow /
        # Together / Groq in the cloud — same base_url + api_key + model
        # triple. No endpoint is preset; selecting openai_compat without
        # BUDGET_ADVISOR_BASE_URL + MODEL raises at provider lookup.
        budget_advisor_provider=os.getenv("BUDGET_ADVISOR_PROVIDER", "empty").strip().lower(),
        budget_advisor_base_url=os.getenv("BUDGET_ADVISOR_BASE_URL", "").strip(),
        budget_advisor_api_key=os.getenv("BUDGET_ADVISOR_API_KEY", ""),
        budget_advisor_model=os.getenv("BUDGET_ADVISOR_MODEL", "").strip(),
        budget_advisor_timeout_seconds=int(os.getenv("BUDGET_ADVISOR_TIMEOUT_SECONDS", "60")),
        budget_advisor_audit_retention_days=int(os.getenv("BUDGET_ADVISOR_AUDIT_RETENTION_DAYS", "180")),
        budget_advisor_audit_cleanup_auto_enabled=_bool_env(
            "BUDGET_ADVISOR_AUDIT_CLEANUP_AUTO_ENABLED",
            False,
        ),
        budget_advisor_audit_cleanup_daily_at=os.getenv(
            "BUDGET_ADVISOR_AUDIT_CLEANUP_DAILY_AT",
            "03:45",
        ).strip()
        or "03:45",
        budget_advisor_audit_cleanup_timezone=os.getenv(
            "BUDGET_ADVISOR_AUDIT_CLEANUP_TIMEZONE",
            "Asia/Shanghai",
        ).strip()
        or "Asia/Shanghai",
        soft_delete_purge_auto_enabled=_bool_env(
            "SOFT_DELETE_PURGE_AUTO_ENABLED",
            False,
        ),
        budget_advisor_live_min_interval_seconds=max(
            0,
            int(os.getenv("BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS", "60")),
        ),
        budget_advisor_live_daily_call_limit=max(
            0,
            int(os.getenv("BUDGET_ADVISOR_LIVE_DAILY_CALL_LIMIT", "50")),
        ),
        tenants_json=os.getenv("TENANTS_JSON", "").strip(),
        enable_http_bootstrap=_bool_env("ENABLE_HTTP_BOOTSTRAP", False),
        http_bootstrap_secret=os.getenv("HTTP_BOOTSTRAP_SECRET", "").strip(),
        enable_api_docs=_bool_env("ENABLE_API_DOCS", False),
        allow_public_admin_api=_bool_env("ALLOW_PUBLIC_ADMIN_API", False),
        public_base_url=_resolve_public_base_url(os.getenv("PUBLIC_BASE_URL")),
        cloudflare_access_required=_bool_env("CLOUDFLARE_ACCESS_REQUIRED", False),
        cloudflare_access_team_domain=_resolve_cloudflare_access_team_domain(
            os.getenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN")
        ),
        cloudflare_access_aud=os.getenv("CLOUDFLARE_ACCESS_AUD", "").strip(),
        # Batch 1: default daily budget 200 MiB / link, default 2-second
        # gap per remote_key. 0 = unlimited (kept for tests / loopback).
        upload_link_default_daily_byte_budget=int(
            os.getenv("UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", str(200 * 1024 * 1024))
        ),
        upload_link_default_per_remote_interval_seconds=int(
            os.getenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "2")
        ),
        upload_link_ttl_days=max(1, int(os.getenv("UPLOAD_LINK_TTL_DAYS", "90"))),
        upload_link_legacy_expiry_spread_days=max(
            1,
            int(os.getenv("UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS", "30")),
        ),
        csv_import_max_bytes=int(os.getenv("CSV_IMPORT_MAX_BYTES", str(8 * 1024 * 1024))),
        csv_import_max_lines=int(os.getenv("CSV_IMPORT_MAX_LINES", "25000")),
        csv_import_max_cell_bytes=int(os.getenv("CSV_IMPORT_MAX_CELL_BYTES", "4096")),
        csv_import_apply_lease_minutes=max(
            1, int(os.getenv("CSV_IMPORT_APPLY_LEASE_MINUTES", "5"))
        ),
        csv_import_row_apply_lease_minutes=max(
            1, int(os.getenv("CSV_IMPORT_ROW_APPLY_LEASE_MINUTES", "2"))
        ),
        app_token_ttl_days=int(os.getenv("APP_TOKEN_TTL_DAYS", "90")),
        app_token_refresh_window_days=int(os.getenv("APP_TOKEN_REFRESH_WINDOW_DAYS", "14")),
        app_token_rotation_grace_seconds=max(
            0,
            int(os.getenv("APP_TOKEN_ROTATION_GRACE_SECONDS", "60")),
        ),
        device_cleanup_retention_days=max(
            0,
            int(os.getenv("DEVICE_CLEANUP_RETENTION_DAYS", "180")),
        ),
        device_cleanup_auto_enabled=_bool_env("DEVICE_CLEANUP_AUTO_ENABLED", False),
        device_cleanup_daily_at=os.getenv(
            "DEVICE_CLEANUP_DAILY_AT", "04:10"
        ).strip() or "04:10",
        device_cleanup_timezone=os.getenv(
            "DEVICE_CLEANUP_TIMEZONE", "Asia/Shanghai"
        ).strip() or "Asia/Shanghai",
        duplicate_phash_scan_limit=max(
            1,
            int(os.getenv("DUPLICATE_PHASH_SCAN_LIMIT", "500")),
        ),
        budget_advisor_owner_confirmed=_bool_env("BUDGET_ADVISOR_OWNER_CONFIRMED", False),
        learning_cleanup_auto_enabled=_bool_env(
            "LEARNING_CLEANUP_AUTO_ENABLED", False
        ),
        learning_cleanup_daily_at=os.getenv(
            "LEARNING_CLEANUP_DAILY_AT", "03:30"
        ).strip() or "03:30",
        learning_cleanup_timezone=os.getenv(
            "LEARNING_CLEANUP_TIMEZONE", "Asia/Shanghai"
        ).strip() or "Asia/Shanghai",
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
        fx_rate_source=(os.getenv("FX_RATE_SOURCE", "frankfurter").strip().lower() or "frankfurter"),
        fx_rate_ecb_url=(
            os.getenv(
                "FX_RATE_ECB_URL",
                "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            ).strip()
            or "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
        ),
        fx_rate_frankfurter_url=(
            os.getenv(
                "FX_RATE_FRANKFURTER_URL",
                "https://api.frankfurter.dev/v1/latest?base=EUR",
            ).strip()
            or "https://api.frankfurter.dev/v1/latest?base=EUR"
        ),
    )
