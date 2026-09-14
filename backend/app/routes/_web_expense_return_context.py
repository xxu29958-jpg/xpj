"""Validated list-origin state for Web expense edit flows."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from fastapi import Form

from app.services.currency_common import supported_currency_codes
from app.services.web_search_service import MAX_QUERY_LENGTH

RETURN_TO_PATHS: dict[str, str] = {
    "pending": "/web/pending",
    "confirmed": "/web/confirmed",
    "reports": "/web/reports",
    "duplicates": "/web/duplicates",
    "search": "/web/search",
    "bill_splits_inbox": "/web/bill-splits/inbox",
    "bill_splits_sent": "/web/bill-splits/sent",
}
RETURN_TO_LABELS: dict[str, str] = {
    "pending": "返回待确认",
    "confirmed": "返回已确认流水",
    "reports": "返回原月份月报",
    "duplicates": "返回重复检查",
    "search": "返回搜索结果",
    "bill_splits_inbox": "返回拆账收件箱",
    "bill_splits_sent": "返回已发拆账",
}
_PENDING_FILTERS = {
    "all",
    "missing_amount",
    "missing_merchant",
    "missing_category",
    "missing_fx",
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
    "home_currency_code": "return_home_currency_code",
    "granularity": "return_granularity",
    "ranking_metric": "return_ranking_metric",
    "merchant_category": "return_merchant_category",
}


@dataclass(frozen=True)
class ExpenseReturnContext:
    """Browser origin carried through one expense fact/correction journey."""

    return_to: str = ""
    return_month: str = ""
    return_filter: str = ""
    return_page: str = ""
    return_tag: str = ""
    return_query: str = ""
    return_home_currency_code: str = ""
    return_granularity: str = ""
    return_ranking_metric: str = ""
    return_merchant_category: str = ""

    def as_kwargs(self) -> dict[str, str]:
        return asdict(self)


def expense_return_query_context(
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
    return_home_currency_code: str = "",
    return_granularity: str = "",
    return_ranking_metric: str = "",
    return_merchant_category: str = "",
) -> ExpenseReturnContext:
    return ExpenseReturnContext(
        return_to=return_to,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
        return_home_currency_code=return_home_currency_code,
        return_granularity=return_granularity,
        return_ranking_metric=return_ranking_metric,
        return_merchant_category=return_merchant_category,
    )


def expense_return_form_context(
    return_to: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    return_home_currency_code: str = Form(default=""),
    return_granularity: str = Form(default=""),
    return_ranking_metric: str = Form(default=""),
    return_merchant_category: str = Form(default=""),
) -> ExpenseReturnContext:
    return ExpenseReturnContext(
        return_to=return_to,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
        return_home_currency_code=return_home_currency_code,
        return_granularity=return_granularity,
        return_ranking_metric=return_ranking_metric,
        return_merchant_category=return_merchant_category,
    )


def clean_return_to(raw: str) -> str:
    token = (raw or "").strip()
    return token if token in RETURN_TO_PATHS else ""


def resolve_return_to(raw: str, default_path: str) -> str:
    token = clean_return_to(raw)
    return RETURN_TO_PATHS.get(token, default_path)


def return_context_params(return_to: str, **origin: str) -> dict[str, str]:
    """Return only query fields valid for the allowlisted origin page."""
    token = clean_return_to(return_to)
    if token == "pending":
        clean_filter = (origin.get("return_filter") or "").strip()
        return {"filter": clean_filter} if clean_filter in _PENDING_FILTERS else {}
    if token in {"confirmed", "reports"}:
        params = _confirmed_report_return_params(token, **{key: origin.get(key, "") for key in
            ("return_month", "return_filter", "return_page", "return_tag")})
        if token == "reports":
            params.update(_report_return_params(origin))
        home = (origin.get("return_home_currency_code") or "").strip()
        if home in supported_currency_codes():
            params["home_currency_code"] = home
        return params
    if token == "search":
        query = (origin.get("return_query") or "").strip()
        if query and len(query) <= MAX_QUERY_LENGTH:
            return {"q": query}
    return {}


def _report_return_params(origin: dict[str, str]) -> dict[str, str]:
    params = {}
    choices = {"home_currency_code": supported_currency_codes(),
        "granularity": {"day", "week", "month"}, "ranking_metric": {"amount", "count"}}
    for key, allowed in choices.items():
        value = (origin.get(f"return_{key}") or "").strip()
        if value in allowed:
            params[key] = value
    category = (origin.get("return_merchant_category") or "").strip()
    if category and len(category) <= 64:
        params["merchant_category"] = category
    return params


def _confirmed_report_return_params(
    token: str,
    *,
    return_month: str,
    return_filter: str,
    return_page: str,
    return_tag: str,
) -> dict[str, str]:
    """Preserve only the selected confirmed-list or report origin's fields."""
    params: dict[str, str] = {}
    clean_month = (return_month or "").strip()
    if _MONTH_RE.fullmatch(clean_month):
        params["month"] = clean_month
    if token == "reports":
        return params
    if (return_filter or "").strip() == "missing_category":
        params.pop("month", None)
        params["filter"] = "missing_category"
    clean_page = (return_page or "").strip()
    if clean_page.isdigit() and 1 <= int(clean_page) <= 100_000:
        params["page"] = clean_page
    clean_tag = (return_tag or "").strip()
    if clean_tag and len(clean_tag) <= 64:
        params["tag"] = clean_tag
    return params


def edit_context_params(return_to: str, **origin: str) -> dict[str, str]:
    """Keep a validated origin attached while the user remains in edit."""
    token = clean_return_to(return_to)
    if not token:
        return {}
    list_params = return_context_params(token, **origin)
    return {"return_to": token, **{_EDIT_KEY_BY_LIST_KEY[key]: value for key, value in list_params.items()}}


def flow_href(path: str, *, ledger_id: str, return_to: str = "", **origin: str) -> str:
    """Keep validated list-origin state on a fact/correction flow link."""
    params = {"ledger_id": ledger_id, **edit_context_params(return_to, **origin)}
    return f"{path}?{urlencode(params)}"


def return_label(return_to: str, *, default: str = "返回流水") -> str:
    return RETURN_TO_LABELS.get(clean_return_to(return_to), default)


def return_href(return_to: str, *, ledger_id: str, default_path: str, **origin: str) -> str:
    path = resolve_return_to(return_to, default_path)
    params = {"ledger_id": ledger_id, **return_context_params(return_to, **origin)}
    return f"{path}?{urlencode(params)}"


def edit_navigation_view(context: ExpenseReturnContext, *, expense_id: int, ledger_id: str) -> dict:
    """Project one validated origin into the form fields and both navigation links."""
    params = context.as_kwargs()
    return {
        "edit_return_fields": edit_context_params(**params),
        "edit_current_href": flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=ledger_id, **params),
        "edit_return_href": return_href(ledger_id=ledger_id, default_path="/web/pending", **params),
        "edit_return_label": return_label(context.return_to),
    }
