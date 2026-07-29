"""/web/duplicates side-by-side review (v0.4-alpha3 slice 2 / PR18).

Lists every pending expense currently flagged as a suspected duplicate
together with its referenced comparison row, so the user can resolve the pair
in a single click. Either row may still be pending or already confirmed:

* **不是重复，保留两条** — calls ``mark_expense_not_duplicate`` (records the
  ignore pair so it never re-fires for the same kind).
* **忽略当前记录** — rejects the suspected row (restorable).
* **忽略参考记录** — rejects the referenced row instead, then clears the
  suspected flag on the kept row so it stops blocking review.

All actions stay loopback-only via ``LocalOnly`` and respect ledger
isolation via ``selected_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_expense_helpers import (
    drawer_fragment_error,
    drawer_fragment_ok,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    parse_form_row_version_token,
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


# 218-D S4 (移植自产品矿): 重复对照页的行状态 chip 与判定原因文案由路由 glue
# 提供, 模板只读 status_label/status_tone/reason_label, 不拼原始 status 串。
_EXPENSE_STATUS_UI = {
    "pending": ("待确认", "warning"),
    "confirmed": ("已入账", "success"),
    "rejected": ("已忽略", ""),
}


def _duplicate_expense_view(expense) -> dict:
    view = _expense_view(expense)
    status_label, status_tone = _EXPENSE_STATUS_UI.get(
        str(view.get("status") or ""),
        ("状态待确认", ""),
    )
    view["status_label"] = status_label
    view["status_tone"] = status_tone
    return view


def _duplicate_reason_label(reason: str) -> str:
    if "感知" in reason and "hash" in reason:
        return "两张图片内容高度相似"
    if "hash" in reason or "完全一致" in reason:
        return "两张图片完全一致"
    if "金额" in reason and "时间" in reason:
        return "金额、商家和消费时间接近"
    return "多项账单信息相似"


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
    flash_type: str = "",
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
        current_view = _duplicate_expense_view(row)
        original_view = _duplicate_expense_view(original) if original is not None else None
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
                "reason_label": _duplicate_reason_label(reason),
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
    # S4-R1: 与 pending 同族 — 只有 error/success 两个合法值, 其余回落默认
    # info 样式, 避免查询参数驱动任意类名。
    ctx["flash_type"] = flash_type if flash_type in ("success", "error") else ""
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="duplicates.html", context=ctx
    )


_STALE_DUPLICATE_MSG = "账单已在其它端被修改，请刷新后重新操作。"


@router.post("/duplicates/{expense_id}/keep")
def web_duplicate_keep(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    # 批10: the pending drawer's 「标为非重复」 button has formaction → this route.
    # ``fragment=1`` switches to the drawer fetch-mutation contract (success →
    # tiny 200 so the client re-fetches the now-unflagged drawer; error → the
    # drawer fragment carrying the error). The /web/duplicates side-by-side page
    # keeps the existing full-page redirect.
    fragment: int = Form(0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        if fragment:
            return drawer_fragment_error(
                db, request, options, selected_id, expense_id, _STALE_DUPLICATE_MSG
            )
        return _web_redirect(
            "/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG, flash_type="error"
        )
    error_msg: str | None = None
    try:
        mark_expense_not_duplicate(
            db, expense_id, selected_id, expected_row_version=parsed
        )
        msg = "已按两条独立记录保留。"
    except AppError as exc:
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        msg = error_msg
    if fragment:
        if error_msg is not None:
            return drawer_fragment_error(
                db, request, options, selected_id, expense_id, error_msg
            )
        return drawer_fragment_ok("keep")
    return _web_redirect(
        "/web/duplicates",
        selected_id,
        msg=msg,
        flash_type="error" if error_msg is not None else "success",
    )


@router.post("/duplicates/{expense_id}/reject-current")
def web_duplicate_reject_current(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG, flash_type="error"
        )
    error_msg: str | None = None
    try:
        reject_expense(db, expense_id, selected_id, expected_row_version=parsed)
        msg = "已忽略当前记录。"
    except AppError as exc:
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        msg = error_msg
    return _web_redirect(
        "/web/duplicates",
        selected_id,
        msg=msg,
        flash_type="error" if error_msg is not None else "success",
    )


@router.post("/duplicates/{expense_id}/reject-original")
def web_duplicate_reject_original(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG, flash_type="error"
        )
    msg = "已忽略参考记录，并保留当前记录。"
    error_msg: str | None = None
    try:
        current, original = _load_pair(db, tenant_id=selected_id, expense_id=expense_id)
        if original is None:
            raise AppError("invalid_request", "找不到被复制的账单。", status_code=404)
        # ADR-0038 PR-2b: client only owns the *current* row's token
        # (which is the row the duplicates UI surfaces); the linked
        # ``original`` row is server-internal — we use its own
        # ``row_version`` as the internal token for the cascaded reject.
        reject_expense(
            db, original.id, selected_id, expected_row_version=original.row_version
        )
        # Clear the suspected flag on the kept row using the
        # client-provided token (matches the row the UI displayed).
        mark_expense_not_duplicate(
            db, current.id, selected_id, expected_row_version=parsed
        )
    except AppError as exc:
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        msg = error_msg
    return _web_redirect(
        "/web/duplicates",
        selected_id,
        msg=msg,
        flash_type="error" if error_msg is not None else "success",
    )
