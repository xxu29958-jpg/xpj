"""Web task adapters for the existing two-party split-change command owner."""

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_debt_repayment import repayment_scope, require_repayment_binding
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes._web_split_change_form import CHANGE_FIELDS, initial_values, render_change_task
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _minor_amount_value,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    parse_form_row_version_token,
)
from app.schemas._bill_split_change import BillSplitChangeAcceptRequest, BillSplitChangeCreateRequest
from app.services import bill_split_service
from app.services.currency_common import major_amount_to_minor
from app.services.debt_service import get_participant_debt_response

router = APIRouter(prefix="/web/debts", tags=["web"])


def _read(db, *, selected_id, actor, public_id, new_share=None):
    return bill_split_service.get_bill_split_agreement(db, tenant_id=selected_id, actor_account_id=actor,
        public_id=public_id, new_share_amount_cents=new_share)


def _outcome(request, db, *, options, selected_id, public_id, values=None, error="", result="", ack=None,
             status_code=200, command="create", supersedes="", rejected=False):
    try:
        actor = resolve_web_actor_account_id(db, request, selected_id)
        agreement = _read(db, selected_id=selected_id, actor=actor, public_id=public_id)
    except (AppError, SQLAlchemyError):
        db.rollback()
        agreement = None
        error = error or "拆账约定暂时无法读取，请重试。已有提交结果与原输入仍保留。"
    return render_change_task(request, db, options=options, selected_id=selected_id, public_id=public_id,
        agreement=agreement, values=values, error=error, result=result, ack=ack,
        status_code=status_code, command=command, supersedes=supersedes, rejected=rejected)


@router.get("/{public_id}/split-agreement")
def web_split_agreement(request: Request, public_id: str, ledger_id: str = "", command: str = "create",
                        supersedes: str = "", _local: None = LocalOnly, db: Session = Depends(get_db)):
    if command not in {"create", "accept", "reject", "withdraw"}:
        raise AppError("invalid_request", status_code=422)
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _outcome(request, db, options=options, selected_id=selected_id, public_id=public_id,
                    command=command, supersedes=supersedes)


async def _form(request):
    form = await request.form()
    return {field: str(form.get(field, "")) for field in (*CHANGE_FIELDS, "idempotency_key")}


def _versions(values):
    original = parse_form_row_version_token(values["expected_row_version"])
    returned = parse_form_row_version_token(values["expected_return_row_version"])
    if original is None or (values["expected_return_row_version"] and returned is None):
        raise AppError("state_conflict", "原约定版本无法读取，请核对后重新填写。", status_code=409)
    return {"expected_row_version": original, "expected_return_row_version": returned}


def _command_payload(values, code):
    versions = _versions(values)
    if values["command"] == "accept":
        return BillSplitChangeAcceptRequest(**versions)
    return BillSplitChangeCreateRequest(**versions,
        new_share_amount_cents=major_amount_to_minor(values["new_share_amount_major"], code),
        settlement_net_amount_cents=major_amount_to_minor(values["settlement_net_amount_major"], code, allow_negative=True),
        reason=values["reason"], supersedes_proposal_public_id=values["supersedes_proposal_public_id"] or None)


def _execute(db, *, selected_id, actor, public_id, values, code):
    from app.services import bill_split_change_command_service as commands

    kwargs = {"tenant_id": selected_id, "actor_account_id": actor, "public_id": public_id,
              "idempotency_key": values["idempotency_key"]}
    command = values["command"]
    if command == "create":
        return commands.create_bill_split_change_idempotently(db, payload=_command_payload(values, code), **kwargs)
    kwargs["proposal_public_id"] = values["proposal_public_id"]
    if command == "accept":
        return commands.accept_bill_split_change_idempotently(db, payload=_command_payload(values, code), **kwargs)
    if command == "reject":
        return commands.reject_bill_split_change_idempotently(db, **kwargs)
    return commands.withdraw_bill_split_change_idempotently(db, **kwargs)


async def _submit(request: Request, db: Session, *, public_id: str, command: str,
                  proposal_public_id: str = "") -> Response:
    values = await _form(request)
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values["ledger_id"], options, request=request)
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id)
        _require_selected_ledger_write(options, selected_id)
        if (values["ledger_id"] != selected_id or values["command"] != command or
                values["proposal_public_id"] != proposal_public_id or not values["idempotency_key"]):
            raise AppError("session_binding_changed", "原身份或原任务不匹配，输入仍保留。", status_code=409)
        actor = resolve_web_actor_account_id(db, request, selected_id)
        debt = get_participant_debt_response(db, public_id=public_id, ledger_id=selected_id, account_id=actor)
        if values["home_currency_code"] != debt.home_currency_code:
            raise AppError("debt_currency_changed", status_code=409)
        receipt = _execute(db, selected_id=selected_id, actor=actor, public_id=public_id,
                           values=values, code=debt.home_currency_code)
    except (AppError, ValidationError, SQLAlchemyError) as exc:
        db.rollback()
        status = exc.status_code if isinstance(exc, AppError) else 503 if isinstance(exc, SQLAlchemyError) else 422
        message = exc.message if isinstance(exc, AppError) else "结果暂未确认，请核实原提交。" if status == 503 else "请检查金额、原因和约定版本。"
        invalid = isinstance(exc, ValidationError) or isinstance(exc, AppError) and exc.error in {
            "amount_invalid", "debt_amount_invalid", "invalid_request"}
        rejected = isinstance(exc, AppError) and exc.error in {
            "state_conflict", "split_change_repayment_pending", "split_change_pending",
            "split_change_not_pending", "split_change_expired"}
        rejected = rejected or isinstance(exc, AppError) and exc.error in {
            "split_total_exceeds_parent", "split_amount_exceeds_parent"}
        result = "rejected" if invalid else "submitted" if status >= 500 else "blocked"
        return _outcome(request, db, options=options, selected_id=selected_id, public_id=public_id,
            values=values, error=message, result=result, status_code=status, rejected=rejected)
    receipt_id = receipt.invitation_public_id if command == "accept" else receipt.public_id
    ack = {"scope": repayment_scope(request, db), "clientRef": values["idempotency_key"], "resultPublicId": receipt_id,
           "values": {field: values[field] for field in CHANGE_FIELDS}}
    return _outcome(request, db, options=options, selected_id=selected_id, public_id=public_id, ack=ack)


@router.post("/{public_id}/split-changes")
async def web_create_split_change(request: Request, public_id: str, _local: None = LocalOnly, db: Session = Depends(get_db)):
    return await _submit(request, db, public_id=public_id, command="create")


@router.post("/{public_id}/split-changes/{proposal_public_id}/accept")
async def web_accept_split_change(request: Request, public_id: str, proposal_public_id: str,
                                 _local: None = LocalOnly, db: Session = Depends(get_db)):
    return await _submit(request, db, public_id=public_id, command="accept", proposal_public_id=proposal_public_id)


@router.post("/{public_id}/split-changes/{proposal_public_id}/reject")
async def web_reject_split_change(request: Request, public_id: str, proposal_public_id: str,
                                 _local: None = LocalOnly, db: Session = Depends(get_db)):
    return await _submit(request, db, public_id=public_id, command="reject", proposal_public_id=proposal_public_id)


@router.post("/{public_id}/split-changes/{proposal_public_id}/withdraw")
async def web_withdraw_split_change(request: Request, public_id: str, proposal_public_id: str,
                                   _local: None = LocalOnly, db: Session = Depends(get_db)):
    return await _submit(request, db, public_id=public_id, command="withdraw", proposal_public_id=proposal_public_id)


@router.post("/{public_id}/split-agreement/preview")
async def web_preview_split_change(request: Request, public_id: str, _local: None = LocalOnly, db: Session = Depends(get_db)):
    values = await _form(request)
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, values["ledger_id"], options, request=request)
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id)
        actor = resolve_web_actor_account_id(db, request, selected_id)
        current = _read(db, selected_id=selected_id, actor=actor, public_id=public_id)
        amount = major_amount_to_minor(values["new_share_amount_major"], current.home_currency_code)
        agreement = _read(db, selected_id=selected_id, actor=actor, public_id=public_id, new_share=amount)
        values["settlement_net_amount_major"] = _minor_amount_value(
            agreement.preview.default_settlement_net_amount_cents, agreement.home_currency_code)
        fresh = initial_values(request, db, selected_id=selected_id, public_id=public_id, agreement=agreement)
        for key in ("expected_row_version", "expected_return_row_version"):
            values[key] = fresh[key]
    except (AppError, SQLAlchemyError) as exc:
        db.rollback()
        return _outcome(request, db, options=options, selected_id=selected_id, public_id=public_id, values=values,
            error=exc.message if isinstance(exc, AppError) else "暂时无法预览，请保留输入后重试。", result="preview",
            status_code=exc.status_code if isinstance(exc, AppError) else 503)
    return render_change_task(request, db, options=options, selected_id=selected_id, public_id=public_id,
                              agreement=agreement, values=values, result="preview")
