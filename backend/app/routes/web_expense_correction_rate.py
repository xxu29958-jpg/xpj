"""Native correction recovery adapts a separate command to the existing FX owner."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._web_correction_form import (
    CorrectionFormData,
    correction_form_data,
    correction_form_projection,
    correction_original_fields,
)
from app.routes._web_correction_page import correction_form_error_response
from app.routes._web_rate_recovery import _RATE_FIELDS, submit_recovery_rate
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    preserve_original_ledger_form,
)
from app.services.expense_service import get_expense

router = APIRouter()


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
    result = submit_recovery_rate(db, request, selected, values,
        review_latest=raw.get("fx_review_latest") == "true")
    original = correction_form_projection(form)
    return correction_form_error_response(db, request, options, selected, expense_id,
        error="", status_code=result["status_code"], form_values=original.form_values,
        receipt_item_rows=original.item_form_rows, split_form_rows=original.split_form_rows,
        return_context=form.return_context, rate_recovery={**values, **result})
