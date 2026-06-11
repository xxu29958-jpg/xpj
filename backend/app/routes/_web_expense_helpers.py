"""Shared helpers for ``/web/expenses/{id}/...`` route modules.

Split out from ``web_expense_edit.py`` so the expense-main / items / splits
route files don't have to import from each other.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes.web_common import _amount_yuan, _base_ctx, _expense_view, _web_redirect, templates
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


def parse_amount_yuan(raw: str) -> tuple[int | None, str | None]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        d = Decimal(cleaned)
    except InvalidOperation:
        return None, "请填写正确的金额，例如 12.34。"
    if d < 0:
        return None, "金额不能为负数。"
    cents = int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cents, None


def parse_original_amount(raw: str) -> tuple[Decimal | None, str | None]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None, None
    try:
        d = Decimal(cleaned)
    except InvalidOperation:
        return None, "请填写正确的金额，例如 12.34。"
    if d < 0:
        return None, "金额不能为负数。"
    return d, None


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
    ctx["error"] = None
    ctx["message"] = request.query_params.get("msg")
    ctx["items_error"] = None
    ctx["splits_error"] = None
    ctx["receipt_items"] = _web_item_rows(db, expense_id, selected_id)
    ctx["split_rows"] = _web_split_rows(db, expense_id, selected_id)
    ctx["split_members"] = _web_split_members(db, selected_id)
    ctx["category_options"] = list_ledger_category_options(db, tenant_id=selected_id)
    return ctx


def _web_item_rows(db: Session, expense_id: int, ledger_id: str) -> dict:
    """Returns dict carrying both row list and items_sum_status banner state
    (ADR-0035). Template iterates ``rows`` for the table, reads ``status`` /
    ``status_label`` for the warning banner."""
    response = list_expense_items(db, expense_id, ledger_id)
    rows = [
        {
            "kind": item.kind,
            "name": item.name,
            "quantity_text": item.quantity_text or "",
            "unit_price_yuan": _amount_yuan(item.unit_price_cents),
            # discount 行 amount_cents 是负数；UI 显示正数（"3.00"），sign 由
            # kind 表达；form post 时 backend 按 kind=discount 重新翻 sign。
            "amount_yuan": _amount_yuan(
                abs(item.amount_cents) if item.amount_cents is not None and item.kind == "discount"
                else item.amount_cents
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
        "mismatch_yuan": _amount_yuan(response.mismatch_cents),
    }


def _web_split_rows(db: Session, expense_id: int, ledger_id: str) -> dict:
    response = list_expense_splits(db, expense_id, ledger_id)
    rows = [
        {
            "member_id": split.member_id,
            "account_name": split.account_name,
            "role": split.role,
            "amount_yuan": _amount_yuan(split.amount_cents),
            "note": split.note or "",
            "disabled": split.disabled_at is not None,
        }
        for split in response.splits
    ]
    rows.extend({"member_id": "", "amount_yuan": "", "note": ""} for _ in range(3))
    return {
        "parent_amount_yuan": _amount_yuan(response.parent_amount_cents),
        "total_yuan": _amount_yuan(response.splits_total_amount_cents),
        "mismatch_yuan": _amount_yuan(response.mismatch_cents),
        "rows": rows,
    }


def _web_split_members(db: Session, ledger_id: str) -> list[dict]:
    return list_active_split_members(db, tenant_id=ledger_id)


def item_replace_payload(
    *,
    expected_row_version: int,
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
        unit_price_cents, unit_error = parse_amount_yuan(unit_raw)
        amount_cents, amount_error = parse_amount_yuan(amount_raw)
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
        amount_cents, amount_error = parse_amount_yuan(amount_raw)
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
