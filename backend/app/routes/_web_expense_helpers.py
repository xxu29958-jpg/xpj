"""Shared helpers for ``/web/expenses/{id}/...`` route modules.

Split out from ``web_expense_edit.py`` so the expense-main / items / splits
route files don't have to import from each other.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_return_context import (
    edit_context_params,
    resolve_return_to,
    return_context_params,
    return_href,
)
from app.routes.web_common import (
    _amount_yuan,
    _base_ctx,
    _currency_input_view,
    _expense_view,
    _web_redirect,
    templates,
)
from app.services.category_service import list_ledger_category_options
from app.services.expense_service import get_expense
from app.services.expense_split_service import (
    list_active_split_members,
    list_expense_splits,
)
from app.services.receipt_item_service import list_expense_items


def _edit_page_or_flash_redirect(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
    fallback_path: str,
    error_key: str = "error",
    status_code: int = 422,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
    receipt_item_rows: list[dict] | None = None,
    split_form_rows: list[dict] | None = None,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
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
        ctx = web_edit_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            form_values=form_values,
            field_errors=field_errors,
            conflict=conflict,
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    except AppError as exc:
        return _web_redirect(
            resolve_return_to(return_to, fallback_path),
            selected_id,
            msg=exc.message,
            flash_type="error",
            **return_context_params(
                return_to,
                return_month=return_month,
                return_filter=return_filter,
                return_page=return_page,
                return_tag=return_tag,
                return_query=return_query,
            ),
        )
    ctx[error_key] = error_msg
    if receipt_item_rows is not None:
        ctx["receipt_items"]["rows"] = receipt_item_rows
    if split_form_rows is not None:
        ctx["split_rows"]["rows"] = split_form_rows
    return templates.TemplateResponse(
        request=request,
        name="edit.html",
        context=ctx,
        status_code=status_code,
    )


def drawer_fragment_ok(action: str) -> HTMLResponse:
    """批10: minimal 200 body for a successful fetch-mutation from the drawer.

    desktop drawer.js only reads ``res.ok`` for confirm/忽略 (it then removes
    the row + opens the next drawer) and re-fetches the row fragment after a
    save, so the success body just needs to be a tiny, non-JSON marker — never
    the bare-JSON the global handler would emit. ``action`` is echoed in a data
    attribute purely so the response is self-describing in logs / manual curls.
    """
    return HTMLResponse(f'<div data-drawer-ok="{action}"></div>')


def drawer_fragment_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
    *,
    status_code: int = 422,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
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
        ctx = web_edit_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            form_values=form_values,
            field_errors=field_errors,
            conflict=conflict,
            return_to="pending",
        )
    except AppError as exc:
        return HTMLResponse(
            f'<div class="empty-cell">{exc.message}</div>',
            status_code=exc.status_code,
        )
    ctx["error"] = error_msg
    return templates.TemplateResponse(
        request=request,
        name="_edit_drawer.html",
        context=ctx,
        status_code=status_code,
    )


def _overlay_submitted_expense_values(
    expense_view: dict,
    form_values: dict[str, str] | None,
) -> None:
    if not form_values:
        return
    view_keys = {
        "expected_row_version": "row_version",
        "amount_yuan": "original_amount_value",
        "merchant": "merchant",
        "category": "category_input",
        "note": "note",
        "tags": "tags",
        "expense_time": "expense_time_local",
    }
    for form_key, view_key in view_keys.items():
        if form_key in form_values:
            expense_view[view_key] = form_values[form_key]


def web_edit_context(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
) -> dict:
    expense = get_expense(db, expense_id, selected_id)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    expense_view = _expense_view(
        expense,
        presentation_currency_code=ctx["home_currency_code"],
    )
    current_expense_view = expense_view.copy()
    _overlay_submitted_expense_values(expense_view, form_values)
    ctx["expense"] = expense_view
    ctx["conflict_current"] = current_expense_view if conflict else None
    ctx["confirm_idempotency_key"] = (
        (form_values or {}).get("idempotency_key") or str(uuid4())
    )
    ctx["error"] = None
    ctx["message"] = request.query_params.get("msg")
    ctx["items_error"] = None
    ctx["splits_error"] = None
    ctx["field_errors"] = field_errors or {}
    ctx["edit_return_fields"] = edit_context_params(
        return_to,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
    )
    ctx["edit_return_href"] = return_href(
        return_to,
        ledger_id=selected_id,
        default_path="/web/pending",
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
    )
    record_currency = expense.home_currency_code or ctx["home_currency_code"]
    ctx["currency_input"] = _currency_input_view(record_currency)
    ctx["expense_currency_input"] = _currency_input_view(
        expense.original_currency_code or record_currency
    )
    ctx["receipt_items"] = _web_item_rows(
        db,
        expense_id,
        selected_id,
        currency_code=record_currency,
    )
    ctx["split_rows"] = _web_split_rows(
        db,
        expense_id,
        selected_id,
        currency_code=record_currency,
    )
    ctx["split_members"] = _web_split_members(db, selected_id)
    ctx["category_options"] = list_ledger_category_options(db, tenant_id=selected_id)
    return ctx


def _web_item_rows(
    db: Session,
    expense_id: int,
    ledger_id: str,
    *,
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
            "unit_price_yuan": _amount_yuan(item.unit_price_cents, currency_code),
            # discount 行 amount_cents 是负数；UI 显示正数（"3.00"），sign 由
            # kind 表达；form post 时 backend 按 kind=discount 重新翻 sign。
            "amount_yuan": _amount_yuan(
                abs(item.amount_cents) if item.amount_cents is not None and item.kind == "discount"
                else item.amount_cents,
                currency_code,
            ),
            "category": item.category,
            "is_ocr_draft": item.is_ocr_draft,
            "errors": {},
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
            "errors": {},
        }
        for _ in range(3)
    )
    return {
        "rows": rows,
        "status": response.items_sum_status,
        "mismatch_cents": response.mismatch_cents,
        "mismatch_yuan": _amount_yuan(response.mismatch_cents, currency_code),
    }


def _web_split_rows(
    db: Session,
    expense_id: int,
    ledger_id: str,
    *,
    currency_code: str,
) -> dict:
    response = list_expense_splits(db, expense_id, ledger_id)
    rows = [
        {
            "member_id": split.member_id,
            "account_name": split.account_name,
            "role": split.role,
            "amount_yuan": _amount_yuan(split.amount_cents, currency_code),
            "note": split.note or "",
            "disabled": split.disabled_at is not None,
            "errors": {},
        }
        for split in response.splits
    ]
    rows.extend(
        {
            "member_id": "",
            "amount_yuan": "",
            "note": "",
            "disabled": False,
            "errors": {},
        }
        for _ in range(3)
    )
    return {
        "parent_amount_yuan": _amount_yuan(response.parent_amount_cents, currency_code),
        "total_yuan": _amount_yuan(response.splits_total_amount_cents, currency_code),
        "mismatch_yuan": _amount_yuan(response.mismatch_cents, currency_code),
        "has_mismatch": response.mismatch_cents != 0,
        "rows": rows,
    }


def _web_split_members(db: Session, ledger_id: str) -> list[dict]:
    return list_active_split_members(db, tenant_id=ledger_id)


def confirm_reject_error(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    error_msg: str,
    fragment: int,
    *,
    status_code: int,
    return_to: str = "",
    return_month: str = "",
    return_filter: str = "",
    return_page: str = "",
    return_tag: str = "",
    return_query: str = "",
    form_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    conflict: bool = False,
) -> Response:
    if fragment:
        return drawer_fragment_error(
            db,
            request,
            options,
            selected_id,
            expense_id,
            error_msg,
            status_code=status_code,
            form_values=form_values,
            field_errors=field_errors,
            conflict=conflict,
        )
    return _edit_page_or_flash_redirect(
        db,
        request,
        options,
        selected_id,
        expense_id,
        error_msg,
        "/web/pending",
        status_code=status_code,
        form_values=form_values,
        field_errors=field_errors,
        conflict=conflict,
        return_to=return_to,
        return_month=return_month,
        return_filter=return_filter,
        return_page=return_page,
        return_tag=return_tag,
        return_query=return_query,
    )


def web_save_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    error: str | None,
    error_status: int,
    form_values: dict[str, str] | None,
    field_errors: dict[str, str] | None,
    conflict: bool,
    fragment: int,
    return_to: str,
    return_month: str,
    return_filter: str,
    return_page: str,
    return_tag: str,
    return_query: str,
) -> Response:
    if error is not None:
        if fragment:
            return drawer_fragment_error(
                db,
                request,
                options,
                selected_id,
                expense_id,
                error,
                status_code=error_status,
                form_values=form_values,
                field_errors=field_errors,
                conflict=conflict,
            )
        return _edit_page_or_flash_redirect(
            db,
            request,
            options,
            selected_id,
            expense_id,
            error,
            "/web/confirmed",
            status_code=error_status,
            form_values=form_values,
            field_errors=field_errors,
            conflict=conflict,
            return_to=return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        )
    if fragment:
        return drawer_fragment_ok("save")
    return _web_redirect(
        resolve_return_to(return_to, f"/web/expenses/{expense_id}/edit"),
        selected_id,
        **return_context_params(
            return_to,
            return_month=return_month,
            return_filter=return_filter,
            return_page=return_page,
            return_tag=return_tag,
            return_query=return_query,
        ),
    )
