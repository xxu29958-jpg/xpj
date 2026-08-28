"""HTTP response owner for Pending bulk commands.

The command routes decide what to mutate; this module owns the matching
progressive-enhancement response, including reject undo tokens shared by the
JSON and no-JS redirect paths.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.routes.web_common import _web_redirect, _with_ledger
from app.services.pending_review_bulk_service import BulkResult

_SUCCESS_VERBS = {
    "reject": "已忽略",
    "confirm_ready": "已确认",
    "keep_duplicate": "已保留",
}

REMOVAL_ACTIONS = frozenset({"reject", "confirm_ready"})


def pending_redirect(selected_id: str, *, filter: str, msg: str) -> RedirectResponse:
    return _web_redirect("/web/pending", selected_id, filter=filter or "all", msg=msg)


def pending_bulk_result_url(
    selected_id: str,
    *,
    action: str,
    filter: str,
    msg: str,
    result: BulkResult,
) -> str:
    url = _with_ledger(
        "/web/pending",
        selected_id,
        filter=filter or "all",
        msg=msg,
        flash_type="success",
    )
    if action != "reject":
        return url
    undo_pairs: list[tuple[str, str]] = []
    for expense_id in result.success_ids:
        row_version = result.undo_row_versions.get(expense_id)
        if row_version is not None:
            undo_pairs.extend((("undo_id", str(expense_id)), ("undo_rv", str(row_version))))
    return f"{url}&{urlencode(undo_pairs)}" if undo_pairs else url


def pending_bulk_result_redirect(
    selected_id: str,
    *,
    action: str,
    filter: str,
    msg: str,
    result: BulkResult,
) -> RedirectResponse:
    return RedirectResponse(
        url=pending_bulk_result_url(
            selected_id,
            action=action,
            filter=filter,
            msg=msg,
            result=result,
        ),
        status_code=303,
    )


def format_bulk_message(action: str, result: BulkResult) -> str:
    parts: list[str] = []
    if result.success_count:
        parts.append(f"{_SUCCESS_VERBS.get(action, '已更新')} {result.success_count} 条")
    parts.extend(f"跳过 {count} 条：{label}" for label, count in result.skipped_reasons.items())
    return "；".join(parts or ["没有可操作的账单。"]) + "。"


def bulk_fragment_json(
    action: str,
    result: BulkResult,
    *,
    selected_id: str,
    filter: str,
) -> JSONResponse:
    message = format_bulk_message(action, result)
    body = {
        "removed_ids": list(result.success_ids),
        "message": message,
        "flash_type": "success",
        "redirect_url": pending_bulk_result_url(
            selected_id,
            action=action,
            filter=filter,
            msg=message,
            result=result,
        ),
    }
    if action == "reject":
        body["undo_items"] = [
            {"id": expense_id, "expected_row_version": result.undo_row_versions[expense_id]}
            for expense_id in result.success_ids
            if expense_id in result.undo_row_versions
        ]
    return JSONResponse(body)


def bulk_error_json(message: str, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        {"removed_ids": [], "message": message, "flash_type": "error"},
        status_code=status_code,
    )


def bulk_no_selection(selected_id: str, *, filter: str, fragment: bool) -> Response:
    message = "请先勾选账单。"
    return bulk_error_json(message) if fragment else pending_redirect(selected_id, filter=filter, msg=message)


def bulk_invalid_snapshot(selected_id: str, *, filter: str, fragment: bool) -> Response:
    message = "页面已过期，请刷新后重新操作。"
    if fragment:
        return bulk_error_json(message, status_code=409)
    return _web_redirect(
        "/web/pending",
        selected_id,
        filter=filter or "all",
        msg=message,
        flash_type="error",
    )
