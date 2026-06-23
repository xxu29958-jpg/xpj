"""/web/pending + /web/review/bulk routes.

Split from ``web_app.py`` in v0.4-alpha3 slice 2 to keep per-page routing
modules under the 280-line budget. Business logic lives in
``app.services`` — this module is responsible for HTTP wiring only.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
    _with_ledger,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.expense_service import (
    fetch_expense_row_version_in_status,
    list_pending,
    undo_reject_expense,
)
from app.services.pending_review_bulk_service import (
    ALLOWED_ACTIONS,
    BulkResult,
    apply_review_bulk,
)

router = APIRouter(prefix="/web", tags=["web"])


_PENDING_FILTERS = {
    "all",
    "missing_amount",
    "missing_merchant",
    "missing_category",
    "duplicate",
    "ready",
}


def _needs_category(view: dict) -> bool:
    # 分类为空，或仍是默认占位「未分类」时视为待分类。
    # 「其他」是用户可主动选择的合法分类，不能把它算进缺分类，
    # 否则旧账单会被错误排除在 ready 筛选外。
    cat = (view.get("category") or "").strip()
    return cat == "" or cat == "未分类"


def _matches_filter(view: dict, filter_key: str) -> bool:
    if filter_key == "all":
        return True
    if filter_key == "missing_amount":
        return view["needs_amount"]
    if filter_key == "missing_merchant":
        return view["needs_merchant"]
    if filter_key == "missing_category":
        return _needs_category(view)
    if filter_key == "duplicate":
        return view["is_duplicate"]
    if filter_key == "ready":
        return (
            not view["needs_amount"]
            and not view["needs_merchant"]
            and not _needs_category(view)
            and not view["is_duplicate"]
        )
    return True


def _resolve_single_undo(
    db: Session, *, selected_id: str, undo: str | None
) -> tuple[int | None, int | None]:
    # ADR-0038/0041: a stale or cross-ledger query param only disables the
    # affordance. The POST route remains the source of truth.
    if not undo or not undo.isdigit():
        return None, None
    candidate = int(undo)
    row_version = fetch_expense_row_version_in_status(
        db, expense_id=candidate, tenant_id=selected_id, status="rejected"
    )
    if row_version is None:
        return None, None
    return candidate, row_version


def _resolve_batch_undo_items(
    db: Session,
    *,
    selected_id: str,
    undo_ids: list[int],
    undo_tokens: list[str],
) -> list[dict[str, int]]:
    if not undo_ids or len(undo_ids) != len(undo_tokens):
        return []

    items: list[dict[str, int]] = []
    for expense_id, raw_token in zip(undo_ids, undo_tokens, strict=True):
        parsed = parse_form_row_version_token(raw_token)
        if parsed is None:
            continue
        row_version = fetch_expense_row_version_in_status(
            db, expense_id=expense_id, tenant_id=selected_id, status="rejected"
        )
        if row_version == parsed:
            items.append({"id": expense_id, "row_version": parsed})
    return items


@router.get("/pending", response_class=HTMLResponse)
def web_pending(
    request: Request,
    ledger_id: str | None = None,
    filter: str | None = None,
    msg: str | None = None,
    undo: str | None = None,
    undo_id: list[int] = Query(default=[]),
    undo_rv: list[str] = Query(default=[]),
    flash_type: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    raw_items = [_expense_view(e) for e in list_pending(db, selected_id)]

    filter_key = (filter or "all").strip().lower()
    if filter_key not in _PENDING_FILTERS:
        filter_key = "all"

    items = [it for it in raw_items if _matches_filter(it, filter_key)]
    pending_total = len(raw_items)
    suspected_total = sum(1 for it in raw_items if it["is_duplicate"])
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="待确认",
        sidebar_counts=(pending_total, suspected_total),
    )
    ctx["expenses"] = items
    ctx["pending_count"] = pending_total
    ctx["filtered_count"] = len(items)
    ctx["filter"] = filter_key
    ctx["flash_message"] = msg or ""
    # ADR-0038 undo: success (green) vs error (red) flash. Only the two canonical
    # values from the redirect map onto a banner style; anything else falls back
    # to the legacy info style so the param can't drive arbitrary CSS classes.
    ctx["flash_type"] = flash_type if flash_type in ("success", "error") else ""
    # ADR-0038 undo: just-rejected expense_id; pending.html renders a 5s 撤销
    # banner that POSTs to /web/expenses/{undo_expense_id}/undo. ``undo`` is a
    # plain int string from the redirect query — invalid values just disable the
    # banner (no error surface, since this is a soft affordance not a contract).
    # Ownership check: the row must actually be in ``rejected`` state under the
    # currently-selected ledger before we expose the undo affordance. A stale
    # ``?undo=N`` in the URL (cross-ledger via the ledger selector, or a
    # bookmark replay) won't render a misleading "可撤销" banner — the route
    # itself is the source of truth (atomic UPDATE WHERE tenant_id, status), but
    # the page also stops lying.
    undo_expense_id, undo_expected_row_version = _resolve_single_undo(
        db, selected_id=selected_id, undo=undo
    )
    ctx["undo_expense_id"] = undo_expense_id
    ctx["undo_expected_row_version"] = undo_expected_row_version
    ctx["undo_items"] = _resolve_batch_undo_items(
        db, selected_id=selected_id, undo_ids=undo_id, undo_tokens=undo_rv
    )
    ctx["needs_amount_count"] = sum(1 for it in raw_items if it["needs_amount"])
    ctx["needs_merchant_count"] = sum(1 for it in raw_items if it["needs_merchant"])
    ctx["needs_category_count"] = sum(1 for it in raw_items if _needs_category(it))
    ctx["suspected_duplicate_count"] = suspected_total
    ctx["ready_count"] = sum(
        1
        for it in raw_items
        if not it["needs_amount"]
        and not it["needs_merchant"]
        and not _needs_category(it)
        and not it["is_duplicate"]
    )
    return templates.TemplateResponse(request=request, name="pending.html", context=ctx)


def _pending_redirect(selected_id: str, *, filter: str, msg: str) -> RedirectResponse:
    return _web_redirect("/web/pending", selected_id, filter=filter or "all", msg=msg)


def _pending_redirect_with_batch_undo(
    selected_id: str, *, filter: str, msg: str, result: BulkResult
) -> RedirectResponse:
    url = _with_ledger(
        "/web/pending",
        selected_id,
        filter=filter or "all",
        msg=msg,
        flash_type="success",
    )
    undo_pairs: list[tuple[str, str]] = []
    for expense_id in result.success_ids:
        row_version = result.undo_row_versions.get(expense_id)
        if row_version is None:
            continue
        undo_pairs.append(("undo_id", str(expense_id)))
        undo_pairs.append(("undo_rv", str(row_version)))
    if undo_pairs:
        url = f"{url}&{urlencode(undo_pairs)}"
    return RedirectResponse(url=url, status_code=303)


_SUCCESS_VERBS = {
    "reject": "已忽略",
    "confirm_ready": "已确认",
    "keep_duplicate": "已保留",
}


def _format_bulk_message(action: str, result: BulkResult) -> str:
    parts: list[str] = []
    if result.success_count:
        verb = _SUCCESS_VERBS.get(action, "已更新")
        parts.append(f"{verb} {result.success_count} 条")
    for label, count in result.skipped_reasons.items():
        parts.append(f"跳过 {count} 条：{label}")
    if not parts:
        parts.append("没有可操作的账单。")
    return "；".join(parts) + "。"


# issue #64 W3: only the removal-type bulk actions speak the fetch+partial JSON
# contract — they pop rows out of the pending list, which the /web bulk bar can
# splice from the DOM without a full reload. set_category / set_merchant /
# keep_duplicate mutate a row in place (it stays visible), so they keep the
# full-page redirect and are unaffected by ``fragment``.
_REMOVAL_ACTIONS = frozenset({"reject", "confirm_ready"})


def _bulk_fragment_json(action: str, result: BulkResult) -> JSONResponse:
    """fetch+partial success body: which rows the server actually removed plus
    the same summary the redirect path flashes. ``removed_ids`` is authoritative
    — confirm_ready skips non-ready rows, so the client must not assume every
    selected row left the queue."""
    body = {
        "removed_ids": list(result.success_ids),
        "message": _format_bulk_message(action, result),
        "flash_type": "success",
    }
    if action == "reject":
        body["undo_items"] = [
            {
                "id": expense_id,
                "expected_row_version": result.undo_row_versions[expense_id],
            }
            for expense_id in result.success_ids
            if expense_id in result.undo_row_versions
        ]
    return JSONResponse(body)


def _bulk_error_json(message: str) -> JSONResponse:
    return JSONResponse({"removed_ids": [], "message": message, "flash_type": "error"})


def _bulk_no_selection(
    selected_id: str, *, filter: str, fragment: bool
) -> Response:
    msg = "请先勾选账单。"
    if fragment:
        return _bulk_error_json(msg)
    return _pending_redirect(selected_id, filter=filter, msg=msg)


def _reject_pending_rows(
    db: Session,
    *,
    selected_id: str,
    expense_ids: list[int],
) -> BulkResult:
    return apply_review_bulk(
        db, tenant_id=selected_id, action="reject", expense_ids=expense_ids
    )


@router.post("/pending/batch-reject", response_class=HTMLResponse)
def web_pending_batch_reject(
    request: Request,
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    filter: str = Form(default="all"),
    # issue #64 W3: fetch+partial path. ``fragment=1`` (only the JS bulk bar adds
    # it) swaps the full-page redirect for a JSON {removed_ids, message,
    # flash_type} so the client splices rows without reloading. No-JS POSTs omit
    # it and keep the redirect — progressive enhancement, mirrors the drawer.
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)

    if not expense_ids:
        return _bulk_no_selection(selected_id, filter=filter, fragment=bool(fragment))

    result = _reject_pending_rows(db, selected_id=selected_id, expense_ids=expense_ids)
    if fragment:
        return _bulk_fragment_json("reject", result)
    return _pending_redirect_with_batch_undo(
        selected_id, filter=filter, msg=_format_bulk_message("reject", result), result=result
    )


@router.post("/pending/batch-undo", response_class=HTMLResponse)
def web_pending_batch_undo(
    request: Request,
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    expected_row_version: list[str] = Form(default=[]),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    if not expense_ids:
        return _web_redirect(
            "/web/pending", selected_id, msg="没有可撤销的账单。", flash_type="error"
        )
    if len(expense_ids) != len(expected_row_version):
        return _web_redirect(
            "/web/pending",
            selected_id,
            msg="页面已过期，请刷新后重新操作。",
            flash_type="error",
        )

    restored = 0
    skipped = 0
    for expense_id, raw_token in zip(expense_ids, expected_row_version, strict=True):
        parsed = parse_form_row_version_token(raw_token)
        if parsed is None:
            skipped += 1
            continue
        try:
            undo_reject_expense(db, expense_id, selected_id, parsed)
            restored += 1
        except AppError:
            skipped += 1

    parts: list[str] = []
    if restored:
        parts.append(f"已撤销 {restored} 条")
    if skipped:
        parts.append(f"跳过 {skipped} 条：无法撤销")
    if not parts:
        parts.append("没有可撤销的账单")
    return _web_redirect(
        "/web/pending",
        selected_id,
        msg="；".join(parts) + "。",
        flash_type="success" if restored else "error",
    )


@router.post("/review/bulk", response_class=HTMLResponse)
def web_review_bulk(
    request: Request,
    action: str = Form(...),
    ledger_id: str = Form(default=""),
    expense_ids: list[int] = Form(default=[]),
    category: str = Form(default=""),
    merchant: str = Form(default=""),
    filter: str = Form(default="all"),
    # issue #64 W3: see web_pending_batch_reject. Only honoured for the removal
    # action (confirm_ready); set_category/set_merchant/keep_duplicate ignore it
    # and stay on the redirect, since they don't pop rows from the list.
    fragment: int = Form(default=0),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)

    action_clean = (action or "").strip()
    if action_clean not in ALLOWED_ACTIONS:
        raise AppError("invalid_request", status_code=422)

    fragment_removal = bool(fragment) and action_clean in _REMOVAL_ACTIONS

    if not expense_ids:
        return _bulk_no_selection(selected_id, filter=filter, fragment=fragment_removal)

    try:
        result = apply_review_bulk(
            db,
            tenant_id=selected_id,
            action=action_clean,
            expense_ids=expense_ids,
            category=category,
            merchant=merchant,
        )
    except AppError as exc:
        if exc.status_code == 422 and exc.error == "invalid_request":
            if fragment_removal:
                return _bulk_error_json(exc.message)
            return _pending_redirect(selected_id, filter=filter, msg=exc.message)
        raise

    if fragment_removal:
        return _bulk_fragment_json(action_clean, result)
    return _pending_redirect(
        selected_id,
        filter=filter,
        msg=_format_bulk_message(action_clean, result),
    )
