"""Shared JSON boundary types for service contracts.

These aliases are for values that genuinely cross a JSON boundary: decoded
provider responses, serialized learning payloads, and free-form task summaries.
Use narrower DTO/TypedDict contracts where a response shape is known.
"""

from __future__ import annotations

from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonContainer: TypeAlias = list[object] | dict[str, object]
JsonValue: TypeAlias = JsonScalar | JsonContainer
JsonObject: TypeAlias = dict[str, JsonValue]
