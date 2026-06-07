"""Owner Console — 孤儿标签清理 (ADR-0043 slice C).

Orphan tags (usage_count == 0) linger after their last expense is untagged
(``set_expense_tags`` drops the link but leaves the ``Tag`` row). This panel
lists them for the default ledger and lets the operator soft-delete them via the
shared ``tag_management_service.delete_tag`` (which writes an undo snapshot; the
periodic purge scheduler hard-deletes past the window). Loopback-only.

Reuses the same service as ``/api/tags`` and ``/web/tags`` — no bespoke delete
path. Orphan filtering happens in the handler so no new ledger-scoped service
query is introduced (``test_ledger_query_scope_guard`` does not scan this
subpackage, but reusing the scoped service keeps it honest anyway).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.owner_console._ai_advisor import _owner_console_tenant_id
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services.tag_management_service import delete_tag, list_tags_with_usage

router = APIRouter(prefix="/owner", tags=["owner"])


@router.get("/tag-cleanup", response_class=HTMLResponse)
def owner_tag_cleanup_get(
    request: Request,
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    tenant_id = _owner_console_tenant_id(db)
    all_tags = list_tags_with_usage(db, tenant_id)
    orphans = [t for t in all_tags if t.usage_count == 0]
    ctx = _base(request, db)
    ctx["tenant_id"] = tenant_id
    ctx["orphans"] = orphans
    ctx["total_tags"] = len(all_tags)
    ctx["flash_message"] = msg
    return templates.TemplateResponse(
        request=request, name="tag_cleanup.html", context=ctx
    )


@router.post("/tag-cleanup/delete", response_class=HTMLResponse)
def owner_tag_cleanup_delete(
    public_id: str = Form(...),
    expected_row_version: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    tenant_id = _owner_console_tenant_id(db)
    # Parse the OCC token like the /web sibling (graceful redirect, not a raw
    # 422 JSON blob) — a blank/non-numeric token means a stale/tampered form.
    try:
        parsed_row_version = int(expected_row_version)
    except (TypeError, ValueError):
        return RedirectResponse(
            url=f"/owner/tag-cleanup?msg={quote('该标签已变化或不存在，请刷新后重试。')}",
            status_code=303,
        )
    # Friendly fast-path: if it's already non-orphan at render time, skip with a
    # clear message. This is NOT the race guard — list_tags_with_usage is itself a
    # query, so a re-tag can still land between here and the delete. Correctness
    # comes from delete_tag(require_orphan=True): its UPDATE soft-deletes atomically
    # only while NOT EXISTS(expense_tags) holds (re-tagging a live tag doesn't bump
    # row_version, so the OCC token alone can't catch it).
    if not any(
        t.public_id == public_id and t.usage_count == 0
        for t in list_tags_with_usage(db, tenant_id)
    ):
        return RedirectResponse(
            url=f"/owner/tag-cleanup?msg={quote('该标签已不再是孤儿（可能刚被使用），已跳过。')}",
            status_code=303,
        )
    try:
        delete_tag(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            expected_row_version=parsed_row_version,
            require_orphan=True,
        )
        msg = "已清理孤儿标签。"
    except AppError as exc:
        # Stale token (someone tagged an expense with it again, or it's gone):
        # re-render with the up-to-date list rather than 500ing.
        msg = "该标签已变化或不存在，请刷新后重试。" if exc.error in {
            "state_conflict",
            "tag_not_found",
        } else exc.message
    return RedirectResponse(
        url=f"/owner/tag-cleanup?msg={quote(msg)}", status_code=303
    )
