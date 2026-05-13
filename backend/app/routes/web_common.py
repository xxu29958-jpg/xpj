"""Shared helpers for /web routes (v0.4-alpha3 slice 2 structure split).

This module hosts everything that previously lived as helpers in
``web_app.py``: the loopback gate, ledger selector, formatters, and the
expense view-model. Each /web route module imports from here so we keep a
single source of truth for ledger isolation rules and amount/time/string
formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.services import owner_console_service as owner_svc
from app.services.expense_service import list_pending
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import list_recurring_items
from app.services.stats_service import monthly_stats
from app.version import BACKEND_VERSION


_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "web"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _require_local(request: Request) -> None:
    """Loopback gate. Same rule as the Owner Console."""
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


@dataclass
class LedgerOption:
    """Option row for the /web ledger selector. Safe to render in HTML."""

    ledger_id: str
    name: str
    role: str
    is_default: bool
    pending_count: int
    confirmed_count: int


def _list_ledger_options(db: Session) -> list[LedgerOption]:
    return [
        LedgerOption(
            ledger_id=row.ledger_id,
            name=row.name,
            role=row.role,
            is_default=row.is_default,
            pending_count=row.pending_count,
            confirmed_count=row.confirmed_count,
        )
        for row in owner_svc.list_console_ledgers(db)
    ]


def _resolve_selected_ledger_id(
    db: Session, requested: str | None, options: list[LedgerOption] | None = None
) -> str:
    """Return the ledger_id the current /web page should operate on.

    ``requested`` comes from query / form. The result is **only** valid
    when it appears in :func:`owner_console_service.list_console_ledgers`;
    arbitrary tenant_id is rejected with a Chinese error.
    """
    opts = options if options is not None else _list_ledger_options(db)
    if not opts:
        raise AppError(
            "invalid_request",
            "服务尚未初始化，请先运行本机的 bootstrap 脚本。",
            status_code=400,
        )
    visible_ids = {opt.ledger_id for opt in opts}
    if requested is None or requested == "":
        for opt in opts:
            if opt.is_default:
                return opt.ledger_id
        return opts[0].ledger_id
    if requested not in visible_ids:
        raise AppError(
            "invalid_request",
            "请选择一个有权限的账本。",
            status_code=400,
        )
    return requested


def _selected_option(options: list[LedgerOption], ledger_id: str) -> LedgerOption:
    for opt in options:
        if opt.ledger_id == ledger_id:
            return opt
    return options[0]


def _require_selected_ledger_write(options: list[LedgerOption], ledger_id: str) -> None:
    selected = _selected_option(options, ledger_id)
    if selected.role not in {"owner", "member"}:
        raise AppError(
            "permission_denied",
            "当前角色为只读，无法修改账本。",
            status_code=403,
        )


def _with_ledger(path: str, ledger_id: str, **extra: str) -> str:
    params: dict[str, str] = {"ledger_id": ledger_id}
    for key, value in extra.items():
        if value:
            params[key] = value
    return f"{path}?{urlencode(params)}"


def _base_ctx(
    request: Request, *, options: list[LedgerOption], selected_ledger_id: str
) -> dict:
    selected = _selected_option(options, selected_ledger_id)
    return {
        "backend_version": BACKEND_VERSION,
        "request": request,
        "ledger_options": options,
        "selected_ledger_id": selected_ledger_id,
        "selected_ledger_name": selected.name,
        "selected_ledger_role": selected.role,
        "selected_ledger_is_default": selected.is_default,
        "is_viewer": selected.role == "viewer",
        "can_write": selected.role in ("owner", "member"),
    }


# ── Formatters ──────────────────────────────────────────────────────────────


def _amount_yuan(amount_cents: int | None) -> str:
    if amount_cents is None:
        return ""
    return f"{amount_cents / 100:.2f}"


_SOURCE_LABELS: dict[str, str] = {
    "ios_upload_link": "iPhone",
    "android_upload": "Android",
    "manual": "手动",
    "web": "网页",
}


def _expense_view(expense) -> dict:
    has_image = bool(expense.image_path) and not expense.image_deleted_at
    if has_image:
        image_state = "available"
    elif expense.image_deleted_at is not None:
        image_state = "cleaned"
    else:
        image_state = "missing"
    source_raw = getattr(expense, "source", "") or ""
    source_label = _SOURCE_LABELS.get(source_raw, "未知")
    needs_amount = expense.amount_cents is None
    needs_merchant = not (expense.merchant or "").strip()
    is_duplicate = (getattr(expense, "duplicate_status", None) or "") == "suspected"
    return {
        "id": expense.id,
        "amount_yuan": _amount_yuan(expense.amount_cents),
        "amount_cents": expense.amount_cents,
        "merchant": expense.merchant or "",
        "category": expense.category or "未分类",
        "note": expense.note or "",
        "status": expense.status,
        "expense_time": expense.expense_time.strftime("%Y-%m-%d %H:%M") if expense.expense_time else "",
        "created_at": expense.created_at.strftime("%Y-%m-%d %H:%M") if expense.created_at else "",
        "has_image": has_image,
        "image_state": image_state,
        "duplicate_status": expense.duplicate_status,
        "is_duplicate": is_duplicate,
        "needs_amount": needs_amount,
        "needs_merchant": needs_merchant,
        "source_label": source_label,
    }


def _dashboard_cards(db: Session, ledger_id: str) -> dict:
    pending_rows = list_pending(db, ledger_id)
    pending_count = len(pending_rows)
    needs_amount = sum(1 for e in pending_rows if e.amount_cents is None)
    needs_merchant = sum(1 for e in pending_rows if not (e.merchant or "").strip())
    suspected = sum(
        1 for e in pending_rows if (getattr(e, "duplicate_status", None) or "") == "suspected"
    )
    month = datetime.now().strftime("%Y-%m")
    stats = monthly_stats(db, month, ledger_id)
    recurring_rows = list_recurring_items(db, tenant_id=ledger_id, include_archived=False)
    active_recurring = sum(1 for item in recurring_rows if item.status == "active")
    paused_recurring = sum(1 for item in recurring_rows if item.status == "paused")
    candidate_count = len(recurring_candidates(db, tenant_id=ledger_id))
    return {
        "pending_count": pending_count,
        "needs_amount_count": needs_amount,
        "needs_merchant_count": needs_merchant,
        "suspected_duplicate_count": suspected,
        "month": month,
        "total_amount_yuan": _amount_yuan(int(stats["total_amount_cents"])),
        "confirmed_count": int(stats["count"]),
        "recurring_active_count": active_recurring,
        "recurring_paused_count": paused_recurring,
        "recurring_candidate_count": candidate_count,
    }
