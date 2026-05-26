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
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import CURRENCY_SYMBOLS, FX_STATUS_PENDING, NO_FRACTION_CURRENCY_CODES
from app.middleware.csrf import csrf_context
from app.network_boundary import require_owner_console_local
from app.services import backup_service, web_stats_service
from app.services import owner_console_service as owner_svc
from app.services.budget_service import get_monthly_budget
from app.services.dashboard_service import list_dashboard_cards
from app.services.exchange_rate_service import home_currency_code
from app.services.expense_service import list_pending
from app.services.goal_service import list_goals
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import list_recurring_items
from app.services.stats_service import monthly_stats
from app.services.time_service import current_month, now_utc
from app.services.time_service import to_iso as _datetime_to_iso
from app.version import BACKEND_VERSION

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "web"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR), context_processors=[csrf_context])


def _require_local(request: Request) -> None:
    """Loopback OR Web-session gate.

    Pre-PR-4 this was a strict loopback check (same rule as Owner Console).
    PR-4 expands it: a public-host request that already carries a valid
    ``__Host-session`` cookie (verified by :mod:`app.middleware.web_session`)
    is also accepted. The middleware stashes :class:`AuthContext` on
    ``request.state.web_session_auth`` for that case.

    Defense-in-depth: if middleware was ever bypassed (config error, route
    not reaching middleware), this dependency still requires loopback. So
    a /web request only reaches a handler when at least one of "loopback
    peer + Host" or "valid cookie verified by middleware" is true.
    """

    if getattr(request.state, "web_session_auth", None) is not None:
        # Middleware already verified the session token AND that the
        # ?ledger_id= query (if any) matches the session ledger.
        return
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
    db: Session,
    requested: str | None,
    options: list[LedgerOption] | None = None,
    *,
    request: Request | None = None,
) -> str:
    """Return the ledger_id the current /web page should operate on.

    ``requested`` comes from query / form. The result is **only** valid
    when it appears in :func:`owner_console_service.list_console_ledgers`;
    arbitrary tenant_id is rejected with a Chinese error.

    When a Web session cookie identifies the caller (set by
    :mod:`app.middleware.web_session` for public Host requests), the
    ledger is locked to the session's account regardless of any
    ``?ledger_id=`` query — the middleware has already rejected a query
    that disagreed with the session, so by the time we get here a stale
    or absent query just defers to the session ledger.
    """
    if request is not None:
        session_auth = getattr(request.state, "web_session_auth", None)
        if session_auth is not None:
            return session_auth.ledger_id

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
    return _safe_same_site_redirect_path(f"{path}?{urlencode(params)}", fallback="/web")


def _web_redirect(path: str, ledger_id: str, **extra: str) -> RedirectResponse:
    return RedirectResponse(url=_with_ledger(path, ledger_id, **extra), status_code=303)


def _safe_same_site_redirect_path(
    raw: str | None,
    *,
    allowed_roots: tuple[str, ...] = ("/web",),
    fallback: str = "",
) -> str:
    """Normalize server-side redirects to same-site paths only.

    Browsers treat several malformed URL forms more liberally than
    ``urlsplit``. Rejecting backslashes, schemes, hosts, and decoded path
    escapes keeps user-controlled form/query values out of open redirects.
    """
    if not raw:
        return fallback
    candidate = raw.strip()
    if not candidate or any(ch in candidate for ch in ("\\", "\n", "\r", "\t")):
        return fallback
    if candidate.startswith("//"):
        return fallback

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return fallback

    path = parsed.path or ""
    decoded_path = unquote(path)
    if (
        not path.startswith("/")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or ":" in decoded_path
    ):
        return fallback
    if any(decoded_path.startswith(root + "//") for root in allowed_roots):
        return fallback
    if not any(decoded_path == root or decoded_path.startswith(root + "/") for root in allowed_roots):
        return fallback
    return urlunsplit(("", "", path, parsed.query, ""))


_VALID_UI_THEMES = {"paper", "mono", "midnight"}


def _read_ui_theme(request: Request) -> str:
    raw = request.cookies.get("ui_theme")
    if raw in _VALID_UI_THEMES:
        return raw
    return "paper"


def _sidebar_counts(db: Session, ledger_id: str) -> tuple[int, int]:
    """Sidebar pending + suspected counts. Delegates to web_stats_service."""
    return web_stats_service.sidebar_counts(db, ledger_id)


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
        "home_currency_code": home_currency_code(),
        "home_currency_symbol": _currency_symbol(home_currency_code()),
    }


# ── Formatters ──────────────────────────────────────────────────────────────


def _amount_yuan(amount_cents: int | None) -> str:
    if amount_cents is None:
        return ""
    return f"{amount_cents / 100:.2f}"


def _currency_symbol(currency_code: str | None) -> str:
    code = (currency_code or home_currency_code()).upper()
    return CURRENCY_SYMBOLS.get(code, f"{code} ")


def _minor_amount_label(amount_minor: int | None, currency_code: str | None) -> str:
    if amount_minor is None:
        return ""
    code = (currency_code or home_currency_code()).upper()
    symbol = _currency_symbol(code)
    if code in NO_FRACTION_CURRENCY_CODES:
        return f"{symbol}{amount_minor:,}"
    return f"{symbol}{amount_minor / 100:,.2f}"


def _minor_amount_value(amount_minor: int | None, currency_code: str | None) -> str:
    if amount_minor is None:
        return ""
    code = (currency_code or home_currency_code()).upper()
    if code in NO_FRACTION_CURRENCY_CODES:
        return str(amount_minor)
    return f"{amount_minor / 100:.2f}"


def _home_amount_label(amount_cents: int | None, currency_code: str | None) -> str:
    return _minor_amount_label(amount_cents, currency_code or home_currency_code())


def _expense_amount_labels(expense) -> tuple[str, str | None]:
    home_code = (getattr(expense, "home_currency_code", None) or home_currency_code()).upper()
    original_code = (getattr(expense, "original_currency_code", None) or home_code).upper()
    original_minor = getattr(expense, "original_amount_minor", None)
    amount_cents = getattr(expense, "amount_cents", None)
    is_foreign = original_code != home_code
    primary = (
        _minor_amount_label(original_minor, original_code)
        if is_foreign and original_minor is not None
        else _home_amount_label(amount_cents, home_code)
    )
    if not is_foreign:
        return primary, None
    rate_date = getattr(expense, "exchange_rate_date", None)
    date_text = rate_date.isoformat() if hasattr(rate_date, "isoformat") else (str(rate_date) if rate_date else "")
    if getattr(expense, "fx_status", "") == FX_STATUS_PENDING or amount_cents is None:
        return primary, f"汇率待同步{(' · ' + date_text) if date_text else ''}"
    rate = getattr(expense, "exchange_rate_to_cny", None)
    if rate is None:
        return primary, f"汇率待同步{(' · ' + date_text) if date_text else ''}"
    meta = (
        f"≈ {_home_amount_label(amount_cents, home_code)} · "
        f"汇率 1 {original_code} = {rate} {home_code}"
    )
    if date_text:
        meta += f" · {date_text}"
    return primary, meta


def _trend14_amounts(db: Session, ledger_id: str) -> list[dict]:
    """14-day trend. Delegates to web_stats_service."""
    return web_stats_service.trend14_amounts(db, ledger_id)


def _confirmed_by_day(db: Session, ledger_id: str, month: str) -> list[dict]:
    """Per-day confirmed totals in month. Delegates to web_stats_service."""
    return web_stats_service.confirmed_by_day(db, ledger_id, month)


def _confirmed_source_breakdown(db: Session, ledger_id: str, month: str | None) -> list[dict]:
    """Source breakdown. Delegates to web_stats_service."""
    return web_stats_service.source_breakdown(db, ledger_id, month)


_SOURCE_LABELS = web_stats_service.SOURCE_LABELS


def _expense_view(expense) -> dict:
    amount_label, fx_meta = _expense_amount_labels(expense)
    home_code = getattr(expense, "home_currency_code", None) or home_currency_code()
    original_code = getattr(expense, "original_currency_code", None) or home_code
    original_minor = getattr(expense, "original_amount_minor", None)
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
        "home_currency_code": home_code,
        "original_currency_code": original_code,
        "original_amount_minor": original_minor,
        "original_amount_value": _minor_amount_value(original_minor, original_code)
        or _amount_yuan(expense.amount_cents),
        "amount_symbol": _currency_symbol(original_code),
        "is_foreign_currency": original_code != home_code,
        "exchange_rate_to_cny": getattr(expense, "exchange_rate_to_cny", None),
        "exchange_rate_date": getattr(expense, "exchange_rate_date", None),
        "exchange_rate_source": getattr(expense, "exchange_rate_source", None),
        "fx_status": getattr(expense, "fx_status", ""),
        "amount_label": amount_label,
        "fx_meta": fx_meta,
        "merchant": expense.merchant or "",
        "category": expense.category or "未分类",
        "note": expense.note or "",
        "status": expense.status,
        "expense_time": expense.expense_time.strftime("%Y-%m-%d %H:%M") if expense.expense_time else "",
        "updated_at_iso": _datetime_to_iso(getattr(expense, "updated_at", None)),
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
    recent_count = web_stats_service.recent_expense_count(db, ledger_id, week_ago)
    active_device_count = web_stats_service.active_device_count(db, ledger_id)
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
