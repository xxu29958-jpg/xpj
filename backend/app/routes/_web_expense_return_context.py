"""Validated list-origin state for Web expense edit flows."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from app.services.web_search_service import MAX_QUERY_LENGTH

RETURN_TO_PATHS: dict[str, str] = {
    "pending": "/web/pending",
    "confirmed": "/web/confirmed",
    "duplicates": "/web/duplicates",
    "search": "/web/search",
}
RETURN_TO_LABELS: dict[str, str] = {
    "pending": "返回待确认",
    "confirmed": "返回已确认流水",
    "duplicates": "返回重复检查",
    "search": "返回搜索结果",
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
_EDIT_KEY_BY_LIST_KEY = {
    "filter": "return_filter",
    "month": "return_month",
    "page": "return_page",
    "tag": "return_tag",
    "q": "return_query",
}


def clean_return_to(raw: str) -> str:
    token = (raw or "").strip()
    return token if token in RETURN_TO_PATHS else ""


def resolve_return_to(raw: str, default_path: str) -> str:
    token = clean_return_to(raw)
    return RETURN_TO_PATHS.get(token, default_path)


def return_context_params(
    return_to: str,
    *,
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
) -> dict[str, str]:
    """Return only query fields valid for the allowlisted origin page."""

    token = clean_return_to(return_to)
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
    if token == "search":
        query = (return_query or "").strip()
        if query and len(query) <= MAX_QUERY_LENGTH:
            return {"q": query}
    return {}


def edit_context_params(
    return_to: str,
    *,
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
) -> dict[str, str]:
    """Keep a validated origin attached while the user remains in edit."""

    token = clean_return_to(return_to)
    if not token:
        return {}
    list_params = return_context_params(
        token,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
    )
    params = {"return_to": token}
    params.update({_EDIT_KEY_BY_LIST_KEY[key]: value for key, value in list_params.items()})
    return params


def flow_href(
    path: str,
    *,
    ledger_id: str,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
) -> str:
    """Keep validated list-origin state on a fact/correction flow link."""

    params = {"ledger_id": ledger_id}
    params.update(
        edit_context_params(
            return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    )
    return f"{path}?{urlencode(params)}"


def return_label(return_to: str, *, default: str = "返回流水") -> str:
    return RETURN_TO_LABELS.get(clean_return_to(return_to), default)


def return_href(
    return_to: str,
    *,
    ledger_id: str,
    default_path: str,
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
) -> str:
    path = resolve_return_to(return_to, default_path)
    params = {"ledger_id": ledger_id}
    params.update(
        return_context_params(
            return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    )
    return f"{path}?{urlencode(params)}"
