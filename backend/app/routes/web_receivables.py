"""/web viewer-personal receivables.

Combines the selected ledger's external/member receivables with the existing
privacy-redacted cross-ledger member creditor discovery.  Direction is resolved
for the current account in the service layer; no payable or third-party debt
can enter this page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debts import (
    _STATUS_RANK,
    _debt_view,
    _web_viewer_account_id,
)
from app.services.debt_service import list_receivables_for_account

router = APIRouter(prefix="/web/receivables", tags=["web"])

_INTRO = "别人需要还给你的往来都在这里；家庭往来保持双方确认，外部往来按事实记录。"
_EMPTY_TITLE = "当前没有待收往来"
_EMPTY_BODY = "借出款项或家庭拆账形成应收后，会在这里持续跟踪。"


def _receivable_row_view(debt) -> dict:
    """Use the same role-aware row projection as the payable list."""
    return _debt_view(debt)


@router.get("", response_class=HTMLResponse)
def web_receivables(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    # selected ledger drives the shell/sidebar AND resolves the loopback viewer account;
    # the receivables list itself is account-scoped (cross-ledger), not ledger-scoped.
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    rows = (
        list_receivables_for_account(
            db,
            tenant_id=selected_id,
            account_id=account_id,
        ).items
        if account_id is not None
        else []
    )
    # Active-first: open receivables before cleared/voided (sunk to the bottom). The
    # service returns status.asc (alphabetical → cleared before open), so re-sort here —
    # mirroring web_debts._split_debt_views + Android sortReceivablesActiveFirst (shared 1A
    # _STATUS_RANK). Python's stable sort preserves the service's created_at order in-rank.
    rows = sorted(rows, key=lambda d: _STATUS_RANK.get(d.status, 0))
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠我的",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _INTRO
    ctx["rows"] = [_receivable_row_view(debt) for debt in rows]
    ctx["empty_title"] = _EMPTY_TITLE
    ctx["empty_body"] = _EMPTY_BODY
    return templates.TemplateResponse(request=request, name="receivables.html", context=ctx)
