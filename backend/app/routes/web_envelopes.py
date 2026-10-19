"""Native cash-purpose forms backed by the common browser draft and command owners."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas.envelopes import EnvelopeReceipt, EnvelopeSave, EnvelopesView
from app.services.currency_common import major_amount_to_minor, minor_amount_label, minor_amount_value
from app.services.envelope_commands import review_envelopes, save_envelopes
from app.services.envelope_query import envelope_history, envelopes_view
from app.services.ledger_calendar_service import current_ledger_date
from app.services.spending_contract_service import clean_month

router = APIRouter(prefix="/web/envelopes", tags=["web"])


def _values(view: EnvelopesView) -> dict[str, str]:
    return {"ledger_id": view.ledger_id, "month": view.month, "home_currency_code": view.home_currency_code,
        "expected_row_version": str(view.row_version), "idempotency_key": str(uuid4()), "note": "调整用途分配",
        "account_ids_json": json.dumps([row.public_id for row in view.accounts if row.selected]),
        "account_versions_json": json.dumps({row.public_id: row.row_version for row in view.accounts}),
        "allocations_json": json.dumps({row.purpose: minor_amount_value(row.allocated_minor,
            view.home_currency_code) for row in view.purposes}, ensure_ascii=False)}


def _render(request: Request, db: Session, *, ledger_id: str, month: str, values: dict | None = None,
             error: str | None = None, result: str = "", prepared_from: str = "", status: int = 200,
             before_version: int | None = None) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None or auth.ledger_id != selected:
        raise AppError("invalid_token", "请先登录当前账本。", status_code=401)
    month = clean_month(month or current_ledger_date(db, ledger_id=selected).strftime("%Y-%m"))
    view = envelopes_view(db, tenant_id=selected, actor_account_id=auth.account_id, month=month)
    values = _values(view) if values is None else values
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="信封分配")
    ctx.update(envelopes=view, values=values, envelope_scope=browser_draft_scope(db, request),
        envelope_result=result, envelope_prepared_from=prepared_from, error=error,
        allocations=_retained_json(values.get("allocations_json", ""), dict),
        selected_sources=_retained_json(values.get("account_ids_json", ""), list),
        money=minor_amount_label, money_value=minor_amount_value, envelope_can_write=auth.role in {"owner", "member"},
        history=envelope_history(db, tenant_id=selected, actor_account_id=auth.account_id,
            before_version=before_version), before_version=before_version)
    return templates.TemplateResponse(request=request, name="envelopes.html", context=ctx,
                                      status_code=status, headers={"Cache-Control": "no-store"})


@router.get("")
def web_envelopes(request: Request, ledger_id: str = "", month: str = "",
                  before_version: int | None = Query(default=None, ge=1),
                  _local: None = LocalOnly, db: Session = Depends(get_db)) -> HTMLResponse:
    return _render(request, db, ledger_id=ledger_id, month=month, before_version=before_version)


def _retained_json(raw: str, kind):
    # Rendering a refused malformed draft must not crash or rewrite its raw input.
    try:
        value = json.loads(raw)
        return value if isinstance(value, kind) else kind()
    except (TypeError, ValueError):
        return kind()


def _payload(values: dict) -> EnvelopeSave:
    currency = values["home_currency_code"]
    amounts = json.loads(values["allocations_json"])
    if not isinstance(amounts, dict):
        raise ValueError("allocations must retain purpose keys")
    return EnvelopeSave(expected_row_version=int(values["expected_row_version"]), home_currency_code=currency,
        account_public_ids=json.loads(values["account_ids_json"]), account_row_versions=json.loads(values["account_versions_json"]),
        allocations={key: major_amount_to_minor(value, currency) for key, value in amounts.items()},
        reason=values["note"])


def _native_values(values: dict) -> None:
    if not values.get("native_controls"):
        return
    amounts = _retained_json(values["allocations_json"], dict)
    amounts.update({key.removeprefix("allocation:"): value for key, value in values.items() if key.startswith("allocation:")})
    values["allocations_json"] = json.dumps(amounts, ensure_ascii=False)
    values["account_ids_json"] = json.dumps([key.removeprefix("source:") for key in values if key.startswith("source:")])


def _ack(request: Request, values: dict, receipt: EnvelopeReceipt):
    href = f"/web/envelopes?ledger_id={receipt.ledger_id}&month={receipt.month}"
    return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=values["idempotency_key"],
        receipt=receipt, next_href=href) or _web_redirect("/web/envelopes", receipt.ledger_id, month=receipt.month)


@router.post("/save")
async def web_save_envelopes(request: Request, expected_row_version: str = Form(""),
                             _local: None = LocalOnly, db: Session = Depends(get_db)):
    values = dict(await request.form())
    values["expected_row_version"] = expected_row_version
    ledger, month = str(values.get("ledger_id", "")), str(values.get("month", ""))
    try:
        _require_selected_ledger_write(_list_ledger_options(db), ledger)
        auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
        _native_values(values)
        payload = _payload(values)
        if values.get("review_latest"):
            receipt = review_envelopes(db, auth=auth, month=month, payload=payload, key=values["idempotency_key"])
            if receipt is not None:
                return _ack(request, values, receipt)
            current = envelopes_view(db, tenant_id=ledger, actor_account_id=auth.account_id, month=month)
            if current.home_currency_code != payload.home_currency_code:
                raise AppError("state_conflict", "请保留原币金额核对，不能直接更换币种标签。", status_code=409)
            refreshed = _values(current)
            original = values["idempotency_key"]
            values.update({key: refreshed[key] for key in ("expected_row_version", "account_versions_json", "idempotency_key")})
            return _render(request, db, ledger_id=ledger, month=month, values=values, result="prepared", prepared_from=original)
        receipt = save_envelopes(db, auth=auth, month=month, payload=payload, key=values["idempotency_key"])
    except (AppError, ValidationError, ValueError, TypeError, KeyError) as exc:
        db.rollback()
        error = exc if isinstance(exc, AppError) else AppError("invalid_request", "请核对原币金额和所选账户，原输入已保留。", status_code=422)
        response = draft_error_response(request, error)
        if response is not None:
            return response
        return _render(request, db, ledger_id=ledger, month=month, values=values, error=error.message,
                       result=draft_refusal_result(error), status=error.status_code)
    return _ack(request, values, receipt)
