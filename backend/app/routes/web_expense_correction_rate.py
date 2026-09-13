"""Native correction recovery adapts a separate command to the existing FX owner."""

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_correction_form import (
    CorrectionFormData,
    correction_form_data,
    correction_form_projection,
    correction_original_fields,
)
from app.routes._web_correction_page import correction_form_error_response
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    preserve_original_ledger_form,
)
from app.schemas import ExchangeRateRequest
from app.services.currency_common import supported_currency_codes
from app.services.exchange_rate_service import list_exchange_rates, set_exchange_rate_idempotently
from app.services.expense_service import get_expense

router = APIRouter()
_RATE_FIELDS = ("currency_code", "home_currency_code", "rate_date", "rate_to_cny",
    "expected_row_version", "idempotency_key")


def correction_rate_context(db: Session, selected: str, details: dict[str, object] | None) -> dict[str, str] | None:
    """Only the attempted fact's explicit server context can open a rate editor."""
    if not details:
        return None
    source, home, raw_date = (details.get(key) for key in _RATE_FIELDS[:3])
    codes = supported_currency_codes()
    if not isinstance(source, str) or not isinstance(home, str) or not isinstance(raw_date, str):
        return None
    if source not in codes or home not in codes or source == home:
        return None
    try:
        rate_date = date.fromisoformat(raw_date)
    except ValueError:
        return None
    if rate_date.isoformat() != raw_date:
        return None
    rates = list_exchange_rates(db, tenant_id=selected, currency_code=source,
        home_currency_code=home, rate_date=rate_date)
    current = rates[0] if rates else None
    return {"currency_code": source, "home_currency_code": home, "rate_date": raw_date,
        "rate_to_cny": str(current.rate_to_cny) if current else "",
        "expected_row_version": str(current.row_version) if current else "0", "idempotency_key": str(uuid4())}


def submit_correction_rate(db: Session, request: Request, selected: str, values: dict[str, str],
    *, review_latest: bool = False) -> dict[str, object]:
    """Rate acceptance never claims, refreshes or executes the original correction."""
    try:
        if review_latest:
            reviewed = correction_rate_context(db, selected, values)
            if reviewed is None:
                raise AppError("invalid_request", status_code=422)
            values.update(expected_row_version=reviewed["expected_row_version"],
                idempotency_key=reviewed["idempotency_key"])
            current = reviewed["rate_to_cny"]
            message = (f"当前汇率：1 {reviewed['currency_code']} = {current} {reviewed['home_currency_code']}。"
                if current else "当前尚未保存这一天的汇率。")
            return {"status_code": 200, "message": message + "原输入已保留，请核对后决定是否保存。"}
        version = values["expected_row_version"]
        if not version.isascii() or not version.isdecimal():
            raise AppError("state_conflict", status_code=409)
        payload = ExchangeRateRequest(**{key: values[key] for key in _RATE_FIELDS[:4]},
            expected_row_version=int(version))
        receipt = set_exchange_rate_idempotently(db, tenant_id=selected,
            actor_account_id=resolve_web_actor_account_id(db, request, selected),
            payload=payload, idempotency_key=values["idempotency_key"])
    except (AppError, ValidationError) as exc:
        db.rollback()
        return {"status_code": exc.status_code if isinstance(exc, AppError) else 422,
            "error": exc.message if isinstance(exc, AppError) else "请检查汇率，原输入已保留。",
            "conflict": isinstance(exc, AppError) and exc.error in {
                "state_conflict", "idempotency_key_required", "idempotency_key_reused"}}
    return {"status_code": 200, "saved": True,
        "message": f"已保存 {receipt.currency_code} → {receipt.home_currency_code} · {receipt.rate_date} 的汇率 {receipt.rate_to_cny}。更正尚未保存，请重新检查并保存更正。"}


@router.post("/expenses/{expense_id}/correction-rate")
def save_correction_rate(
    expense_id: int, request: Request,
    form: CorrectionFormData = Depends(correction_form_data),
    original_fields: dict = Depends(correction_original_fields),
    db: Session = Depends(get_db), _local: None = LocalOnly,
) -> Response:
    raw = original_fields
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, str(raw.get("ledger_id", "")), options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=original_fields, task="补汇率并继续原更正")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    get_expense(db, expense_id, selected)
    values = {key: str(raw.get(f"fx_{key}", "")) for key in _RATE_FIELDS}
    result = submit_correction_rate(db, request, selected, values,
        review_latest=raw.get("fx_review_latest") == "true")
    original = correction_form_projection(form)
    return correction_form_error_response(db, request, options, selected, expense_id,
        error="", status_code=result["status_code"], form_values=original.form_values,
        receipt_item_rows=original.item_form_rows, split_form_rows=original.split_form_rows,
        return_context=form.return_context, rate_recovery={**values, **result})
