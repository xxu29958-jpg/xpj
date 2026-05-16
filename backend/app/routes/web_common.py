"""Shared helpers for /web routes (v0.4-alpha3 slice 2 structure split).

This module hosts everything that previously lived as helpers in
``web_app.py``: the loopback gate, ledger selector, formatters, and the
expense view-model. Each /web route module imports from here so we keep a
single source of truth for ledger isolation rules and amount/time/string
formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.network_boundary import require_owner_console_local
from app.models import AuthToken, Device, Expense
from app.services import backup_service
from app.services.budget_service import get_monthly_budget
from app.services.dashboard_service import list_dashboard_cards
from app.services.goal_service import list_goals
from app.services import owner_console_service as owner_svc
from app.services.expense_service import list_pending
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import list_recurring_items
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month, now_utc
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


_VALID_UI_THEMES = {"paper", "mono", "midnight"}


def _read_ui_theme(request: Request) -> str:
    raw = request.cookies.get("ui_theme")
    if raw in _VALID_UI_THEMES:
        return raw
    return "paper"


def _sidebar_counts(db: Session, ledger_id: str) -> tuple[int, int]:
    """Cheap counts for the sidebar nav badges (pending + suspected duplicates).

    Avoids loading full ``list_pending()`` rows on pages that don't need them.
    """
    pending_count = int(
        db.scalar(
            select(func.count(Expense.id))
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.status == "pending")
        )
        or 0
    )
    suspected_count = int(
        db.scalar(
            select(func.count(Expense.id))
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.status == "pending")
            .where(Expense.duplicate_status == "suspected")
        )
        or 0
    )
    return pending_count, suspected_count


def _base_ctx(
    request: Request,
    *,
    options: list[LedgerOption],
    selected_ledger_id: str,
    page_title: str | None = None,
    show_month_picker: bool = False,
    selected_month: str | None = None,
    sidebar_counts: tuple[int, int] | None = None,
) -> dict:
    selected = _selected_option(options, selected_ledger_id)
    pending_count, suspected_count = sidebar_counts or (0, 0)
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
        "page_title": page_title,
        "ui_theme": _read_ui_theme(request),
        "show_month_picker": show_month_picker,
        "selected_month": selected_month,
        "pending_count": pending_count,
        "suspected_duplicate_count": suspected_count,
    }


# ── Formatters ──────────────────────────────────────────────────────────────


def _amount_yuan(amount_cents: int | None) -> str:
    if amount_cents is None:
        return ""
    return f"{amount_cents / 100:.2f}"


def _trend14_amounts(db: Session, ledger_id: str) -> list[dict]:
    """近 14 个日历日（含今天）的每日确认金额，按 expense_time/confirmed_at 聚合。

    返回顺序：从最早到今天，每项 {'d': 'MM-DD', 'amount_yuan': float}。
    日期为空的 expense 会 fallback 到 confirmed_at；都没有则忽略。
    """
    today = now_utc().astimezone().date()
    start = today - timedelta(days=13)
    expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
    rows = db.execute(
        select(func.strftime("%m-%d", expense_time), func.coalesce(func.sum(Expense.amount_cents), 0))
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(func.date(expense_time) >= start.isoformat())
        .where(func.date(expense_time) <= today.isoformat())
        .group_by(func.strftime("%m-%d", expense_time))
    )
    by_day: dict[str, int] = {label: int(amt or 0) for label, amt in rows}
    result: list[dict] = []
    for i in range(14):
        d = start + timedelta(days=i)
        label = d.strftime("%m-%d")
        result.append({
            "d": label,
            "amount_yuan": by_day.get(label, 0) / 100.0,
            "amount_cents": by_day.get(label, 0),
        })
    return result


def _confirmed_by_day(db: Session, ledger_id: str, month: str) -> list[dict]:
    """已确认账单在指定月内的每日金额，用于日历热力图。

    返回 [{'date': 'YYYY-MM-DD', 'amount_cents': int, 'count': int}]，
    只包含该月有支出的天；模板自己填空日。
    """
    if not month or "-" not in month:
        return []
    expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
    rows = db.execute(
        select(
            func.strftime("%Y-%m-%d", expense_time),
            func.coalesce(func.sum(Expense.amount_cents), 0),
            func.count(Expense.id),
        )
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
        .where(func.strftime("%Y-%m", expense_time) == month)
        .group_by(func.strftime("%Y-%m-%d", expense_time))
    )
    return [
        {"date": d, "amount_cents": int(amt or 0), "amount_yuan": int(amt or 0) / 100.0, "count": int(cnt)}
        for d, amt, cnt in rows
    ]


def _confirmed_source_breakdown(db: Session, ledger_id: str, month: str | None) -> list[dict]:
    """指定月的已确认账单来源占比。返回 [{'label', 'count', 'percent'}]。"""
    q = (
        select(Expense.source, func.count(Expense.id))
        .where(Expense.tenant_id == ledger_id)
        .where(Expense.status == "confirmed")
    )
    if month:
        expense_time = func.coalesce(Expense.expense_time, Expense.confirmed_at)
        q = q.where(func.strftime("%Y-%m", expense_time) == month)
    q = q.group_by(Expense.source)
    rows = list(db.execute(q))
    total = sum(int(c or 0) for _, c in rows) or 1
    return [
        {
            "label": _SOURCE_LABELS.get((s or "").strip(), "其他"),
            "count": int(c),
            "percent": int(round(int(c) / total * 100)),
        }
        for s, c in sorted(rows, key=lambda r: -int(r[1] or 0))
    ]


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


def _previous_month_string(month: str) -> str | None:
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_number = int(month_text)
    except (TypeError, ValueError):
        return None
    if not 1 <= month_number <= 12:
        return None
    if month_number == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month_number - 1:02d}"


def _dashboard_cards(db: Session, ledger_id: str) -> dict:
    pending_rows = list_pending(db, ledger_id)
    pending_count = len(pending_rows)
    needs_amount = sum(1 for e in pending_rows if e.amount_cents is None)
    needs_merchant = sum(1 for e in pending_rows if not (e.merchant or "").strip())
    suspected = sum(
        1 for e in pending_rows if (getattr(e, "duplicate_status", None) or "") == "suspected"
    )
    month = current_month("Asia/Shanghai")
    stats = monthly_stats(db, month, ledger_id)
    prev_month = _previous_month_string(month)
    prev_stats = monthly_stats(db, prev_month, ledger_id) if prev_month else None
    recurring_rows = list_recurring_items(db, tenant_id=ledger_id, include_archived=False)
    active_recurring = sum(1 for item in recurring_rows if item.status == "active")
    paused_recurring = sum(1 for item in recurring_rows if item.status == "paused")
    candidate_count = len(recurring_candidates(db, tenant_id=ledger_id))
    budget = get_monthly_budget(db, tenant_id=ledger_id, month=month, timezone_name="Asia/Shanghai")
    goals = list_goals(db, tenant_id=ledger_id, month=month, timezone_name="Asia/Shanghai")
    goal_risk_count = sum(1 for goal in goals if goal.progress_state in {"near_limit", "over_limit"})
    now = now_utc()
    week_ago = now - timedelta(days=7)
    recent_count = int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == ledger_id)
            .where(Expense.created_at >= week_ago)
        )
        or 0
    )
    active_device_count = int(
        db.scalar(
            select(func.count(func.distinct(Device.id)))
            .select_from(Device)
            .join(AuthToken, AuthToken.device_id == Device.id)
            .where(AuthToken.ledger_id == ledger_id)
            .where(AuthToken.revoked_at.is_(None))
            .where(Device.revoked_at.is_(None))
        )
        or 0
    )
    latest_backup = backup_service.latest_backup()
    backup_age_days = None
    if latest_backup is not None:
        backup_age_days = max(0, (now.astimezone() - latest_backup.created_at).days)
    layout = list_dashboard_cards(db, tenant_id=ledger_id, surface="web")
    current_total = int(stats["total_amount_cents"])
    prev_total = int(prev_stats["total_amount_cents"]) if prev_stats else 0
    delta_amount = current_total - prev_total
    if prev_total <= 0:
        delta_direction = "none"
        delta_percent = None
    elif delta_amount == 0:
        delta_direction = "flat"
        delta_percent = 0
    elif delta_amount > 0:
        delta_direction = "up"
        delta_percent = int(round(delta_amount * 100 / prev_total))
    else:
        delta_direction = "down"
        delta_percent = int(round(abs(delta_amount) * 100 / prev_total))
    return {
        "layout": [
            {
                "key": item.key,
                "title": item.title,
                "visible": item.visible,
                "position": item.position,
            }
            for item in layout.items
        ],
        "pending_count": pending_count,
        "needs_amount_count": needs_amount,
        "needs_merchant_count": needs_merchant,
        "suspected_duplicate_count": suspected,
        "month": month,
        "total_amount_yuan": _amount_yuan(int(stats["total_amount_cents"])),
        "confirmed_count": int(stats["count"]),
        "previous_month": prev_month,
        "previous_total_amount_yuan": _amount_yuan(prev_total),
        "delta_amount_yuan": _amount_yuan(abs(delta_amount)),
        "delta_direction": delta_direction,
        "delta_percent": delta_percent,
        "recurring_active_count": active_recurring,
        "recurring_paused_count": paused_recurring,
        "recurring_candidate_count": candidate_count,
        "budget_configured": budget.configured,
        "budget_total_yuan": _amount_yuan(int(budget.total_amount_cents)),
        "budget_remaining_yuan": _amount_yuan(int(budget.remaining_amount_cents)),
        "budget_overspent_yuan": _amount_yuan(int(budget.overspent_amount_cents)),
        "budget_is_over": budget.remaining_amount_cents < 0,
        "goals_count": len(goals),
        "goals_risk_count": goal_risk_count,
        "recent_count": recent_count,
        "active_device_count": active_device_count,
        "backup_available": latest_backup is not None,
        "backup_age_days": backup_age_days,
    }
