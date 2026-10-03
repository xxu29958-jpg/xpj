"""Closed persisted choices for the existing advisor and exchange-rate services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class AdvisorSettingsProjection:
    provider: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: int
    min_interval_seconds: int
    daily_call_limit: int


@dataclass(frozen=True)
class FxSettingsProjection:
    auto_enabled: bool
    source: str
    sync_times: str
    timezone: str


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and len(value.encode("utf-8")) <= limit and not any(
        ord(char) < 32 or ord(char) == 127 for char in value
    )


def advisor_payload(value: AdvisorSettingsProjection) -> dict[str, object]:
    if (
        value.provider not in {"empty", "openai_compat"}
        or not _text(value.base_url, 2048)
        or not _text(value.api_key, 4096)
        or not _text(value.model, 256)
        or type(value.timeout_seconds) is not int or not 5 <= value.timeout_seconds <= 300
        or type(value.min_interval_seconds) is not int or not 0 <= value.min_interval_seconds <= 86400
        or type(value.daily_call_limit) is not int or not 0 <= value.daily_call_limit <= 10000
    ):
        raise ValueError("runtime advisor settings are invalid")
    return asdict(value)


def fx_payload(value: FxSettingsProjection) -> dict[str, object]:
    if (
        type(value.auto_enabled) is not bool
        or value.source not in {"ecb", "frankfurter"}
        or not _text(value.sync_times, 128)
        or not _text(value.timezone, 64)
    ):
        raise ValueError("runtime exchange-rate settings are invalid")
    return asdict(value)
