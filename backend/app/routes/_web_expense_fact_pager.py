"""Anchored revision-timeline pager projection for the Web fact surface."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.routes._web_expense_return_context import ExpenseReturnContext, edit_context_params


def timeline_page_url(
    return_context: ExpenseReturnContext,
    *,
    expense_id: int,
    selected_ledger_id: str,
    page: int,
    snapshot: int | None = None,
) -> str:
    # ``snapshot`` 锚来自服务端 response（非请求回显）：同一历史视图内 page±1
    # 都钉在同一 rev_snapshot 上；只有重新进入事实页（不带该参数）才取新快照。
    params: list[tuple[str, str]] = [
        ("ledger_id", selected_ledger_id),
        ("rev_page", str(page)),
    ]
    if snapshot is not None:
        params.append(("rev_snapshot", str(snapshot)))
    params.extend(edit_context_params(**return_context.as_kwargs()).items())
    return f"/web/expenses/{expense_id}/edit?{urlencode(params)}#fact-timeline"


def fact_timeline_page_context(
    return_context: ExpenseReturnContext,
    *,
    timeline: dict[str, Any],
    expense_id: int,
    selected_ledger_id: str,
) -> dict[str, Any]:
    """Project one anchored revision page into pager links and counters."""

    page_context = {
        key: timeline[key]
        for key in ("page", "page_size", "total", "snapshot_revision", "has_newer", "has_older")
    }
    page_context["older_remaining"] = max(
        0,
        timeline["total"] - timeline["page"] * timeline["page_size"],
    )
    page_context["newer_url"] = (
        timeline_page_url(
            return_context,
            expense_id=expense_id,
            selected_ledger_id=selected_ledger_id,
            page=timeline["page"] - 1,
            snapshot=timeline["snapshot_revision"],
        )
        if timeline["has_newer"]
        else ""
    )
    page_context["older_url"] = (
        timeline_page_url(
            return_context,
            expense_id=expense_id,
            selected_ledger_id=selected_ledger_id,
            page=timeline["page"] + 1,
            snapshot=timeline["snapshot_revision"],
        )
        if timeline["has_older"]
        else ""
    )
    return page_context
