"""Presentation of one identity-bound occurrence command; the domain owns the write."""

import json
from urllib.parse import urlencode
from uuid import uuid4

from app.errors import AppError


def occurrence_href(public_id: str, *, ledger_id: str, month: str, payment_month: str,
                    q: str, payment_id: str = "", **extra: str) -> str:
    return f"/web/recurring/{public_id}/occurrence?" + urlencode({
        "ledger_id": ledger_id, "month": month, "payment_month": payment_month,
        "q": q, "payment_id": payment_id, **extra,
    })


def _selected_payment_fields(payments, focused, target):
    choices = payments + ([focused] if focused and focused["eligible"] else [])
    payment = next((row for row in choices if row["public_id"] == target), None)
    if payment is None:
        raise AppError("invalid_request", "原付款不在当前可选账单中，请保留原提交并重新核对。", status_code=409)
    return {"expense_public_id": payment["public_id"], "expected_expense_row_version": str(payment["row_version"]),
        "payment_label": f"{payment['merchant']} · {payment['date']} · {payment['home_currency_code'] or '币种待确认'} {payment['amount']}"}


def occurrence_form(*, request, item, occurrence, scope, navigation, payments, focused,
                    retry=None, prepare=False, can_associate=True):
    base = {**navigation, "public_id": item.public_id, "task_id": f"{item.public_id}:{occurrence.period}",
        "series_label": item.merchant_name, "payment_label": "", "action": "",
        "expense_public_id": "", "expected_expense_row_version": "",
        "expected_row_version": str(occurrence.row_version),
        "expected_series_row_version": str(occurrence.series_row_version),
        "idempotency_key": uuid4().hex, "draft_scope": json.dumps(scope) if scope else ""}
    if retry and not prepare:
        return {**base, **retry}
    if request.query_params.get("resume_occurrence") == "1" and not prepare:
        return {**base, "original_only": True}
    action = retry["action"] if prepare else request.query_params.get("command", "")
    if action not in {"link", "clear"}:
        return None
    if not can_associate:
        raise AppError("invalid_request", "当前不能修改付款关联，请先核对本期状态。", status_code=409)
    target = retry["expense_public_id"] if prepare else request.query_params.get("choose_payment", "")
    if action == "link":
        base.update(_selected_payment_fields(payments, focused, target))
    else:
        base["payment_label"] = "解除本期关联，保留原付款账单"
    base["action"] = action
    if prepare:
        base["prepared_from_key"] = retry["idempotency_key"]
    return base
