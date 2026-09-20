"""One bound native form for split-change commands and their original receipts."""

import json
from uuid import uuid4

from starlette.responses import Response

from app.routes._web_debt_repayment import repayment_scope
from app.routes._web_debt_write import _debt_write_gate
from app.routes._web_split_agreement import agreement_href, agreement_view, settlement_label
from app.routes.web_common import _base_ctx, _currency_input_view, _minor_amount_value, templates
from app.services.currency_common import supported_currency_codes

CHANGE_FIELDS = (
    "debt_public_id", "ledger_id", "origin_binding", "home_currency_code", "command",
    "proposal_public_id", "expected_row_version", "expected_return_row_version",
    "new_share_amount_major", "settlement_net_amount_major", "reason", "supersedes_proposal_public_id",
)
COMMAND_LABELS = {"create": "发送新约定", "accept": "接受这份约定", "reject": "拒绝这份约定", "withdraw": "撤回我的约定"}


def command_path(public_id: str, command: str, proposal_id: str = "") -> str:
    base = f"/web/debts/{public_id}/split-changes"
    return base if command == "create" else f"{base}/{proposal_id}/{command}"


def initial_values(request, db, *, selected_id, public_id, agreement, command="create", supersedes="") -> dict:
    pending = agreement.pending_proposal if agreement else None
    code = agreement.home_currency_code if agreement else ""
    initial = dict.fromkeys(CHANGE_FIELDS, "")
    initial.update(debt_public_id=public_id, ledger_id=selected_id,
        origin_binding=json.dumps(repayment_scope(request, db), ensure_ascii=False, sort_keys=True),
        command=command, home_currency_code=code, idempotency_key=str(uuid4()), supersedes_proposal_public_id=supersedes)
    if agreement:
        initial.update(expected_row_version=str(agreement.original_debt.row_version),
            expected_return_row_version=str(agreement.return_debt.row_version) if agreement.return_debt else "",
            new_share_amount_major=_minor_amount_value(agreement.preview.new_share_amount_cents, code),
            settlement_net_amount_major=_minor_amount_value(agreement.preview.default_settlement_net_amount_cents, code))
    if command != "create" and pending:
        initial.update(proposal_public_id=pending.public_id, reason=pending.reason,
            new_share_amount_major=_minor_amount_value(pending.new_share_amount_cents, code),
            settlement_net_amount_major=_minor_amount_value(pending.settlement_net_amount_cents, code),
            expected_row_version=str(pending.original_debt_row_version),
            expected_return_row_version=str(pending.return_debt_row_version) if pending.return_debt_row_version else "")
    return initial


def pending_view(agreement, *, public_id, selected_id) -> dict | None:
    proposal = agreement.pending_proposal
    if proposal is None:
        return None
    code = agreement.home_currency_code
    actions = ["withdraw"] if proposal.proposed_by_you else ["accept", "reject"]
    return {"proposal": proposal, "share": _minor_amount_value(proposal.new_share_amount_cents, code),
            "settlement": settlement_label(proposal.settlement_net_amount_cents, code),
            "actions": [{"label": COMMAND_LABELS[action], "href": agreement_href(public_id, selected_id) + f"&command={action}"}
                        for action in actions]}


def _command_allowed(can_draft, values, pending) -> bool:
    if values["command"] == "create":
        return can_draft
    return bool(can_draft and pending and values["proposal_public_id"] == pending.public_id and
                (pending.proposed_by_you == (values["command"] == "withdraw")))


def _replacement_intent(values, agreement, pending) -> dict:
    replacement_values = {field: values[field] for field in CHANGE_FIELDS}
    replacement_values.update(command="create", proposal_public_id="",
        expected_row_version=str(agreement.original_debt.row_version),
        expected_return_row_version=str(agreement.return_debt.row_version) if agreement.return_debt else "",
        supersedes_proposal_public_id=pending.public_id if pending else "")
    return {"clientRef": str(uuid4()), "values": replacement_values}


def render_change_task(request, db, *, options, selected_id, public_id, agreement=None,
                       values=None, error="", result="", ack=None, status_code=200, command="create", supersedes="",
                       rejected=False) -> Response:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="拆账新约定")
    initial = initial_values(request, db, selected_id=selected_id, public_id=public_id,
                             agreement=agreement, command=command, supersedes=supersedes)
    if values is not None:
        initial.update(values)
    can_write = _debt_write_gate(options, selected_id)
    can_draft = bool(can_write and agreement and agreement.viewer_is_party)
    current_command = initial["command"]
    pending = agreement.pending_proposal if agreement else None
    can_create = _command_allowed(can_draft, initial, pending)
    replacement = None
    if rejected and values and can_draft:
        replacement = _replacement_intent(initial, agreement, pending)
    ctx.update(agreement_task=True, agreement=agreement_view(agreement, selected_id=selected_id) if agreement else None,
        agreement_pending=pending_view(agreement, public_id=public_id, selected_id=selected_id) if agreement else None,
        change={"values": initial, "fields": CHANGE_FIELDS, "scope": repayment_scope(request, db), "error": error,
                "result": result, "ack": ack, "can_create": can_create, "can_draft": can_draft, "can_recover": can_write,
                "replacement": replacement,
                "href": agreement_href(public_id, selected_id), "public_id": public_id,
                "submit_label": COMMAND_LABELS.get(current_command, "核对原约定操作"),
                "action": command_path(public_id, current_command, initial["proposal_public_id"]),
                "currency_input": _currency_input_view(initial["home_currency_code"])
                    if initial["home_currency_code"] in supported_currency_codes() else None})
    return templates.TemplateResponse(request=request, name="split_agreement.html", context=ctx, status_code=status_code)
