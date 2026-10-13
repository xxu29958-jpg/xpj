"""Bound Web apply tasks use the same original-command owner as the API."""

import json
from typing import Literal
from uuid import uuid4

from fastapi import Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
)
from app.routes._web_session_common import resolve_web_actor
from app.routes.web_common import (
    _base_ctx,
    _require_selected_ledger_write,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.services.rule_application_service import (
    apply_rules_idempotently,
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
)


class RuleApplicationForm(BaseModel):
    ledger_id: str = ""
    apply_status: Literal["pending", "confirmed"] = "pending"
    preview_confirmed: str = ""
    preview_token: str = ""
    idempotency_key: str = ""
    draft_ref: str = ""
    draft_scope: str = ""
    original_scanned: int = 0
    original_changed: int = 0
    review_new: bool = False


def render_rule_application(request: Request, db: Session, *, options, selected_id: str,
    status: Literal["pending", "confirmed"], preview: bool = False,
    form: RuleApplicationForm | None = None, result: str = "", error: AppError | None = None,
) -> Response:
    scope = browser_draft_scope(db, request)
    impact = None
    if preview:
        read = preview_apply_rules_to_confirmed if status == "confirmed" else preview_apply_rules_to_pending
        impact = read(db, tenant_id=selected_id, limit=20)
    if form is None or result == "prepared":
        form = RuleApplicationForm(ledger_id=selected_id, apply_status=status, preview_confirmed="yes",
            preview_token=impact["preview_token"] if impact else "", idempotency_key=str(uuid4()),
            draft_ref=form.draft_ref if form else str(uuid4()), draft_scope=json.dumps(scope) if scope else "",
            original_scanned=impact["scanned"] if impact else 0, original_changed=impact["changed_count"] if impact else 0)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    ctx.update(rule_draft_scope=scope, application_form=form.model_dump(), application_result=result,
        application_status=status, error=error.message if error else "", bulk_preview=impact if status == "pending" else None,
        confirmed_bulk_preview=impact if status == "confirmed" else None, q="?ledger_id=" + selected_id)
    return templates.TemplateResponse(request=request, name="rule_impact.html", context=ctx,
        status_code=error.status_code if error else 200)


def submit_rule_application(request: Request, db: Session, *, options, selected_id: str,
    status: Literal["pending", "confirmed"], form: RuleApplicationForm,
) -> Response:
    if "application/json" not in request.headers.get("accept", ""):
        retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=form.model_dump(), task="应用分类规则")
        if retained is not None:
            return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        if form.preview_confirmed != "yes":
            return _web_redirect("/web/rules", selected_id,
                **{"confirmed_preview" if status == "confirmed" else "apply_preview": "1"}, msg="请先预览影响范围，再确认应用规则。")
        if form.ledger_id != selected_id or form.apply_status != status:
            raise AppError("session_binding_changed", "原账本或应用范围无法确认，请保留原任务。", status_code=409)
        require_draft_binding(db, request, ledger_id=form.ledger_id, draft_scope=form.draft_scope, require_session=False)
        if form.review_new:
            return render_rule_application(request, db, options=options, selected_id=selected_id,
                status=status, preview=True, form=form, result="prepared")
        account_id, device_id = resolve_web_actor(db, request, selected_id)
        receipt = apply_rules_idempotently(db, tenant_id=selected_id, status=status,
            preview_token=form.preview_token, idempotency_key=form.idempotency_key,
            actor_account_id=account_id, actor_device_id=device_id)
    except AppError as exc:
        db.rollback()
        result = "rejected" if exc.error in {"preview_stale", "preview_required"} else "blocked"
        return draft_error_response(request, exc, refusal_result=result) or render_rule_application(request, db,
            options=options, selected_id=selected_id, status=status, form=form, result=result, error=exc)
    suffix = " 还有未扫描账单，可再次预览。" if receipt.scan_limit_reached else ""
    redirect = _web_redirect("/web/rules", selected_id, view="history",
        msg=f"已核实原应用：改写了 {receipt.changed_count} 笔分类。{suffix}")
    return draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.idempotency_key,
        receipt=receipt, next_href=redirect.headers["location"]) or redirect
