"""Complete or correct payment sources without creating another purchase."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
)
from app.routes._web_funding import funding_options, parse_funding, review_funding_values
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _web_redirect,
    templates,
)
from app.routes.web_funds import _scope
from app.schemas.funds import ExpenseFundingCommand, ExpenseFundingView
from app.services.currency_common import minor_amount_label, minor_amount_value
from app.services.expense_funding_command import expense_funding_view, save_expense_funding
from app.services.funds_commands import claim_funds, funds_request_is_unpublished

router = APIRouter(prefix="/web/expenses", tags=["web"])


def _render(request, db, expense_id, ledger_id, *, values=None, result="", error=None, status=200, prepared_from=""):
    options, ledger, auth = _scope(request, db, ledger_id)
    funding = expense_funding_view(db, ledger_id=ledger, actor_account_id=auth.account_id, expense_id=expense_id)
    rows = [{"component_id": part.component_id, "account_public_id": part.account_public_id,
        "account_row_version": part.account_row_version, "account_name": part.account_name, "account_currency": part.currency_code,
        "expense_currency": funding.currency_code, "expense_amount": minor_amount_value(part.expense_amount_minor, funding.currency_code),
        "account_amount": minor_amount_value(part.account_amount_minor, part.currency_code), "included_in_opening": part.included_in_opening}
        for part in funding.parts if part.account_public_id is not None]
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=ledger, page_title="付款来源")
    ctx.update(funding=funding, funding_accounts=funding_options(db, auth), money=minor_amount_label,
        funding_scope=browser_draft_scope(db, request), funding_result=result, funding_prepared_from=prepared_from, error=error,
        funding_can_write=auth.role in {"owner", "member"} and funding.can_edit,
        values=values if values is not None else {"expense_id": str(expense_id), "currency_code": funding.currency_code,
            "expected_row_version": str(funding.expense_row_version), "funding_json": json.dumps(rows, ensure_ascii=False),
            "reason": "补充付款来源" if not funding.parts else "更正付款来源", "idempotency_key": str(uuid4())})
    return templates.TemplateResponse(request=request, name="expense_funding.html", context=ctx, status_code=status,
        headers={"Cache-Control": "no-store"})


@router.get("/{expense_id}/funding")
def read_funding(request: Request, expense_id: int, ledger_id: str = "", _local: None = LocalOnly, db: Session = Depends(get_db)):
    return _render(request, db, expense_id, ledger_id)


@router.post("/{expense_id}/funding")
async def write_funding(request: Request, expense_id: int, _local: None = LocalOnly, db: Session = Depends(get_db)):
    values = dict(await request.form())
    ledger = str(values.get("ledger_id", ""))
    href = f"/web/expenses/{expense_id}/edit?ledger_id={ledger}"
    try:
        auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
        _require_selected_ledger_write(_list_ledger_options(db), ledger)
        payload = ExpenseFundingCommand(expected_row_version=values["expected_row_version"], reason=values["reason"],
            parts=parse_funding(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id,
                raw=values["funding_json"], currency_code=values["currency_code"]))
        key = values["idempotency_key"]
        if values.get("review_latest"):
            claim = claim_funds(db, auth, payload, key, "save_expense_funding", str(expense_id))
            if claim is None:
                original = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == ledger,
                    ApiIdempotencyKey.idempotency_key == key))
                receipt = ExpenseFundingView.model_validate(original.response_body)
            else:
                db.rollback()
                current = expense_funding_view(db, ledger_id=ledger, actor_account_id=auth.account_id, expense_id=expense_id)
                if current.currency_code != values["currency_code"]:
                    raise AppError("state_conflict", "消费币种已变更，请按原输入重新核对付款组成。", status_code=409)
                values.update(expected_row_version=str(current.expense_row_version),
                    funding_json=review_funding_values(db, auth, values["funding_json"], values["currency_code"]),
                    idempotency_key=str(uuid4()))
                return _render(request, db, expense_id, ledger, values=values, result="prepared", prepared_from=key)
        else:
            receipt = save_expense_funding(db, auth=auth, expense_id=expense_id, payload=payload, key=key)
        return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=key,
            receipt=receipt, next_href=href) or _web_redirect(f"/web/expenses/{expense_id}/edit", ledger)
    except (AppError, ValidationError, ValueError, KeyError) as exc:
        db.rollback()
        error = exc if isinstance(exc, AppError) else AppError("invalid_request", "请核对付款组成和更正原因；原输入已保留。", status_code=422)
        if values.get("review_latest") and error.error in {"invalid_request", "currency_not_supported", "amount_invalid"}:
            auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
            if funds_request_is_unpublished(db, auth, values.get("idempotency_key", "")):
                return _render(request, db, expense_id, ledger,
                    values={**values, "idempotency_key": str(uuid4())}, result="prepared",
                    error=error.message + " 原提交未记账，请修改保留的输入后确认。",
                    prepared_from=values.get("idempotency_key", ""))
        return draft_error_response(request, error) or _render(request, db, expense_id, ledger, values=values,
            error=error.message, result=draft_refusal_result(error), status=error.status_code)
