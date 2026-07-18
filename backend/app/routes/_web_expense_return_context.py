"""Validated return-state helpers for Web expense edit flows."""

from __future__ import annotations

import re

# The drawer is served from a small set of list pages. Keep every return target
# and query field on an explicit allowlist so hidden form values cannot widen
# the same-site redirect surface.
RETURN_TO_PATHS: dict[str, str] = {
    "pending": "/web/pending",
    "confirmed": "/web/confirmed",
    "duplicates": "/web/duplicates",
}
_PENDING_FILTERS = {
    "all",
    "missing_amount",
    "missing_merchant",
    "missing_category",
    "duplicate",
    "ready",
}
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def resolve_return_to(raw: str, default_path: str) -> str:
    """Map a hidden ``return_to`` token to a whitelisted Web list path."""
    return RETURN_TO_PATHS.get((raw or "").strip(), default_path)


def return_context_params(
    return_to: str,
    *,
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
) -> dict[str, str]:
    """Return only list-query fields allowed for a whitelisted edit origin."""
    token = (return_to or "").strip()
    if token == "pending":
        clean_filter = (return_filter or "").strip()
        return {"filter": clean_filter} if clean_filter in _PENDING_FILTERS else {}
    if token == "confirmed":
        params: dict[str, str] = {}
        clean_month = (return_month or "").strip()
        if _MONTH_RE.fullmatch(clean_month):
            params["month"] = clean_month
        clean_page = (return_page or "").strip()
        if clean_page.isdigit() and 1 <= int(clean_page) <= 100_000:
            params["page"] = clean_page
        clean_tag = (return_tag or "").strip()
        if clean_tag and len(clean_tag) <= 64:
            params["tag"] = clean_tag
        return params
    return {}


def edit_context_params(
    return_to: str,
    *,
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
) -> dict[str, str]:
    """Keep a validated list origin attached while remaining on the edit page."""
    token = (return_to or "").strip()
    if token not in RETURN_TO_PATHS:
        return {}
    list_params = return_context_params(
        token,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
    )
    params = {"return_to": token}
    params.update({f"return_{key}": value for key, value in list_params.items()})
    return params
