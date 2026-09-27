"""Typed void forms use the existing original-submission storage and binding owner."""
import json
from uuid import uuid4

from app.routes._web_debt_repayment import repayment_scope
from app.routes._web_debt_write import _debt_write_gate
from app.routes.web_common import _base_ctx, templates

VOID_FIELDS = ("debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "reason", "repayment_public_id")


def void_context(request, db, *, selected_id, public_id, kind, expected="", target="",
                 can_create=False, can_recover=False, values=None, error="", result="", ack=None):
    scope = repayment_scope(request, db)
    initial = {"debt_public_id": public_id, "ledger_id": selected_id,
                   "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
                   "expected_row_version": expected, "reason": "", "repayment_public_id": target,
                   "idempotency_key": str(uuid4()) if can_create else ""}
    if values is not None:
        initial.update(values)
    return {"public_id": public_id, "kind": kind, "scope": scope, "values": initial, "error": error,
                "result": result, "ack": ack, "visible": can_create or values is not None,
                "can_create": can_create, "can_recover": can_recover}


def render_void_recovery(request, db, *, options, selected_id, public_id, kind,
                         values=None, error="", result="", status_code=503, ack=None):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对原作废")
    ctx["void_form"] = void_context(request, db, selected_id=selected_id, public_id=public_id,
        kind=kind, values=values, error=error, result=result, ack=ack,
        can_recover=_debt_write_gate(options, selected_id))
    return templates.TemplateResponse(request=request, name="debt_void_recovery.html", context=ctx, status_code=status_code)


def add_void_detail_context(request, db, *, ctx, debt, selected_id, public_id,
                            kind=None, values=None, error="", result="", ack=None, target=""):
    writable = ctx["can_write"] and not ctx["debt"]["is_member"]
    ctx["void_form"] = void_context(request, db, selected_id=selected_id, public_id=public_id,
        kind="debt-void", expected=str(debt.row_version), can_create=writable and debt.status == "open",
        can_recover=writable, values=values if kind == "void" else None,
        error=error if kind == "void" else "", result=result if kind == "void" else "",
        ack=ack if kind == "void" else None)
    target_on_page = any(row["kind"] == "repayment" and row["repayment"]["public_id"] == target
                         for row in ctx["activity"]["rows"])
    ctx["repayment_void_recovery"] = void_context(request, db, selected_id=selected_id, public_id=public_id,
        kind="repayment-void", can_recover=writable,
        values=values if kind == "repayment_void" and not target_on_page else None,
        error=error if kind == "repayment_void" else "",
        result=result if kind == "repayment_void" and not target_on_page else "",
        ack=ack if kind == "repayment_void" else None)
    for row in ctx["activity"]["rows"]:
        if row["kind"] == "repayment":
            fact = row["repayment"]
            fact["void_form"] = void_context(request, db, selected_id=selected_id, public_id=public_id,
                kind="repayment-void", expected=str(debt.row_version), target=fact["public_id"],
                can_create=writable and debt.status != "voided" and not fact["is_voided"], can_recover=writable,
                values=values if kind == "repayment_void" and fact["public_id"] == target else None,
                error=error if kind == "repayment_void" and fact["public_id"] == target else "",
                result=result if kind == "repayment_void" and fact["public_id"] == target else "")
    if kind in {"void", "repayment_void"}:
        ctx["action_form"]["fallback"] = ctx["debt"]["is_member"]
