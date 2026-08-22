"""Closed durable projection for operator-editable runtime settings."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.services.secure_file import (
    hold_protected_file_for_read,
    hold_service_owned_projection_for_read,
    write_protected_file_replace,
)

_SCHEMA = "ticketbox-runtime-settings-v1"
_MAX_BYTES = 4096
_FIELDS = frozenset({"schema", "public_base_url", "budget_advisor_owner_confirmed"})


@dataclass(frozen=True)
class RuntimeSettingsProjection:
    public_base_url: str
    budget_advisor_owner_confirmed: bool


@dataclass(frozen=True)
class RuntimeSettingsMutation:
    field: Literal["public_base_url", "budget_advisor_owner_confirmed"]
    value: str | bool

    def __post_init__(self) -> None:
        valid = (self.field == "public_base_url" and isinstance(self.value, str)) or (
            self.field == "budget_advisor_owner_confirmed" and type(self.value) is bool
        )
        if not valid:
            raise TypeError("runtime settings mutation type does not match its field")


_SETTINGS_LOCK = threading.Lock()


def _payload(projection: RuntimeSettingsProjection) -> dict[str, object]:
    if (
        not isinstance(projection.public_base_url, str)
        or len(projection.public_base_url.encode("utf-8")) > 2048
        or "\r" in projection.public_base_url
        or "\n" in projection.public_base_url
        or not isinstance(projection.budget_advisor_owner_confirmed, bool)
    ):
        raise ValueError("runtime settings projection contains invalid values")
    return {
        "schema": _SCHEMA,
        "public_base_url": projection.public_base_url,
        "budget_advisor_owner_confirmed": projection.budget_advisor_owner_confirmed,
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
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("runtime settings projection is not closed")
    if value.get("schema") != _SCHEMA:
        raise ValueError("runtime settings projection schema is unsupported")
    projection = RuntimeSettingsProjection(
        public_base_url=value.get("public_base_url"),
        budget_advisor_owner_confirmed=value.get("budget_advisor_owner_confirmed"),
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
        projection = RuntimeSettingsProjection(
            public_base_url=(str(mutation.value) if mutation.field == "public_base_url" else current.public_base_url),
            budget_advisor_owner_confirmed=(
                bool(mutation.value)
                if mutation.field == "budget_advisor_owner_confirmed"
                else current.budget_advisor_owner_confirmed
            ),
        )
        write_runtime_settings(path, projection, service_owned=service_owned)
        return projection
