from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.services.runtime_settings_store import RecognitionSettingsProjection

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class RecognitionConfig:
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
    debt_bill_provider: str


def resolve_local_llm_base_url(raw: str | None) -> str:
    """Return a loopback HTTP(S) model endpoint, or disable the provider."""

    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return ""
    return value


def resolve_recognition_config(projection: RecognitionSettingsProjection | None) -> RecognitionConfig:
    if projection is not None:
        return RecognitionConfig(**asdict(projection))

    return RecognitionConfig(
        ocr_provider=os.getenv("OCR_PROVIDER", "empty").strip().lower(),
        ocr_auto_run=_bool_env("OCR_AUTO_RUN", False),
        ocr_fallback_provider=os.getenv("OCR_FALLBACK_PROVIDER", "empty").strip().lower(),
        ocr_min_confidence=float(os.getenv("OCR_MIN_CONFIDENCE", "0.65")),
        ocr_default_timezone=os.getenv("OCR_DEFAULT_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
        local_llm_base_url=resolve_local_llm_base_url(os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1")),
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_llm_timeout_seconds=int(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "60")),
        local_llm_max_concurrent=max(1, int(os.getenv("LOCAL_LLM_MAX_CONCURRENT", "2"))),
        local_llm_queue_timeout_seconds=max(0.0, float(os.getenv("LOCAL_LLM_QUEUE_TIMEOUT_SECONDS", "5"))),
        debt_bill_provider=os.getenv("DEBT_BILL_PROVIDER", "empty").strip().lower(),
    )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}
