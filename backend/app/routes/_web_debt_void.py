"""Typed void forms use the existing original-submission storage and binding owner."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.routes._web_debt_write import _debt_write_gate, repayment_scope
from app.routes.web_common import _base_ctx, templates
from app.schemas import DebtResponse

VOID_FIELDS = ("debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "reason", "repayment_public_id")


def void_context(request, db, *, selected_id, public_id, kind, expected="", target="",
                 can_create=False, can_recover=False, values=None, error="", result="", ack=None, rejected=False):
    scope = repayment_scope(request, db)
    initial = {"debt_public_id": public_id, "ledger_id": selected_id,
                   "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
                   "expected_row_version": expected, "reason": "", "repayment_public_id": target,
                   "idempotency_key": str(uuid4()) if can_create else ""}
    if values is not None:
        initial.update(values)
    return {"public_id": public_id, "kind": kind, "scope": scope, "values": initial, "error": error,
                "result": result, "ack": ack, "visible": can_create or values is not None,
                "can_create": can_create, "can_recover": can_recover, "rejected": rejected}


def render_void_recovery(request, db, *, options, selected_id, public_id, kind,
                         values=None, error="", result="", status_code=503, ack=None, rejected=False):
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对原作废")
    ctx["void_form"] = void_context(request, db, selected_id=selected_id, public_id=public_id,
        kind=kind, values=values, error=error, result=result, ack=ack, rejected=rejected,
        can_recover=_debt_write_gate(options, selected_id))
    return templates.TemplateResponse(request=request, name="debt_void_recovery.html", context=ctx, status_code=status_code)


def add_void_detail_context(
    request: Request, db: Session, *, ctx: dict[str, Any], debt: DebtResponse,
    selected_id: str, public_id: str, kind: str | None = None,
    values: dict[str, str] | None = None, error: str = "", result: str = "",
    ack: dict[str, Any] | None = None, target: str = "", rejected: bool = False,
) -> None:
    writable = ctx["can_write"] and not ctx["debt"]["is_member"]
    base = {"selected_id": selected_id, "public_id": public_id, "can_recover": writable}
    feedback = {"values": values, "error": error, "result": result, "ack": ack, "rejected": rejected}
    debt_feedback = feedback if kind == "void" else {}
    repayment_feedback = feedback if kind == "repayment_void" else {}
    ctx["void_form"] = void_context(request, db, **base,
        kind="debt-void", expected=str(debt.row_version), can_create=writable and debt.status == "open",
        **debt_feedback)
    repayments = [row["repayment"] for row in ctx["activity"]["rows"] if row["kind"] == "repayment"]
    target_on_page = any(fact["public_id"] == target for fact in repayments)
    ctx["repayment_void_recovery"] = None if target_on_page else void_context(request, db, **base,
        kind="repayment-void", **repayment_feedback)
    can_void_repayment = writable and debt.status != "voided"
    for fact in repayments:
        row_feedback = repayment_feedback if fact["public_id"] == target else {}
        fact["void_form"] = void_context(request, db, **base,
            kind="repayment-void", expected=str(debt.row_version), target=fact["public_id"],
            can_create=can_void_repayment and not fact["is_voided"], **row_feedback)
    if kind in {"void", "repayment_void"}:
        ctx["action_form"]["fallback"] = ctx["debt"]["is_member"]
