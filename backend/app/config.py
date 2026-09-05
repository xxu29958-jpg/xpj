from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, DEFAULT_SUPPORTED_CURRENCY_CODES
from app.recognition_config import resolve_recognition_config

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _resolve_data_root(backend_root: Path) -> Path:
    """Writable-data root for files the running backend *creates* — settings
    projection (Owner Console) and uploaded originals.

    Defaults to ``backend_root`` so a normal source/dev run (and the whole test
    suite) is unchanged. The formal Windows service contract sets
    ``TICKETBOX_DATA_DIR`` to the machine-owned
    ``TicketboxRuntimeBinding/data-root/app`` junction. Its v2 marker and Volume
    GUID bind the junction to the installer-selected physical
    ``<DataRoot>/app``. This must not fall back to ``BACKEND_ROOT`` in a frozen
    build because that is PyInstaller's throwaway ``_MEIPASS`` extraction dir.
    Read-only program assets keep resolving against ``BACKEND_ROOT``.
    """
    raw = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    if not raw:
        return backend_root
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = backend_root / candidate
    return candidate.resolve()


DATA_ROOT = _resolve_data_root(BACKEND_ROOT)
load_dotenv(DATA_ROOT / ".env", encoding="utf-8-sig")
RUNTIME_SETTINGS_PATH = DATA_ROOT / "runtime-settings" / "runtime-settings.json"
_RUNTIME_SETTINGS_SERVICE_OWNED = bool(os.environ.get("TICKETBOX_INSTALLATION_ID", "").strip())


def runtime_settings_service_owned() -> bool:
    """Return whether the installer granted the service-owned projection contract."""

    return _RUNTIME_SETTINGS_SERVICE_OWNED


# Hosts considered loopback for local-development public URLs.
_LOOPBACK_OUTBOUND_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
OWNER_RECOVERY_CHANNELS: frozenset[str] = frozenset(
    {"development", "managed_host", "operator"},
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _choice_env(name: str, default: str, choices: frozenset[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


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
    background_task_max_active: int
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
    # ADR-0049 §D 债务账单解析 provider。默认 'empty'=不调模型、回落手填；'mock'=dev/test；
    # 'local_llm'=复用 LOCAL_LLM_* 同一台自托管视觉模型（无独立 LLM 配置）。
    debt_bill_provider: str
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
    recycle_bin_retention_days: int
    budget_advisor_live_min_interval_seconds: int
    budget_advisor_live_daily_call_limit: int
    tenants_json: str
    enable_http_bootstrap: bool
    http_bootstrap_secret: str
    enable_api_docs: bool
    allow_public_admin_api: bool
    owner_recovery_channel: str
    public_base_url: str
    cloudflare_access_required: bool
    cloudflare_access_team_domain: str
    cloudflare_access_aud: str
    # Public surface hardening (Batch 1).
    upload_link_default_daily_byte_budget: int
    upload_link_default_per_remote_interval_seconds: int
    upload_link_ttl_days: int
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
    # ADR-0049 §4 bill-split → Debt linkage rollout gate. ON by default (⑤b
    # activation, 2026-06-19): accepting a bill split now creates the receiver's
    # member Debt. Every rollout prerequisite is met — the §0.1 HARD BOUNDARY (a
    # bill-split member Debt is owned by the receiver's ledger with the sender as
    # cross-ledger creditor) was cleared by slice 5's account-scoped confirm/reject
    # (§5.2); the cross-ledger creditor discovery + confirm UX shipped across all
    # three surfaces (⑤c read views + ⑤b-2 Android confirm path); and pre-rollout
    # backfill self-heals historically-accepted splits on the next startup
    # (``reconcile_bill_split_debts_if_enabled``, P3b). Flipping it ON is
    # forward-only per §4; set ``DEBT_ROLLOUT_ENABLED=false`` to opt one install
    # out (does not remove already-created Debts).
    debt_rollout_enabled: bool

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


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
    re-reads ``os.environ`` and the closed runtime-settings projection.

    The Owner Console calls this only after atomically publishing that bounded
    projection. Tests and dev tooling also use it after changing their inputs.
    Callers needing unrelated per-request settings should use dependency
    injection instead of widening this contract.
    """
    get_settings.cache_clear()


# ADR-0045: the shipped placeholder token defaults. These are PUBLIC (committed
# in the repo), so they must never be used as a real secret — the CSRF signing key
# (``middleware/csrf.py``) rejects them and derives a real per-install secret instead.
PLACEHOLDER_UPLOAD_TOKEN = "replace-with-random-upload-token"
PLACEHOLDER_APP_TOKEN = "replace-with-random-app-token"
PLACEHOLDER_ADMIN_TOKEN = "replace-with-random-admin-token"
PLACEHOLDER_SECRETS = frozenset({PLACEHOLDER_UPLOAD_TOKEN, PLACEHOLDER_APP_TOKEN, PLACEHOLDER_ADMIN_TOKEN})

# PG-only (debt #4) localhost superuser fallback used ONLY when DATABASE_URL is
# unset. Connecting as the ``postgres`` superuser to run create_all / migrations
# is exactly the 2026-06-04 cut-over setup that left tables owned by ``postgres``
# and bricked startup for ~4 days (see docs/runbook/POSTGRES_MIGRATION.md §3 and
# the table-owner trap). Real deployments MUST set DATABASE_URL to the app role.
DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres@localhost:5432/ticketbox?require_auth=scram-sha-256"


class InstalledRuntimeSettingsError(RuntimeError):
    """The installed backend lacks its mandatory service-owned settings projection."""


def database_url_is_default_fallback() -> bool:
    """True when DATABASE_URL is unset and the superuser@localhost default is in use.

    Startup surfaces a WARN in this case (model-invariant hardening P1): running
    migrations as the default superuser is the table-owner-trap precondition.
    Read live (not via the lru_cached settings) so it reflects the env at call time.
    """
    return os.getenv("DATABASE_URL") is None


@lru_cache
def get_settings() -> Settings:
    from app.services.runtime_settings_store import read_runtime_settings

    runtime_settings = read_runtime_settings(
        RUNTIME_SETTINGS_PATH,
        service_owned=runtime_settings_service_owned(),
    )
    if runtime_settings_service_owned() and runtime_settings is None:
        raise InstalledRuntimeSettingsError("installed runtime settings projection is missing")
    recognition = resolve_recognition_config(runtime_settings.recognition if runtime_settings is not None else None)
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
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
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
        background_task_max_active=max(
            1,
            int(os.getenv("BACKGROUND_TASK_MAX_ACTIVE", "8")),
        ),
        ocr_provider=recognition.ocr_provider,
        ocr_auto_run=recognition.ocr_auto_run,
        ocr_fallback_provider=recognition.ocr_fallback_provider,
        ocr_min_confidence=recognition.ocr_min_confidence,
        ocr_default_timezone=recognition.ocr_default_timezone,
        local_llm_base_url=recognition.local_llm_base_url,
        local_llm_model=recognition.local_llm_model,
        local_llm_timeout_seconds=recognition.local_llm_timeout_seconds,
        # Default 2 deliberately allows a little OCR throughput overlap. A
        # single-GPU / single-stream local vision model (e.g. one quantized
        # model in LM Studio) should set LOCAL_LLM_MAX_CONCURRENT=1 to avoid
        # VRAM contention; the queue + LOCAL_LLM_QUEUE_TIMEOUT_SECONDS still
        # bound how long callers wait for a slot.
        local_llm_max_concurrent=recognition.local_llm_max_concurrent,
        local_llm_queue_timeout_seconds=recognition.local_llm_queue_timeout_seconds,
        # ADR-0049 §D: 债务账单解析 provider，默认 'empty'（未配视觉模型即回落手填）。
        # 选 'local_llm' 复用上面的 LOCAL_LLM_* 配置（同一台自托管视觉模型）。
        debt_bill_provider=recognition.debt_bill_provider,
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
        recycle_bin_retention_days=max(
            1,
            int(os.getenv("RECYCLE_BIN_RETENTION_DAYS", "30")),
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
        owner_recovery_channel=_choice_env(
            "TICKETBOX_OWNER_RECOVERY_CHANNEL",
            "development",
            OWNER_RECOVERY_CHANNELS,
        ),
        public_base_url=_resolve_public_base_url(
            runtime_settings.public_base_url if runtime_settings is not None else os.getenv("PUBLIC_BASE_URL")
        ),
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
        csv_import_max_bytes=int(os.getenv("CSV_IMPORT_MAX_BYTES", str(8 * 1024 * 1024))),
        csv_import_max_lines=int(os.getenv("CSV_IMPORT_MAX_LINES", "25000")),
        csv_import_max_cell_bytes=int(os.getenv("CSV_IMPORT_MAX_CELL_BYTES", "4096")),
        csv_import_apply_lease_minutes=max(1, int(os.getenv("CSV_IMPORT_APPLY_LEASE_MINUTES", "5"))),
        csv_import_row_apply_lease_minutes=max(1, int(os.getenv("CSV_IMPORT_ROW_APPLY_LEASE_MINUTES", "2"))),
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
        device_cleanup_daily_at=os.getenv("DEVICE_CLEANUP_DAILY_AT", "04:10").strip() or "04:10",
        device_cleanup_timezone=os.getenv("DEVICE_CLEANUP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        duplicate_phash_scan_limit=max(
            1,
            int(os.getenv("DUPLICATE_PHASH_SCAN_LIMIT", "500")),
        ),
        budget_advisor_owner_confirmed=(
            runtime_settings.budget_advisor_owner_confirmed
            if runtime_settings is not None
            else _bool_env("BUDGET_ADVISOR_OWNER_CONFIRMED", False)
        ),
        learning_cleanup_auto_enabled=_bool_env("LEARNING_CLEANUP_AUTO_ENABLED", False),
        learning_cleanup_daily_at=os.getenv("LEARNING_CLEANUP_DAILY_AT", "03:30").strip() or "03:30",
        learning_cleanup_timezone=os.getenv("LEARNING_CLEANUP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
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
        debt_rollout_enabled=_bool_env("DEBT_ROLLOUT_ENABLED", True),
    )
