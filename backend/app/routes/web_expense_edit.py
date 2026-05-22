"""/web expense edit, save, confirm, reject, item, and split routes."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
    ExpenseUpdateRequest,
)
from app.services.expense_service import (
    confirm_expense,
    get_expense,
    reject_expense,
    update_expense,
)
from app.services.expense_split_service import (
    list_active_split_members,
    list_expense_splits,
    replace_expense_splits,
)
from app.services.receipt_item_service import list_expense_items, replace_expense_items

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    fragment: int = 0,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    ctx = _web_edit_context(db, request, options, selected_id, expense_id)
    # ?fragment=1 returns the drawer fragment fetched by desktop.js.
    template_name = "_edit_drawer.html" if fragment else "edit.html"
    return templates.TemplateResponse(request=request, name=template_name, context=ctx)


def _parse_amount_yuan(raw: str) -> tuple[int | None, str | None]:
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


def _parse_original_amount(raw: str) -> tuple[Decimal | None, str | None]:
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


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    original_currency: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    original_amount, error = _parse_original_amount(amount_yuan)

    if error is None:
        payload_args = {
            "merchant": merchant.strip() or None,
            "category": category.strip() or None,
            "note": note.strip() or None,
        }
        if original_amount is not None:
            payload_args["original_currency"] = (
                (original_currency or "").strip().upper() or None
            )
            payload_args["original_amount"] = original_amount
        payload = ExpenseUpdateRequest(**payload_args)
        try:
            update_expense(db, expense_id, selected_id, payload)
        except AppError as exc:
            error = exc.message

    if error is not None:
        ctx = _web_edit_context(db, request, options, selected_id, expense_id)
        ctx["error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)

    return RedirectResponse(
        url=_with_ledger(f"/web/expenses/{expense_id}/edit", selected_id),
        status_code=303,
    )


@router.post("/expenses/{expense_id}/confirm", response_class=HTMLResponse)
def web_confirm(
    expense_id: int,
    request: Request,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        confirm_expense(db, expense_id, selected_id)
    except AppError as exc:
        ctx = _web_edit_context(db, request, options, selected_id, expense_id)
        ctx["error"] = exc.message
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return RedirectResponse(url=_with_ledger("/web/pending", selected_id), status_code=303)


@router.post("/expenses/{expense_id}/items/save", response_class=HTMLResponse)
def web_items_save(
    expense_id: int,
    request: Request,
    item_name: list[str] = Form(default=[]),
    item_quantity: list[str] = Form(default=[]),
    item_unit_price_yuan: list[str] = Form(default=[]),
    item_amount_yuan: list[str] = Form(default=[]),
    item_category: list[str] = Form(default=[]),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseItemReplaceRequest | None = None
    try:
        payload = _item_replace_payload(
            item_name=item_name,
            item_quantity=item_quantity,
            item_unit_price_yuan=item_unit_price_yuan,
            item_amount_yuan=item_amount_yuan,
            item_category=item_category,
        )
    except AppError as exc:
        error = exc.message
    if error is None and payload is not None:
        try:
            replace_expense_items(db, expense_id, selected_id, payload)
        except AppError as exc:
            error = exc.message
    if error is not None:
        ctx = _web_edit_context(db, request, options, selected_id, expense_id)
        ctx["items_error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return RedirectResponse(
        url=_with_ledger(f"/web/expenses/{expense_id}/edit", selected_id, msg="明细已保存。"),
        status_code=303,
    )


@router.post("/expenses/{expense_id}/splits/save", response_class=HTMLResponse)
def web_splits_save(
    expense_id: int,
    request: Request,
    split_member_id: list[str] = Form(default=[]),
    split_amount_yuan: list[str] = Form(default=[]),
    split_note: list[str] = Form(default=[]),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    error: str | None = None
    payload: ExpenseSplitReplaceRequest | None = None
    try:
        payload = _split_replace_payload(
            split_member_id=split_member_id,
            split_amount_yuan=split_amount_yuan,
            split_note=split_note,
        )
    except AppError as exc:
        error = exc.message
    if error is None and payload is not None:
        try:
            replace_expense_splits(
                db,
                expense_id,
                selected_id,
                payload,
                actor_account_id=None,
            )
        except AppError as exc:
            error = exc.message
    if error is not None:
        ctx = _web_edit_context(db, request, options, selected_id, expense_id)
        ctx["splits_error"] = error
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return RedirectResponse(
        url=_with_ledger(f"/web/expenses/{expense_id}/edit", selected_id, msg="拆账已保存。"),
        status_code=303,
    )


@router.post("/expenses/{expense_id}/reject", response_class=HTMLResponse)
def web_reject(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    reject_expense(db, expense_id, selected_id)
    return RedirectResponse(url=_with_ledger("/web/pending", selected_id), status_code=303)


def _web_edit_context(
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
    return ctx


def _web_item_rows(db: Session, expense_id: int, ledger_id: str) -> list[dict]:
    response = list_expense_items(db, expense_id, ledger_id)
    rows = [
        {
            "name": item.name,
            "quantity_text": item.quantity_text or "",
            "unit_price_yuan": _amount_yuan(item.unit_price_cents),
            "amount_yuan": _amount_yuan(item.amount_cents),
            "category": item.category,
            "is_ocr_draft": item.is_ocr_draft,
        }
        for item in response.items
    ]
    rows.extend(
        {
            "name": "",
            "quantity_text": "",
            "unit_price_yuan": "",
            "amount_yuan": "",
            "category": "",
            "is_ocr_draft": False,
        }
        for _ in range(3)
    )
    return rows


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


def _item_replace_payload(
    *,
    item_name: list[str],
    item_quantity: list[str],
    item_unit_price_yuan: list[str],
    item_amount_yuan: list[str],
    item_category: list[str],
) -> ExpenseItemReplaceRequest:
    items: list[ExpenseItemRequest] = []
    max_len = max(
        len(item_name),
        len(item_quantity),
        len(item_unit_price_yuan),
        len(item_amount_yuan),
        len(item_category),
        0,
    )
    for index in range(max_len):
        name = _at(item_name, index).strip()
        quantity = _at(item_quantity, index).strip()
        unit_raw = _at(item_unit_price_yuan, index)
        amount_raw = _at(item_amount_yuan, index)
        category = _at(item_category, index).strip()
        if not any((name, quantity, unit_raw.strip(), amount_raw.strip(), category)):
            continue
        if not name:
            raise AppError("invalid_request", "明细名称不能为空。", status_code=422)
        unit_price_cents, unit_error = _parse_amount_yuan(unit_raw)
        amount_cents, amount_error = _parse_amount_yuan(amount_raw)
        if unit_error or amount_error:
            raise AppError("invalid_request", "请填写正确的明细金额。", status_code=422)
        items.append(
            ExpenseItemRequest(
                name=name,
                quantity_text=quantity or None,
                unit_price_cents=unit_price_cents,
                amount_cents=amount_cents,
                category=category or None,
            )
        )
    return ExpenseItemReplaceRequest(items=items)


def _split_replace_payload(
    *,
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
        amount_cents, amount_error = _parse_amount_yuan(amount_raw)
        if amount_error or amount_cents is None:
            raise AppError("invalid_request", "请填写正确的拆账金额。", status_code=422)
        splits.append(
            ExpenseSplitRequest(
                member_id=member_id,
                amount_cents=amount_cents,
                note=note or None,
            )
        )
    return ExpenseSplitReplaceRequest(splits=splits)


def _at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""
