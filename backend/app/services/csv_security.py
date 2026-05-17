from __future__ import annotations

from typing import Any

DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@")


def safe_csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in DANGEROUS_CSV_PREFIXES:
        return "'" + text
    return text
