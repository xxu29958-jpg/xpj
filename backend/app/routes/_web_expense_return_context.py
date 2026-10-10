"""Validated list-origin state for Web expense edit flows."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Form

from app.services.currency_common import supported_currency_codes
from app.services.web_search_service import MAX_QUERY_LENGTH

RETURN_TO_PATHS: dict[str, str] = {
    "pending": "/web/pending",
    "confirmed": "/web/confirmed",
    "reports": "/web/reports",
    "duplicates": "/web/duplicates",
    "uncategorized": "/web/categories/uncategorized",
    "search": "/web/search",
    "originals": "/web/originals",
    "bill_splits_inbox": "/web/bill-splits/inbox",
    "bill_splits_sent": "/web/bill-splits/sent",
}
_DYNAMIC_RETURN_TO = frozenset({"recurring_occurrence", "csv_import_event"})
CONFIRMED_CROSS_PERIOD_FILTERS = frozenset({"missing_category", "missing_accounting_date"})
RETURN_TO_LABELS: dict[str, str] = {
    "pending": "返回待确认",
    "confirmed": "返回已确认流水",
    "reports": "返回原月份月报",
    "duplicates": "返回重复检查",
    "uncategorized": "返回补分类",
    "search": "返回搜索结果",
    "originals": "返回原件检查",
    "bill_splits_inbox": "返回拆账收件箱",
    "bill_splits_sent": "返回已发拆账",
    "recurring_occurrence": "返回本期固定支出",
    "csv_import_event": "返回导入复核",
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
    "after": "return_after",
    "draft_ref": "return_category_draft_ref",
    "receipt": "return_category_receipt_key",
    "focus": "return_duplicate_expense_id",
    "filter": "return_filter",
    "month": "return_month",
    "page": "return_page",
    "tag": "return_tag",
    "q": "return_query",
    "category": "return_category",
    "home_currency_code": "return_home_currency_code",
    "granularity": "return_granularity",
    "ranking_metric": "return_ranking_metric",
    "merchant_category": "return_merchant_category",
}


@dataclass(frozen=True)
class ExpenseReturnContext:
    """Browser origin carried through one expense fact/correction journey."""

    return_to: str = ""
    return_after: str = ""
    return_month: str = ""
    return_filter: str = ""
    return_page: str = ""
    return_tag: str = ""
    return_query: str = ""
    return_category: str = ""
    return_home_currency_code: str = ""
    return_granularity: str = ""
    return_ranking_metric: str = ""
    return_merchant_category: str = ""
    return_recurring_public_id: str = ""
    return_payment_expense_id: str = ""
    return_payment_month: str = ""
    return_import_public_id: str = ""
    return_import_line_number: str = ""
    return_import_expense_id: str = ""
    return_receipt_key: str = ""
    return_receipt_expense_id: str = ""
    return_review_ref: str = ""
    return_review_expense_id: str = ""
    return_review_family: str = ""
    return_duplicate_expense_id: str = ""
    return_category_draft_ref: str = ""
    return_category_receipt_key: str = ""

    def as_kwargs(self) -> dict[str, str]:
        return asdict(self)


def expense_return_query_context(
    return_to: str = "",
    return_after: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
    return_category: str = "",
    return_home_currency_code: str = "",
    return_granularity: str = "",
    return_ranking_metric: str = "",
    return_merchant_category: str = "",
    return_recurring_public_id: str = "",
    return_payment_expense_id: str = "",
    return_payment_month: str = "",
    return_import_public_id: str = "",
    return_import_line_number: str = "",
    return_import_expense_id: str = "",
    return_receipt_key: str = "",
    return_receipt_expense_id: str = "",
    return_review_ref: str = "",
    return_review_expense_id: str = "",
    return_review_family: str = "",
    return_duplicate_expense_id: str = "",
    return_category_draft_ref: str = "",
    return_category_receipt_key: str = "",
) -> ExpenseReturnContext:
    return ExpenseReturnContext(
        return_to=return_to,
        return_after=return_after,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
        return_category=return_category,
        return_home_currency_code=return_home_currency_code,
        return_granularity=return_granularity,
        return_ranking_metric=return_ranking_metric,
        return_merchant_category=return_merchant_category,
        return_recurring_public_id=return_recurring_public_id,
        return_payment_expense_id=return_payment_expense_id,
        return_payment_month=return_payment_month,
        return_import_public_id=return_import_public_id,
        return_import_line_number=return_import_line_number,
        return_import_expense_id=return_import_expense_id,
        return_receipt_key=return_receipt_key,
        return_receipt_expense_id=return_receipt_expense_id,
        return_review_ref=return_review_ref,
        return_review_expense_id=return_review_expense_id,
        return_review_family=return_review_family,
        return_duplicate_expense_id=return_duplicate_expense_id,
        return_category_draft_ref=return_category_draft_ref,
        return_category_receipt_key=return_category_receipt_key,
    )


def expense_return_form_context(
    return_to: str = Form(default=""),
    return_after: str = Form(default=""),
    return_month: str = Form(default=""),
    return_filter: str = Form(default=""),
    return_page: str = Form(default=""),
    return_tag: str = Form(default=""),
    return_query: str = Form(default=""),
    return_category: str = Form(default=""),
    return_home_currency_code: str = Form(default=""),
    return_granularity: str = Form(default=""),
    return_ranking_metric: str = Form(default=""),
    return_merchant_category: str = Form(default=""),
    return_recurring_public_id: str = Form(default=""),
    return_payment_expense_id: str = Form(default=""),
    return_payment_month: str = Form(default=""),
    return_import_public_id: str = Form(default=""),
    return_import_line_number: str = Form(default=""),
    return_import_expense_id: str = Form(default=""),
    return_receipt_key: str = Form(default=""),
    return_receipt_expense_id: str = Form(default=""),
    return_review_ref: str = Form(default=""),
    return_review_expense_id: str = Form(default=""),
    return_review_family: str = Form(default=""),
    return_duplicate_expense_id: str = Form(default=""),
    return_category_draft_ref: str = Form(default=""),
    return_category_receipt_key: str = Form(default=""),
) -> ExpenseReturnContext:
    return ExpenseReturnContext(
        return_to=return_to,
        return_after=return_after,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
        return_category=return_category,
        return_home_currency_code=return_home_currency_code,
        return_granularity=return_granularity,
        return_ranking_metric=return_ranking_metric,
        return_merchant_category=return_merchant_category,
        return_recurring_public_id=return_recurring_public_id,
        return_payment_expense_id=return_payment_expense_id,
        return_payment_month=return_payment_month,
        return_import_public_id=return_import_public_id,
        return_import_line_number=return_import_line_number,
        return_import_expense_id=return_import_expense_id,
        return_receipt_key=return_receipt_key,
        return_receipt_expense_id=return_receipt_expense_id,
        return_review_ref=return_review_ref,
        return_review_expense_id=return_review_expense_id,
        return_review_family=return_review_family,
        return_duplicate_expense_id=return_duplicate_expense_id,
        return_category_draft_ref=return_category_draft_ref,
        return_category_receipt_key=return_category_receipt_key,
    )


def _public_uuid(raw: str) -> str:
    try:
        return str(UUID(str(raw)))
    except (TypeError, ValueError):
        return ""


def _recurring_period(raw: str) -> str:
    month = (raw or "").strip()
    return month if _MONTH_RE.fullmatch(month) else ""


def _payment_expense_id(raw: str) -> str:
    expense_id = (raw or "").strip()
    if (
        0 < len(expense_id) <= 10
        and expense_id.isascii()
        and expense_id.isdigit()
        and 0 < int(expense_id) <= 2_147_483_647
    ):
        return expense_id
    return ""


def recurring_occurrence_origin(
    *,
    return_recurring_public_id: str,
    return_month: str,
    return_payment_expense_id: str = "",
    return_payment_month: str = "",
    return_query: str = "",
) -> dict[str, str] | None:
    series_id = _public_uuid(return_recurring_public_id)
    period = _recurring_period(return_month)
    if not series_id or not period:
        return None
    origin = {
        "return_to": "recurring_occurrence",
        "return_recurring_public_id": series_id,
        "return_month": period,
    }
    payment_id = _payment_expense_id(return_payment_expense_id)
    if payment_id:
        origin["return_payment_expense_id"] = payment_id
    payment_month = (return_payment_month or "").strip()
    if payment_month == "all" or _MONTH_RE.fullmatch(payment_month):
        origin["return_payment_month"] = payment_month
    query = (return_query or "").strip()
    if query and len(query) <= 150:
        origin["return_query"] = query
    return origin


def clean_return_to(raw: str) -> str:
    token = (raw or "").strip()
    return token if token in RETURN_TO_PATHS or token in _DYNAMIC_RETURN_TO else ""


def _csv_import_origin(origin: dict[str, str]) -> dict[str, str]:
    batch = _public_uuid(origin.get("return_import_public_id", ""))
    line = _payment_expense_id(origin.get("return_import_line_number", ""))
    if not batch or not line or int(line) < 2:
        return {}
    kept = {"return_to": "csv_import_event", "return_import_public_id": batch,
        "return_import_line_number": line}
    selected = _payment_expense_id(origin.get("return_import_expense_id", ""))
    if selected:
        kept["return_import_expense_id"] = selected
    return kept


def resolve_return_to(raw: str, default_path: str, **origin: str) -> str:
    token = clean_return_to(raw)
    if token == "recurring_occurrence":
        series_id = _public_uuid(origin.get("return_recurring_public_id", ""))
        return f"/web/recurring/{series_id}/occurrence" if series_id else default_path
    if token == "csv_import_event":
        kept = _csv_import_origin(origin)
        if kept:
            return f"/web/import/{kept['return_import_public_id']}/rows/{kept['return_import_line_number']}/review"
        return default_path
    return RETURN_TO_PATHS.get(token, default_path)


def _recurring_list_return_params(origin: dict[str, str]) -> dict[str, str]:
    kept = recurring_occurrence_origin(
        return_recurring_public_id=origin.get("return_recurring_public_id", ""),
        return_month=origin.get("return_month", ""),
        return_payment_expense_id=origin.get("return_payment_expense_id", ""),
        return_payment_month=origin.get("return_payment_month", ""),
        return_query=origin.get("return_query", ""),
    )
    if not kept:
        return {}
    params = {"month": kept["return_month"]}
    if kept.get("return_payment_expense_id"):
        params["payment_id"] = kept["return_payment_expense_id"]
    if kept.get("return_payment_month"):
        params["payment_month"] = kept["return_payment_month"]
    if kept.get("return_query"):
        params["q"] = kept["return_query"]
    return params


def return_context_params(return_to: str, **origin: str) -> dict[str, str]:
    """Return only query fields valid for the allowlisted origin page."""
    token = clean_return_to(return_to)
    if token == "pending":
        clean_filter = (origin.get("return_filter") or "").strip()
        return {"filter": clean_filter} if clean_filter in _PENDING_FILTERS else {}
    if token == "duplicates":
        focus = _payment_expense_id(origin.get("return_duplicate_expense_id", ""))
        return {"focus": focus} if focus else {}
    if token == "uncategorized":
        return _uncategorized_return_params(origin)
    if token == "confirmed":
        return _confirmed_return_params(origin)
    if token == "reports":
        return _report_return_params(origin)
    if token == "search":
        return _search_return_params(origin)
    if token == "originals":
        return {"after": _payment_expense_id(origin.get("return_after", "")) or "0"}
    if token == "recurring_occurrence":
        return _recurring_list_return_params(origin)
    if token == "csv_import_event":
        kept = _csv_import_origin(origin)
        selected = kept.get("return_import_expense_id")
        return {"expense_id": selected} if selected else {}
    return {}


def _uncategorized_return_params(origin: dict[str, str]) -> dict[str, str]:
    kept = {"filter": "including_other"} if origin.get("return_filter") == "including_other" else {}
    for key in ("draft_ref", "receipt"):
        value = _public_uuid(origin.get(_EDIT_KEY_BY_LIST_KEY[key], ""))
        if value:
            kept[key] = value
    return kept


def _search_return_params(origin: dict[str, str]) -> dict[str, str]:
    query = (origin.get("return_query") or "").strip()
    return {"q": query} if query and len(query) <= MAX_QUERY_LENGTH else {}


def _report_return_params(origin: dict[str, str]) -> dict[str, str]:
    params = {}
    month = (origin.get("return_month") or "").strip()
    if _MONTH_RE.fullmatch(month):
        params["month"] = month
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


def _confirmed_return_params(origin: dict[str, str]) -> dict[str, str]:
    """Keep the confirmed-list filters, including its currency projection."""
    params: dict[str, str] = {}
    clean_month = (origin.get("return_month") or "").strip()
    if _MONTH_RE.fullmatch(clean_month):
        params["month"] = clean_month
    clean_filter = (origin.get("return_filter") or "").strip()
    if clean_filter in CONFIRMED_CROSS_PERIOD_FILTERS:
        params.pop("month", None)
        params["filter"] = clean_filter
    clean_page = (origin.get("return_page") or "").strip()
    if clean_page.isdigit() and 1 <= int(clean_page) <= 100_000:
        params["page"] = clean_page
    home = (origin.get("return_home_currency_code") or "").strip()
    if home in supported_currency_codes():
        params["home_currency_code"] = home
    for field, key, limit in (("return_tag", "tag", 64), ("return_query", "q", MAX_QUERY_LENGTH),
                              ("return_category", "category", 64)):
        value = (origin.get(field) or "").strip()
        if value and len(value) <= limit:
            params[key] = value
    return params


def edit_context_params(return_to: str, **origin: str) -> dict[str, str]:
    """Keep a validated origin attached while the user remains in edit."""
    token = clean_return_to(return_to)
    if token == "csv_import_event":
        kept = _csv_import_origin(origin)
    elif token == "recurring_occurrence":
        kept = recurring_occurrence_origin(
            return_recurring_public_id=origin.get("return_recurring_public_id", ""),
            return_month=origin.get("return_month", ""),
            return_payment_expense_id=origin.get("return_payment_expense_id", ""),
            return_payment_month=origin.get("return_payment_month", ""),
            return_query=origin.get("return_query", ""),
        ) or {}
    elif token:
        list_params = return_context_params(token, **origin)
        kept = {"return_to": token, **{_EDIT_KEY_BY_LIST_KEY[key]: value for key, value in list_params.items()}}
    else:
        kept = {}
    return {**kept, **(_review_origin(origin) or _receipt_origin(origin))}


def _review_origin(origin: dict[str, str]) -> dict[str, str]:
    ref = _public_uuid(origin.get("return_review_ref", ""))
    expense_id = _payment_expense_id(origin.get("return_review_expense_id", ""))
    if ref and expense_id:
        family = origin.get("return_review_family", "")
        return {"return_review_ref": ref, "return_review_expense_id": expense_id,
            **({"return_review_family": family} if family in {"expenseitems", "expensesplits", "expenseack", "expensetext", "expenseocr"} else {})}
    return {}


def _receipt_origin(origin: dict[str, str]) -> dict[str, str]:
    key = origin.get("return_receipt_key", "")
    expense_id = _payment_expense_id(origin.get("return_receipt_expense_id", ""))
    if expense_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
        return {"return_receipt_key": key, "return_receipt_expense_id": expense_id}
    return {}


def flow_href(path: str, *, ledger_id: str, return_to: str = "", **origin: str) -> str:
    """Keep validated list-origin state on a fact/correction flow link."""
    params = {"ledger_id": ledger_id, **edit_context_params(return_to, **origin)}
    return f"{path}?{urlencode(params)}"


def return_label(return_to: str, *, default: str = "返回流水") -> str:
    return RETURN_TO_LABELS.get(clean_return_to(return_to), default)


def return_href(return_to: str, *, ledger_id: str, default_path: str, **origin: str) -> str:
    if review := _review_origin(origin):
        family = review.get("return_review_family", "expensereview")
        task_path = {"expensetext": "recognize-text", "expenseocr": "ocr/retry"}.get(family, "edit")
        path = f"/web/expenses/{review['return_review_expense_id']}/{task_path}"
        href = flow_href(path, ledger_id=ledger_id, return_to=return_to,
            **{key: value for key, value in origin.items() if key not in review and key not in _receipt_origin(origin)})
        task_query = "&confirmation_task=1" if task_path == "edit" else ""
        return f"{href}{task_query}#{family}-edit-{review['return_review_ref']}"
    if receipt := _receipt_origin(origin):
        path = f"/web/expenses/{receipt['return_receipt_expense_id']}/confirmation/{receipt['return_receipt_key']}"
        return flow_href(path, ledger_id=ledger_id, return_to=return_to,
            **{key: value for key, value in origin.items() if key not in receipt})
    path = resolve_return_to(return_to, default_path, **origin)
    params = {"ledger_id": ledger_id, **return_context_params(return_to, **origin)}
    if clean_return_to(return_to) == "originals":
        params["inspect"] = "1"
    anchor = f"#categorybatch-create-{params['draft_ref']}" if clean_return_to(return_to) == "uncategorized" and params.get("draft_ref") else ""
    return f"{path}?{urlencode(params)}{anchor}"


def confirm_return_redirect(
    context: ExpenseReturnContext,
    *,
    default_path: str = "/web/pending",
) -> tuple[str, dict[str, str]]:
    """Human confirm must reopen the same origin the create/edit journey carried."""
    kwargs = context.as_kwargs()
    token = context.return_to or "pending"
    return (
        resolve_return_to(token, default_path, **kwargs),
        return_context_params(**{**kwargs, "return_to": token}),
    )


def edit_navigation_view(context: ExpenseReturnContext, *, expense_id: int, ledger_id: str) -> dict:
    """Project one validated origin into the form fields and both navigation links."""
    params = context.as_kwargs()
    return {
        "edit_return_fields": edit_context_params(**params),
        "edit_current_href": flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=ledger_id, **params),
        "edit_return_href": return_href(ledger_id=ledger_id, default_path="/web/pending", **params),
        "edit_return_label": "返回原核对任务" if _review_origin(params) else "返回确认回执" if _receipt_origin(params) else return_label(context.return_to),
        "expense_review_inspection": bool(_review_origin(params)),
    }
