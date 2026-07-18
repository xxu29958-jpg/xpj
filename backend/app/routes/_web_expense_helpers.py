"""Shared helpers for ``/web/expenses/{id}/...`` route modules.

Split out from ``web_expense_edit.py`` so the expense-main / items / splits
route files don't have to import from each other.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_return_context import (
    RETURN_TO_PATHS,
    edit_context_params,
    resolve_return_to,
    return_context_params,
)
from app.routes.web_common import (
    _base_ctx,
    _currency_input_view,
    _expense_view,
    _minor_amount_value,
    _parse_major_amount,
    _web_redirect,
    _with_ledger,
    templates,
)
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
)
from app.services.category_service import list_ledger_category_options
from app.services.expense_service import get_expense
from app.services.expense_split_service import (
    list_active_split_members,
    list_expense_splits,
)
from app.services.receipt_item_service import list_expense_items
from app.services.spending_contract_service import accounting_timezone_key
from app.services.time_service import ensure_utc_assuming_local


def parse_amount_yuan(
    raw: str,
    *,
    currency_code: str,
) -> tuple[int | None, str | None]:
    """Parse a legacy ``*_yuan`` form field at an explicit currency boundary.

    The public form field names are retained for compatibility, but their values
    are major units of the expense's frozen home currency, not necessarily CNY.
    """
    try:
        return (
            _parse_major_amount(
                raw,
                label="金额",
                currency_code=currency_code,
                empty_value=None,
            ),
            None,
        )
    except AppError as exc:
        return None, exc.message


def parse_original_amount(
    raw: str,
    *,
    currency_code: str,
) -> tuple[Decimal | None, str | None]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        _parse_major_amount(
            cleaned,
            label="金额",
            currency_code=currency_code,
            required=True,
        )
    except AppError as exc:
        return None, exc.message
    return Decimal(cleaned), None


def parse_expense_time_local(raw: str | None) -> tuple[datetime | None, str | None]:
    """Parse the edit form's ``<input type="datetime-local">`` value into a UTC
    ``datetime``. Blank means "leave the time unchanged" → ``(None, None)``.

    A datetime-local input yields a *naive* wall-clock string (``2026-05-04T20:00``)
    the user reads as accounting-tz (Asia/Shanghai); we assume-local → UTC so
    storage stays UTC and round-trips with ``_expense_time_local_input``. A value
    that already carries an offset / trailing ``Z`` is honoured as-is (defensive).
    On an unparseable value → ``(None, error)`` so ``web_save`` flashes it via the
    existing edit error path.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None, "请填写正确的时间。"
    return ensure_utc_assuming_local(parsed, accounting_timezone_key()), None


def _edit_page_or_flash_redirect(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
    fallback_path: str,
    error_key: str = "error",
) -> Response:
    """Re-render edit.html with ``error_msg`` — or flash-redirect when the row
    itself is gone.

    Audit P2 #6 + codex follow-up: every POST error path on the edit page
    (main save/confirm/reject AND the items/splits sub-forms) re-reads the
    same expense via :func:`web_edit_context` to re-render the form. If the
    row vanished between the action and the re-read (deleted on another
    surface, swept, cross-ledger), that second read raises again and the
    response degrades to the global bare-JSON handler — the GET route guards
    exactly this case. ``error_key`` selects which template slot carries the
    message ("error" for the main form, "items_error" / "splits_error" for
    the sub-forms); ``fallback_path`` mirrors the GET guard's list.
    """
    try:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
    except AppError as exc:
        return _web_redirect(fallback_path, selected_id, msg=exc.message, flash_type="error")
    ctx[error_key] = error_msg
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


def drawer_fragment_ok(action: str) -> HTMLResponse:
    """批10: minimal 200 body for a successful fetch-mutation from the drawer.

    Desktop ``drawer.js`` requires a non-redirected HTML response carrying this
    action-specific marker before it removes a row or re-fetches the drawer.
    That keeps a followed login redirect from masquerading as success. Never
    return the bare JSON emitted by the global handler.
    """
    return HTMLResponse(f'<div data-drawer-ok="{action}"></div>')


def drawer_fragment_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
) -> Response:
    """批10: re-render ``_edit_drawer.html`` carrying ``error_msg`` for a failed
    fetch-mutation — or the readable empty-cell snippet when the row vanished.

    Mirrors the GET fragment guard in ``web_edit_get`` (a deleted / cross-ledger
    row must not inject raw JSON into the drawer, since drawer.js does not check
    ``res.ok`` on the GET path). The fetch-mutation path *does* check ``res.ok``,
    so this MUST carry a non-2xx status — otherwise the client treats the failure
    as success and removes the row. The vanished-row branch keeps the row's own
    status (404…); the still-present-but-rejected branch uses 422 so the client
    swaps the error fragment into the open drawer instead of advancing.
    """
    try:
        ctx = web_edit_context(db, request, options, selected_id, expense_id)
    except AppError as exc:
        return HTMLResponse(
            f'<div class="empty-cell">{exc.message}</div>',
            status_code=exc.status_code,
        )
    ctx["error"] = error_msg
    return templates.TemplateResponse(request=request, name="_edit_drawer.html", context=ctx, status_code=422)


def web_edit_context(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
) -> dict:
    expense = get_expense(db, expense_id, selected_id)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["expense"] = _expense_view(expense)
    ctx["expense_currency_input"] = _currency_input_view(expense.home_currency_code)
    ctx["error"] = None
    ctx["message"] = request.query_params.get("msg")
    ctx["items_error"] = None
    ctx["splits_error"] = None
    ctx["receipt_items"] = _web_item_rows(
        db,
        expense_id,
        selected_id,
        expense.home_currency_code,
    )
    ctx["split_rows"] = _web_split_rows(
        db,
        expense_id,
        selected_id,
        expense.home_currency_code,
    )
    ctx["split_members"] = _web_split_members(db, selected_id)
    ctx["category_options"] = list_ledger_category_options(db, tenant_id=selected_id)
    default_return_to = "pending" if expense.status == "pending" else "confirmed"
    return_to = (request.query_params.get("return_to") or "").strip()
    if return_to not in RETURN_TO_PATHS:
        return_to = default_return_to
    raw_state = {
        "return_month": request.query_params.get("return_month", ""),
        "return_filter": request.query_params.get("return_filter", ""),
        "return_page": request.query_params.get("return_page", ""),
        "return_tag": request.query_params.get("return_tag", ""),
    }
    list_params = return_context_params(return_to, **raw_state)
    edit_params = edit_context_params(return_to, **raw_state)
    ctx.update(
        {
            "edit_return_to": return_to,
            "edit_return_month": edit_params.get("return_month", ""),
            "edit_return_filter": edit_params.get("return_filter", ""),
            "edit_return_page": edit_params.get("return_page", ""),
            "edit_return_tag": edit_params.get("return_tag", ""),
            "edit_back_url": _with_ledger(
                resolve_return_to(return_to, "/web/confirmed"),
                selected_id,
                **list_params,
            ),
            "edit_back_label": (
                "返回收件箱" if return_to == "pending" else "返回账本" if return_to == "confirmed" else "返回疑似重复"
            ),
            "edit_page_title": (
                f"编辑账单 #{expense.id}" if expense.status == "pending" else f"账单详情 #{expense.id}"
            ),
            "edit_page_hint": (
                "核对小票证据与账本字段，保存后再决定是否入账。"
                if expense.status == "pending"
                else "查看小票证据与已入账字段；修改后会返回原来的账本位置。"
            ),
        }
    )
    return ctx


def _web_item_rows(
    db: Session,
    expense_id: int,
    ledger_id: str,
    currency_code: str,
) -> dict:
    """Returns dict carrying both row list and items_sum_status banner state
    (ADR-0035). Template iterates ``rows`` for the table, reads ``status`` /
    ``status_label`` for the warning banner."""
    response = list_expense_items(db, expense_id, ledger_id)
    rows = [
        {
            "kind": item.kind,
            "name": item.name,
            "quantity_text": item.quantity_text or "",
            "unit_price_yuan": _minor_amount_value(item.unit_price_cents, currency_code),
            # discount 行 amount_cents 是负数；UI 显示正数（"3.00"），sign 由
            # kind 表达；form post 时 backend 按 kind=discount 重新翻 sign。
            "amount_yuan": _minor_amount_value(
                abs(item.amount_cents)
                if item.amount_cents is not None and item.kind == "discount"
                else item.amount_cents,
                currency_code,
            ),
            "category": item.category,
            "is_ocr_draft": item.is_ocr_draft,
        }
        for item in response.items
    ]
    rows.extend(
        {
            "kind": "product",
            "name": "",
            "quantity_text": "",
            "unit_price_yuan": "",
            "amount_yuan": "",
            "category": "",
            "is_ocr_draft": False,
        }
        for _ in range(3)
    )
    return {
        "rows": rows,
        "status": response.items_sum_status,
        "mismatch_cents": response.mismatch_cents,
        "mismatch_yuan": _minor_amount_value(response.mismatch_cents, currency_code),
    }


def _web_split_rows(
    db: Session,
    expense_id: int,
    ledger_id: str,
    currency_code: str,
) -> dict:
    response = list_expense_splits(db, expense_id, ledger_id)
    rows = [
        {
            "member_id": split.member_id,
            "account_name": split.account_name,
            "role": split.role,
            "amount_yuan": _minor_amount_value(split.amount_cents, currency_code),
            "note": split.note or "",
            "disabled": split.disabled_at is not None,
        }
        for split in response.splits
    ]
    rows.extend({"member_id": "", "amount_yuan": "", "note": ""} for _ in range(3))
    return {
        "parent_amount_yuan": _minor_amount_value(response.parent_amount_cents, currency_code),
        "total_yuan": _minor_amount_value(response.splits_total_amount_cents, currency_code),
        "mismatch_yuan": _minor_amount_value(response.mismatch_cents, currency_code),
        "rows": rows,
    }


def _web_split_members(db: Session, ledger_id: str) -> list[dict]:
    return list_active_split_members(db, tenant_id=ledger_id)


def item_replace_payload(
    *,
    expected_row_version: int,
    currency_code: str,
    item_name: list[str],
    item_kind: list[str],
    item_quantity: list[str],
    item_unit_price_yuan: list[str],
    item_amount_yuan: list[str],
    item_category: list[str],
) -> ExpenseItemReplaceRequest:
    items: list[ExpenseItemRequest] = []
    max_len = max(
        len(item_name),
        len(item_kind),
        len(item_quantity),
        len(item_unit_price_yuan),
        len(item_amount_yuan),
        len(item_category),
        0,
    )
    for index in range(max_len):
        name = _at(item_name, index).strip()
        kind_raw = _at(item_kind, index).strip() or "product"
        quantity = _at(item_quantity, index).strip()
        unit_raw = _at(item_unit_price_yuan, index)
        amount_raw = _at(item_amount_yuan, index)
        category = _at(item_category, index).strip()
        if not any((name, quantity, unit_raw.strip(), amount_raw.strip(), category)):
            continue
        if not name:
            raise AppError("invalid_request", "明细名称不能为空。", status_code=422)
        unit_price_cents, unit_error = parse_amount_yuan(unit_raw, currency_code=currency_code)
        amount_cents, amount_error = parse_amount_yuan(amount_raw, currency_code=currency_code)
        if unit_error or amount_error:
            raise AppError("invalid_request", "请填写正确的明细金额。", status_code=422)
        # ADR-0035: form post 总是发正数 amount_yuan；discount 行在 backend
        # 翻转 sign。这样模板就不用渲染带 "-" 的 input。
        if kind_raw == "discount" and amount_cents is not None:
            amount_cents = -abs(amount_cents)
        try:
            items.append(
                ExpenseItemRequest(
                    name=name,
                    kind=kind_raw,
                    quantity_text=quantity or None,
                    unit_price_cents=unit_price_cents,
                    amount_cents=amount_cents,
                    category=category or None,
                )
            )
        except ValueError as exc:
            raise AppError("invalid_request", str(exc), status_code=422) from exc
    return ExpenseItemReplaceRequest(
        expected_row_version=expected_row_version,
        items=items,
    )


def split_replace_payload(
    *,
    expected_row_version: int,
    currency_code: str,
    split_member_id: list[str],
    split_amount_yuan: list[str],
    split_note: list[str],
) -> ExpenseSplitReplaceRequest:
    splits: list[ExpenseSplitRequest] = []
    max_len = max(len(split_member_id), len(split_amount_yuan), len(split_note), 0)
    for index in range(max_len):
        member_raw = _at(split_member_id, index).strip()
        amount_raw = _at(split_amount_yuan, index)
        note = _at(split_note, index).strip()
        if not any((member_raw, amount_raw.strip(), note)):
            continue
        if not member_raw or not amount_raw.strip():
            raise AppError("invalid_request", "拆账成员和金额都需要填写。", status_code=422)
        try:
            member_id = int(member_raw)
        except ValueError as exc:
            raise AppError("invalid_request", "请选择正确的家庭成员。", status_code=422) from exc
        amount_cents, amount_error = parse_amount_yuan(amount_raw, currency_code=currency_code)
        if amount_error or amount_cents is None:
            raise AppError("invalid_request", "请填写正确的拆账金额。", status_code=422)
        splits.append(
            ExpenseSplitRequest(
                member_id=member_id,
                amount_cents=amount_cents,
                note=note or None,
            )
        )
    return ExpenseSplitReplaceRequest(
        expected_row_version=expected_row_version,
        splits=splits,
    )


def _at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""
