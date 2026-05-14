"""Web account center — dashboard, confirmed, stats, expense edit.

v0.4-alpha3 slice 2: this module is the slim host for the /web pages that
remain in ``web_app.py``. Pending / bulk live in ``web_pending.py``, rules
live in ``web_rules.py``, helpers and the loopback gate live in
``web_common.py``.

It re-exports ``_require_local`` and ``templates`` because existing tests
import them from this module.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import Account, LedgerMember
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _dashboard_cards,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
    _require_local,  # re-exported for tests
)
from app.schemas import DashboardCardUpdateRequest, DashboardCardsUpdateRequest
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
    ExpenseUpdateRequest,
)
from app.services.dashboard_service import list_dashboard_cards, update_dashboard_cards
from app.services.expense_split_service import list_expense_splits, replace_expense_splits
from app.services.expense_service import (
    confirm_expense,
    ensure_thumbnail_file,
    get_expense,
    list_confirmed,
    reject_expense,
    update_expense,
)
from app.services.file_service import resolve_protected_image
from app.services.receipt_item_service import list_expense_items, replace_expense_items

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def web_root(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["cards"] = _dashboard_cards(db, selected_id)
    return templates.TemplateResponse(request=request, name="dashboard.html", context=ctx)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def web_root_slash(
    ledger_id: str | None = None,
    _local: None = LocalOnly,
) -> RedirectResponse:
    target = "/web"
    if ledger_id:
        target = _with_ledger(target, ledger_id)
    return RedirectResponse(url=target, status_code=303)


def _dashboard_cards_context(db: Session, selected_id: str) -> list[dict]:
    cards = list_dashboard_cards(db, tenant_id=selected_id, surface="web")
    return [
        {
            "key": item.key,
            "title": item.title,
            "visible": item.visible,
            "position": item.position,
        }
        for item in cards.items
    ]


def _dashboard_cards_payload(
    *,
    card_key: list[str],
    card_position: list[int],
    visible_key: list[str],
) -> DashboardCardsUpdateRequest:
    if len(card_key) != len(card_position):
        raise AppError("invalid_request", "卡片顺序数据不完整。", status_code=422)
    visible = set(visible_key)
    seen: set[str] = set()
    cards: list[DashboardCardUpdateRequest] = []
    for key, position in zip(card_key, card_position, strict=True):
        cleaned_key = key.strip()
        if not cleaned_key or cleaned_key in seen:
            raise AppError("invalid_request", "卡片数据不正确。", status_code=422)
        seen.add(cleaned_key)
        cards.append(
            DashboardCardUpdateRequest(
                key=cleaned_key,
                visible=cleaned_key in visible,
                position=position,
            )
        )
    return DashboardCardsUpdateRequest(cards=cards)


@router.get("/dashboard/cards", response_class=HTMLResponse)
def web_dashboard_cards_get(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["dashboard_cards"] = _dashboard_cards_context(db, selected_id)
    ctx["message"] = msg
    return templates.TemplateResponse(request=request, name="dashboard_cards.html", context=ctx)


@router.post("/dashboard/cards/save", response_class=HTMLResponse)
def web_dashboard_cards_save(
    ledger_id: str = Form(default=""),
    card_key: list[str] = Form(default=[]),
    card_position: list[int] = Form(default=[]),
    visible_key: list[str] = Form(default=[]),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    payload = _dashboard_cards_payload(
        card_key=card_key,
        card_position=card_position,
        visible_key=visible_key,
    )
    update_dashboard_cards(db, tenant_id=selected_id, surface="web", payload=payload)
    return RedirectResponse(
        url=_with_ledger("/web/dashboard/cards", selected_id, msg="Dashboard 卡片已保存。"),
        status_code=303,
    )


@router.post("/dashboard/cards/reset", response_class=HTMLResponse)
def web_dashboard_cards_reset(
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    update_dashboard_cards(
        db,
        tenant_id=selected_id,
        surface="web",
        payload=DashboardCardsUpdateRequest(cards=[]),
    )
    return RedirectResponse(
        url=_with_ledger("/web/dashboard/cards", selected_id, msg="已恢复默认卡片。"),
        status_code=303,
    )


@router.get("/confirmed", response_class=HTMLResponse)
def web_confirmed(
    request: Request,
    page: int = 1,
    month: str | None = None,
    tag: str | None = None,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    page_size = 50
    expenses, total = list_confirmed(
        db,
        tenant_id=selected_id,
        page=page,
        page_size=page_size,
        month=month,
        tag=tag,
    )
    items = [_expense_view(e) for e in expenses]
    total_pages = max(1, (total + page_size - 1) // page_size)
    pager_params = {"ledger_id": selected_id}
    if month:
        pager_params["month"] = month
    if tag:
        pager_params["tag"] = tag
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["expenses"] = items
    ctx["page"] = page
    ctx["total_pages"] = total_pages
    ctx["total"] = total
    ctx["month"] = month or ""
    ctx["tag"] = tag or ""
    ctx["pager_query"] = urlencode(pager_params)
    return templates.TemplateResponse(request=request, name="confirmed.html", context=ctx)


# ── Expense edit / save / confirm / reject / image ──────────────────────────


@router.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def web_edit_get(
    expense_id: int,
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options)
    ctx = _web_edit_context(db, request, options, selected_id, expense_id)
    return templates.TemplateResponse(request=request, name="edit.html", context=ctx)


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


@router.post("/expenses/{expense_id}/save", response_class=HTMLResponse)
def web_save(
    expense_id: int,
    request: Request,
    amount_yuan: str = Form(default=""),
    merchant: str = Form(default=""),
    category: str = Form(default=""),
    note: str = Form(default=""),
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    amount_cents, error = _parse_amount_yuan(amount_yuan)

    if error is None:
        payload = ExpenseUpdateRequest(
            amount_cents=amount_cents,
            merchant=merchant.strip() or None,
            category=category.strip() or None,
            note=note.strip() or None,
        )
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
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
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
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
    expense_id: int,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
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
    rows = db.execute(
        select(LedgerMember, Account)
        .join(Account, Account.id == LedgerMember.account_id)
        .where(LedgerMember.ledger_id == ledger_id)
        .where(LedgerMember.disabled_at.is_(None))
        .order_by(LedgerMember.id.asc())
    ).all()
    return [
        {
            "member_id": member.id,
            "account_name": account.display_name,
            "role": member.role,
        }
        for member, account in rows
    ]


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


@router.get("/expenses/{expense_id}/image", include_in_schema=False)
def web_image(
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id)
    expense = get_expense(db, expense_id, selected_id)
    path, media_type = resolve_protected_image(expense.image_path, selected_id)
    return FileResponse(path=path, media_type=media_type)


@router.get("/expenses/{expense_id}/thumbnail", include_in_schema=False)
def web_thumbnail(
    expense_id: int,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> FileResponse:
    selected_id = _resolve_selected_ledger_id(db, ledger_id)
    path, media_type = ensure_thumbnail_file(db, expense_id, selected_id)
    return FileResponse(path=path, media_type=media_type)
