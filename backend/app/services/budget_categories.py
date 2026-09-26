"""Budget category validation shared by current arrangements and history."""

import json

from app.errors import AppError
from app.services.category_common import normalize_category


def clean_budget_category(value: str) -> str:
    raw = (value or "").strip()
    if not raw or len(raw) > 64:
        raise AppError("invalid_request", status_code=422)
    return normalize_category(raw)


def parse_budget_exclusions(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        try:
            category = clean_budget_category(item)
        except AppError:
            continue
        if category not in seen:
            normalized.append(category)
            seen.add(category)
    return normalized
