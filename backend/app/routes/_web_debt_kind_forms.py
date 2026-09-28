"""Retained kind forms and recovery views, independent of the command adapter."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.routes._web_debt_write import _debt_write_gate, repayment_scope
from app.routes.web_common import _base_ctx, templates
from app.schemas import DebtResponse


def kind_context(
    request: Request, db: Session, *, selected_id: str, public_id: str,
    expected: str = "", debt_kind: str = "unspecified", can_create: bool = False,
    can_recover: bool = False, values: dict[str, str] | None = None, error: str = "",
    result: str = "", ack: dict | None = None, rejected: bool = False,
) -> dict:
    scope = repayment_scope(request, db)
    initial = {"debt_public_id": public_id, "ledger_id": selected_id,
        "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
        "expected_row_version": expected, "debt_kind": debt_kind,
        "idempotency_key": str(uuid4()) if can_create else ""}
    if values is not None:
        initial.update(values)
    return {"public_id": public_id, "scope": scope, "values": initial, "visible": can_create or values is not None,
        "can_create": can_create, "can_recover": can_recover, "error": error, "result": result,
        "ack": ack, "rejected": rejected}


def add_kind_detail_context(
    request: Request, db: Session, *, ctx: dict, debt: DebtResponse, selected_id: str,
    public_id: str, kind: str | None, values: dict[str, str] | None, error: str | None,
    result: str, ack: dict | None, rejected: bool,
) -> None:
    can_view_original = not ctx["debt"]["is_member"] or debt.ledger_id is not None and debt.viewer_is_debtor is True
    ctx["kind_form"] = kind_context(request, db, selected_id=selected_id, public_id=public_id,
        expected=str(debt.row_version), debt_kind=debt.debt_kind,
        can_create=ctx["can_write"] and ((not ctx["debt"]["is_member"] and debt.status == "open") or ctx["can_change_member_kind"]),
        can_recover=ctx["can_write"] and can_view_original,
        values=values if kind == "kind" else None,
        error=error if kind == "kind" else "", result=result, ack=ack, rejected=rejected)
    ctx["kind_form"]["can_view_original"] = can_view_original
    if kind == "kind":
        ctx["action_form"]["fallback"] = False


def render_kind_recovery(
    request: Request, db: Session, *, options: list[dict], selected_id: str, public_id: str,
    values: dict[str, str] | None = None, error: str = "", result: str = "",
    status_code: int = 200, ack: dict | None = None, rejected: bool = False,
) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对原偿还方式")
    ctx["kind_form"] = kind_context(request, db, selected_id=selected_id, public_id=public_id,
        can_recover=_debt_write_gate(options, selected_id), values=values,
        error=error, result=result, ack=ack, rejected=rejected)
    ctx["kind_detail_error"] = "当前详情暂时无法刷新，请稍后重新读取；原提交结果和输入仍保留在此页。"
    return templates.TemplateResponse(request=request, name="debt_kind_recovery.html", context=ctx, status_code=status_code)
