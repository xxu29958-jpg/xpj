"""Closed durable projection for operator-editable runtime settings."""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from app.services.secure_file import (
    hold_protected_file_for_read,
    hold_service_owned_projection_for_read,
    write_protected_file_no_replace,
    write_protected_file_replace,
)

_LEGACY_SCHEMA = "ticketbox-runtime-settings-v1"
_SCHEMA = "ticketbox-runtime-settings-v2"
_MAX_BYTES = 4096
_LEGACY_FIELDS = frozenset({"schema", "public_base_url", "budget_advisor_owner_confirmed"})
_FIELDS = frozenset({*_LEGACY_FIELDS, "recognition"})
_RECOGNITION_FIELDS = frozenset(
    {
        "ocr_provider",
        "ocr_auto_run",
        "ocr_fallback_provider",
        "ocr_min_confidence",
        "ocr_default_timezone",
        "local_llm_base_url",
        "local_llm_model",
        "local_llm_timeout_seconds",
        "local_llm_max_concurrent",
        "local_llm_queue_timeout_seconds",
        "debt_bill_provider",
    }
)


@dataclass(frozen=True)
class RecognitionSettingsProjection:
    """One atomic operator choice for the shared receipt/debt recognition engine."""

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


@dataclass(frozen=True)
class RuntimeSettingsProjection:
    public_base_url: str
    budget_advisor_owner_confirmed: bool
    recognition: RecognitionSettingsProjection | None = None


@dataclass(frozen=True)
class RuntimeSettingsMutation:
    field: Literal["public_base_url", "budget_advisor_owner_confirmed", "recognition"]
    value: str | bool | RecognitionSettingsProjection

    def __post_init__(self) -> None:
        valid = (
            (self.field == "public_base_url" and isinstance(self.value, str))
            or (self.field == "budget_advisor_owner_confirmed" and type(self.value) is bool)
            or (self.field == "recognition" and isinstance(self.value, RecognitionSettingsProjection))
        )
        if not valid:
            raise TypeError("runtime settings mutation type does not match its field")


_SETTINGS_LOCK = threading.Lock()


def _clean_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit or "\r" in value or "\n" in value:
        raise ValueError("runtime settings projection contains invalid text")
    return value


def _recognition_payload(projection: RecognitionSettingsProjection) -> dict[str, object]:
    provider = _clean_text(projection.ocr_provider, limit=32)
    fallback = _clean_text(projection.ocr_fallback_provider, limit=32)
    debt_provider = _clean_text(projection.debt_bill_provider, limit=32)
    if provider not in {"empty", "rapidocr", "local_llm"}:
        raise ValueError("runtime recognition provider is unsupported")
    if fallback not in {"empty", "rapidocr", "local_llm"}:
        raise ValueError("runtime recognition fallback provider is unsupported")
    if debt_provider not in {"empty", "local_llm"}:
        raise ValueError("runtime debt-bill provider is unsupported")
    if type(projection.ocr_auto_run) is not bool:
        raise ValueError("runtime recognition auto-run flag is invalid")
    if (
        not isinstance(projection.ocr_min_confidence, (int, float))
        or isinstance(projection.ocr_min_confidence, bool)
        or not math.isfinite(float(projection.ocr_min_confidence))
        or not 0 <= float(projection.ocr_min_confidence) <= 1
    ):
        raise ValueError("runtime recognition confidence threshold is invalid")
    if type(projection.local_llm_timeout_seconds) is not int or not 1 <= projection.local_llm_timeout_seconds <= 3600:
        raise ValueError("runtime local-model timeout is invalid")
    if type(projection.local_llm_max_concurrent) is not int or not 1 <= projection.local_llm_max_concurrent <= 64:
        raise ValueError("runtime local-model concurrency is invalid")
    if (
        not isinstance(projection.local_llm_queue_timeout_seconds, (int, float))
        or isinstance(projection.local_llm_queue_timeout_seconds, bool)
        or not math.isfinite(float(projection.local_llm_queue_timeout_seconds))
        or not 0 <= float(projection.local_llm_queue_timeout_seconds) <= 3600
    ):
        raise ValueError("runtime local-model queue timeout is invalid")
    return {
        "ocr_provider": provider,
        "ocr_auto_run": projection.ocr_auto_run,
        "ocr_fallback_provider": fallback,
        "ocr_min_confidence": float(projection.ocr_min_confidence),
        "ocr_default_timezone": _clean_text(projection.ocr_default_timezone, limit=64),
        "local_llm_base_url": _clean_text(projection.local_llm_base_url, limit=2048),
        "local_llm_model": _clean_text(projection.local_llm_model, limit=256),
        "local_llm_timeout_seconds": projection.local_llm_timeout_seconds,
        "local_llm_max_concurrent": projection.local_llm_max_concurrent,
        "local_llm_queue_timeout_seconds": float(projection.local_llm_queue_timeout_seconds),
        "debt_bill_provider": debt_provider,
    }


def _payload(projection: RuntimeSettingsProjection) -> dict[str, object]:
    if (
        type(projection.budget_advisor_owner_confirmed) is not bool
        or projection.recognition is not None
        and not isinstance(projection.recognition, RecognitionSettingsProjection)
    ):
        raise ValueError("runtime settings projection contains invalid values")
    return {
        "schema": _SCHEMA,
        "public_base_url": _clean_text(projection.public_base_url, limit=2048),
        "budget_advisor_owner_confirmed": projection.budget_advisor_owner_confirmed,
        "recognition": (_recognition_payload(projection.recognition) if projection.recognition is not None else None),
    }


def _encode(projection: RuntimeSettingsProjection) -> str:
    return (
        json.dumps(
            _payload(projection),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _encode_legacy(projection: RuntimeSettingsProjection) -> str:
    return (
        json.dumps(
            {
                "schema": _LEGACY_SCHEMA,
                "public_base_url": _clean_text(projection.public_base_url, limit=2048),
                "budget_advisor_owner_confirmed": projection.budget_advisor_owner_confirmed,
            },
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _decode_recognition(value: object) -> RecognitionSettingsProjection | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _RECOGNITION_FIELDS:
        raise ValueError("runtime recognition projection is not closed")
    return RecognitionSettingsProjection(**value)


def read_runtime_settings(
    path: Path,
    *,
    service_owned: bool,
) -> RuntimeSettingsProjection | None:
    target = Path(os.path.abspath(path))
    if not target.is_absolute() or not target.name:
        raise ValueError("runtime settings path must be an absolute file path")
    if not os.path.lexists(target):
        return None
    holder = hold_service_owned_projection_for_read if service_owned else hold_protected_file_for_read
    with holder(target) as protected:
        encoded = protected.read_bytes()
    if len(encoded) > _MAX_BYTES:
        raise ValueError("runtime settings projection exceeds its bounded size")
    try:
        value = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("runtime settings projection is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("runtime settings projection is not closed")
    schema = value.get("schema")
    if schema == _LEGACY_SCHEMA:
        if set(value) != _LEGACY_FIELDS:
            raise ValueError("runtime settings projection is not closed")
        projection = RuntimeSettingsProjection(
            public_base_url=value.get("public_base_url"),
            budget_advisor_owner_confirmed=value.get("budget_advisor_owner_confirmed"),
        )
        if encoded.decode("utf-8") != _encode_legacy(projection):
            raise ValueError("runtime settings projection is not canonical")
        return projection
    if schema != _SCHEMA:
        raise ValueError("runtime settings projection schema is unsupported")
    if set(value) != _FIELDS:
        raise ValueError("runtime settings projection is not closed")
    projection = RuntimeSettingsProjection(
        public_base_url=value.get("public_base_url"),
        budget_advisor_owner_confirmed=value.get("budget_advisor_owner_confirmed"),
        recognition=_decode_recognition(value.get("recognition")),
    )
    if encoded.decode("utf-8") != _encode(projection):
        raise ValueError("runtime settings projection is not canonical")
    return projection


def write_runtime_settings(
    path: Path,
    projection: RuntimeSettingsProjection,
    *,
    service_owned: bool,
) -> None:
    encoded = _encode(projection)
    if len(encoded.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("runtime settings projection exceeds its bounded size")
    target = Path(os.path.abspath(path))
    if not target.is_absolute() or not target.name:
        raise ValueError("runtime settings path must be an absolute file path")
    if not service_owned:
        target.parent.mkdir(parents=True, exist_ok=True)
    write_protected_file_replace(target, encoded, service_owned=service_owned)


def initialize_runtime_settings(
    path: Path,
    projection: RuntimeSettingsProjection,
    *,
    service_owned: bool,
) -> RuntimeSettingsProjection:
    """Create the first projection without replacing an existing owner value."""
    encoded = _encode(projection)
    target = Path(os.path.abspath(path))
    if not target.is_absolute() or not target.name:
        raise ValueError("runtime settings path must be an absolute file path")
    with _SETTINGS_LOCK:
        current = read_runtime_settings(target, service_owned=service_owned)
        if current is not None:
            return current
        try:
            write_protected_file_no_replace(
                target,
                encoded,
                service_owned=service_owned,
            )
        except FileExistsError as exc:
            current = read_runtime_settings(target, service_owned=service_owned)
            if current is None:
                raise OSError("runtime settings appeared without readable authority") from exc
            return current
        created = read_runtime_settings(target, service_owned=service_owned)
        if created != projection:
            raise OSError("initial runtime settings publication changed bytes")
        return created


def patch_runtime_settings(
    path: Path,
    *,
    defaults: RuntimeSettingsProjection,
    mutation: RuntimeSettingsMutation,
    service_owned: bool,
) -> RuntimeSettingsProjection:
    """Serialize the sole read-merge-publish transaction for this process."""
    _payload(defaults)
    with _SETTINGS_LOCK:
        current = read_runtime_settings(path, service_owned=service_owned) or defaults
        projection = replace(current, **{mutation.field: mutation.value})
        write_runtime_settings(path, projection, service_owned=service_owned)
        return projection
