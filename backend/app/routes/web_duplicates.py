"""/web/duplicates side-by-side review (v0.4-alpha3 slice 2 / PR18).

Lists every pending expense currently flagged as a suspected duplicate
together with the row it duplicates, so the user can resolve the pair
in a single click:

* **保留两条** — calls ``mark_expense_not_duplicate`` (records the ignore
  pair so it never re-fires for the same kind).
* **删除当前** — rejects the suspected row.
* **删除被复制的那条** — rejects the original row instead, then clears the
  suspected flag on the kept row so it stops blocking review.

All actions stay loopback-only via ``LocalOnly`` and respect ledger
isolation via ``selected_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    templates,
)
from app.services.expense_service import (
    get_expense,
    list_duplicate_expenses,
    list_expenses_by_ids,
    mark_expense_not_duplicate,
    reject_expense,
)

if TYPE_CHECKING:
    from app.models import Expense

router = APIRouter(prefix="/web", tags=["web"])


def _load_pair(db: Session, *, tenant_id: str, expense_id: int) -> tuple[Expense, Expense | None]:
    expense = get_expense(db, expense_id, tenant_id)
    other: Expense | None = None
    if expense.duplicate_of_id is not None:
        others = list_expenses_by_ids(
            db, tenant_id=tenant_id, expense_ids=[expense.duplicate_of_id]
        )
        other = others[0] if others else None
    return expense, other


@router.get("/duplicates", response_class=HTMLResponse)
def web_duplicates(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    rows = list_duplicate_expenses(db, selected_id)
    # Single batched query for every referenced original; pair-build loop
    # below does in-memory lookup. No N+1 over duplicate rows.
    original_ids = sorted({row.duplicate_of_id for row in rows if row.duplicate_of_id is not None})
    originals_by_id = {
        e.id: e
        for e in list_expenses_by_ids(db, tenant_id=selected_id, expense_ids=original_ids)
    }
    pairs = []
    for row in rows:
        original = (
            originals_by_id.get(row.duplicate_of_id)
            if row.duplicate_of_id is not None
            else None
        )
        reason = row.duplicate_reason or ""
        # 把判定 reason 字符串映射成相似度 score（高/中置信度 pill 用）。
        # 后端目前没有持久化 score；规则简单透明，由 reason 关键词派生。
        if "hash" in reason or "完全一致" in reason:
            score = 0.98
        elif "金额" in reason and "时间" in reason:
            score = 0.85
        elif reason:
            score = 0.72
        else:
            score = 0.7
        current_view = _expense_view(row)
        original_view = _expense_view(original) if original is not None else None
        diff_fields: list[str] = []
        if original_view:
            if current_view.get("merchant") != original_view.get("merchant"):
                diff_fields.append("merchant")
            if current_view.get("amount_cents") != original_view.get("amount_cents"):
                diff_fields.append("amount")
            if current_view.get("expense_time") != original_view.get("expense_time"):
                diff_fields.append("time")
        pairs.append(
            {
                "current": current_view,
                "original": original_view,
                "reason": reason,
                "score": score,
                "score_pct": int(round(score * 100)),
                "confidence_tier": "high" if score >= 0.9 else "mid",
                "diff_fields": diff_fields,
            }
        )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="疑似重复",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["duplicate_pairs"] = pairs
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="duplicates.html", context=ctx
    )


def _parse_form_updated_at(value: str) -> datetime | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None


_STALE_DUPLICATE_MSG = "账单已在其它端被修改，请刷新后重新操作。"


@router.post("/duplicates/{expense_id}/keep")
def web_duplicate_keep(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_updated_at: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = _parse_form_updated_at(expected_updated_at)
    if parsed is None:
        return _web_redirect("/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG)
    try:
        mark_expense_not_duplicate(
            db, expense_id, selected_id, expected_updated_at=parsed
        )
        msg = "已标记为「不是重复」。"
    except AppError as exc:
        msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
    return _web_redirect("/web/duplicates", selected_id, msg=msg)


@router.post("/duplicates/{expense_id}/reject-current")
def web_duplicate_reject_current(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_updated_at: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = _parse_form_updated_at(expected_updated_at)
    if parsed is None:
        return _web_redirect("/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG)
    try:
        reject_expense(db, expense_id, selected_id, expected_updated_at=parsed)
        msg = "已删除当前账单。"
    except AppError as exc:
        msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
    return _web_redirect("/web/duplicates", selected_id, msg=msg)


@router.post("/duplicates/{expense_id}/reject-original")
def web_duplicate_reject_original(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_updated_at: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = _parse_form_updated_at(expected_updated_at)
    if parsed is None:
        return _web_redirect("/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG)
    msg = "已删除被复制的那条，并保留当前账单。"
    try:
        current, original = _load_pair(db, tenant_id=selected_id, expense_id=expense_id)
        if original is None:
            raise AppError("invalid_request", "找不到被复制的账单。", status_code=404)
        # ADR-0038 PR-2b: client only owns the *current* row's token
        # (which is the row the duplicates UI surfaces); the linked
        # ``original`` row is server-internal — we use its own
        # ``updated_at`` as the internal token for the cascaded reject.
        reject_expense(
            db, original.id, selected_id, expected_updated_at=original.updated_at
        )
        # Clear the suspected flag on the kept row using the
        # client-provided token (matches the row the UI displayed).
        mark_expense_not_duplicate(
            db, current.id, selected_id, expected_updated_at=parsed
        )
    except AppError as exc:
        msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
    return _web_redirect("/web/duplicates", selected_id, msg=msg)
