"""Shared helpers for /web routes (v0.4-alpha3 slice 2 structure split).

This module hosts everything that previously lived as helpers in
``web_app.py``: the loopback gate, ledger selector, formatters, and the
expense view-model. Each /web route module imports from here so we keep a
single source of truth for ledger isolation rules and amount/time/string
formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_PENDING
from app.middleware.csrf import csrf_context
from app.network_boundary import require_owner_console_local
from app.services import backup_service, bill_split_service, web_stats_service
from app.services import owner_console_service as owner_svc
from app.services.budget_service import get_monthly_budget
from app.services.currency_common import (
    currency_input_metadata,
    currency_symbol,
    major_amount_to_minor,
    minor_amount_label,
    minor_amount_major_number,
    minor_amount_value,
    minor_unit_digits,
)
from app.services.dashboard_service import list_dashboard_cards
from app.services.exchange_rate_service import home_currency_code
from app.services.expense_service import ledger_has_any_expense, list_pending
from app.services.goal_service import list_goals
from app.services.identity_service import (
    WEB_SESSION_TTL_SECONDS,
    lock_and_revalidate_web_session_principal,
)
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import list_recurring_items
from app.services.spending_contract_service import accounting_zone
from app.services.stats_service import monthly_stats
from app.services.time_service import (
    current_month,
    ensure_utc,
    now_utc,
    parse_month_label,
)
from app.services.time_service import to_iso as _datetime_to_iso
from app.version import BACKEND_VERSION, STATIC_ASSET_VERSION

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "web"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR), context_processors=[csrf_context])
# ADR-0038 PR-2e: register ``to_iso`` so /web templates can render
# ORM ``updated_at`` values (datetime) into the canonical ISO-Z form
# the hidden ``expected_row_version`` form fields use. Without this
# filter the template would emit Python's ``str(datetime)`` (no T
# separator, no Z), which ``parse_form_row_version_token`` rejects.
templates.env.filters["to_iso"] = _datetime_to_iso

_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def parse_form_row_version_token(value: str) -> int | None:
    """ADR-0041: parse the hidden ``expected_row_version`` form field as int.

    Returns ``None`` when the field is blank or malformed; callers surface the
    same "页面已过期/账单已在其它端被修改" UX as a stale-write 409. ``row_version``
    is a monotonic integer — no ISO/tz normalisation (that was the ``updated_at``
    era); a non-numeric value is simply treated as a stale/absent token.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


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


def _project_session_ledger_options(
    options: list[LedgerOption] | None,
    session_auth,
) -> None:
    """Project the ledger selector to the single ledger authorized by a Web session.

    ``_list_ledger_options`` is deliberately the loopback Owner Console read
    surface, so it can contain every ledger visible to the local owner account.
    A public Web session is a different principal: exposing those rows in the
    rendered selector would disclose unrelated ledger ids and names even though
    the middleware correctly blocks cross-ledger data reads.

    Mutate the caller-owned list in place because every /web route resolves the
    selected ledger before passing that same list to ``_base_ctx``.  Rebuild the
    option from the authenticated context so both the visible name and role come
    from the session-bound ledger, never from the local owner's projection.
    """
    if options is None:
        return
    matched = next(
        (opt for opt in options if opt.ledger_id == session_auth.ledger_id),
        None,
    )
    options[:] = [
        LedgerOption(
            ledger_id=session_auth.ledger_id,
            name=session_auth.ledger_name,
            role=session_auth.role,
            is_default=matched.is_default if matched is not None else False,
            pending_count=matched.pending_count if matched is not None else 0,
            confirmed_count=matched.confirmed_count if matched is not None else 0,
        )
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

    Unsafe methods additionally revalidate that middleware snapshot under the
    shared identity-lifecycle transaction lock. This happens inside the route
    function, after request-body parsing, and keeps the lock through the
    command's first commit/rollback.
    """
    if request is not None:
        session_auth = getattr(request.state, "web_session_auth", None)
        if session_auth is not None:
            if getattr(request, "method", "GET").upper() not in _SAFE_HTTP_METHODS:
                session_auth = lock_and_revalidate_web_session_principal(
                    db,
                    session_auth,
                    platform=getattr(request.state, "web_session_platform", ""),
                    ttl_seconds=WEB_SESSION_TTL_SECONDS,
                )
                request.state.web_session_auth = session_auth
            # ENGINEERING_RULES §14: a Web session is bound to one ledger. Keep
            # the Owner Console's other ledger ids/names out of the HTML context,
            # and use the paired principal's role for both rendering and writes.
            _project_session_ledger_options(options, session_auth)
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
    # Deny if the ledger isn't an explicit option for this caller: never fall
    # back to options[0] (a different ledger that may be writable) for a WRITE
    # gate. The role on the matching option already reflects the Web session
    # (stamped by _resolve_selected_ledger_id) vs. the owner console.
    selected = next((opt for opt in options if opt.ledger_id == ledger_id), None)
    if selected is None or selected.role not in {"owner", "member"}:
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
    if not path.startswith("/") or decoded_path.startswith("//") or "\\" in decoded_path or ":" in decoded_path:
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
    home_code = home_currency_code()
    return {
        "backend_version": BACKEND_VERSION,
        "asset_version": STATIC_ASSET_VERSION,
        "request": request,
        "ledger_options": options,
        "selected_ledger_id": selected_ledger_id,
        "selected_ledger_name": selected.name,
        "selected_ledger_role": selected.role,
        "selected_ledger_is_default": selected.is_default,
        "is_viewer": selected.role == "viewer",
        "can_write": selected.role in ("owner", "member"),
        "has_web_session": (getattr(request.state, "web_session_auth", None) is not None),
        "web_session_platform": getattr(request.state, "web_session_platform", None),
        "page_title": page_title,
        "ui_theme": _read_ui_theme(request),
        "show_month_picker": show_month_picker,
        "selected_month": selected_month,
        "pending_count": pending_count,
        "suspected_duplicate_count": suspected_count,
        "home_currency_code": home_code,
        "home_currency_symbol": _currency_symbol(home_code),
        "home_currency_input": _currency_input_view(home_code),
    }


# ── Formatters ──────────────────────────────────────────────────────────────


def _amount_yuan(amount_cents: int | None) -> str:
    """Legacy Web projection name for a home-currency major-unit value.

    ``*_yuan`` keys are kept for template/JSON compatibility, but their value
    is currency-neutral and follows the configured home currency's minor digits.
    New projections should prefer ``*_major`` or ``*_value`` names.
    """

    return _minor_amount_value(amount_cents, home_currency_code())


def _month_display_label(value: str | None, *, fallback: str = "所选月份") -> str:
    parsed = parse_month_label(value)
    if parsed is None:
        return fallback
    year, month = parsed
    return f"{year} 年 {month} 月"


def _calendar_date_label(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        normalized = ensure_utc(value)
        if normalized is None:
            return ""
        calendar_date = normalized.astimezone(accounting_zone()).date()
    else:
        calendar_date = value
    return f"{calendar_date.year} 年 {calendar_date.month} 月 {calendar_date.day} 日"


def _expense_time_local_input(value) -> str:
    """Render a stored UTC ``expense_time`` into the ``YYYY-MM-DDTHH:MM`` shape an
    ``<input type="datetime-local">`` expects, in the accounting timezone
    (Asia/Shanghai) — the same wall-clock the rest of /web shows (see
    ``web_bill_split._fmt_local``). Empty when unset.

    Storage stays UTC: this is only the prefill side. ``web_save`` parses the
    submitted value back from accounting-tz to UTC (assume-local), so the
    round-trip is consistent and never drifts 8h. Keeping the conversion in one
    helper (not the template) honours ENGINEERING_RULES §14.
    """
    value = ensure_utc(value)
    if value is None:
        return ""
    return value.astimezone(accounting_zone()).strftime("%Y-%m-%dT%H:%M")


def _currency_symbol(currency_code: str | None) -> str:
    return currency_symbol(currency_code or home_currency_code())


def _currency_input_view(currency_code: str | None) -> dict[str, object]:
    """Currency-neutral major-unit input metadata for HTML number fields."""
    return currency_input_metadata(currency_code or home_currency_code())


def _minor_amount_label(amount_minor: int | None, currency_code: str | None) -> str:
    return minor_amount_label(amount_minor, currency_code or home_currency_code())


def _minor_amount_value(amount_minor: int | None, currency_code: str | None) -> str:
    return minor_amount_value(amount_minor, currency_code or home_currency_code())


def _minor_amount_number(
    amount_minor: int | None,
    currency_code: str | None,
) -> int | float | None:
    return minor_amount_major_number(amount_minor, currency_code or home_currency_code())


def _parse_major_amount(
    raw: str,
    *,
    label: str,
    currency_code: str | None = None,
    allow_negative: bool = False,
    required: bool = False,
    empty_value: int | None = None,
) -> int | None:
    """Parse an HTML major-unit amount with currency-derived fraction digits."""

    text = (raw or "").strip()
    if not text:
        if required:
            raise AppError("invalid_request", f"请填写{label}。", status_code=422)
        return empty_value
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise AppError("invalid_request", f"{label}不是合法金额。", status_code=422) from exc
    if not amount.is_finite():
        raise AppError("invalid_request", f"{label}不是合法金额。", status_code=422)
    if amount < 0 and not allow_negative:
        raise AppError("invalid_request", f"{label}不能为负数。", status_code=422)
    code = (currency_code or home_currency_code()).upper()
    digits = minor_unit_digits(code)
    quantum = Decimal(1).scaleb(-digits)
    try:
        exactly_representable = amount == amount.quantize(quantum)
    except InvalidOperation:
        exactly_representable = False
    if not exactly_representable:
        detail = "只能填写整数" if digits == 0 else f"最多填写 {digits} 位小数"
        raise AppError(
            "invalid_request",
            f"{label}按 {code} {detail}。",
            status_code=422,
        )
    return major_amount_to_minor(
        amount,
        code,
        allow_negative=allow_negative,
    )


def _home_amount_label(amount_cents: int | None, currency_code: str | None) -> str:
    return _minor_amount_label(amount_cents, currency_code or home_currency_code())


def _amount_segments(amount_cents: int | None, currency_code: str | None) -> dict[str, str]:
    """Editorial split of a home-currency amount into ``cur`` / ``int`` / ``dec`` for
    the premium hero rendering (照 ``confirmed.css .ledger-hero .lh-amt``: a small muted
    currency mark + a large integer + a small muted decimal tail).

    ``dec`` is ``""`` for no-fraction currencies (mirrors ``_minor_amount_label``'s
    fraction handling); the thousands-separated integer matches the rest of /web's debt
    labels. Keeping the split here — not in the template — honours §14: the template just
    drops the three pieces into spans.
    """
    code = (currency_code or home_currency_code()).upper()
    digits = minor_unit_digits(code)
    amount = int(amount_cents or 0)
    scale = 10**digits
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), scale)
    decimal = "" if digits == 0 else f".{fraction:0{digits}d}"
    return {"cur": _currency_symbol(code), "int": f"{sign}{whole:,}", "dec": decimal}


def _home_amount_value(
    amount_minor: int | None,
    currency_code: str | None = None,
) -> str:
    return _minor_amount_value(amount_minor, currency_code or home_currency_code())


def _home_amount_label_value(
    amount_minor: int | None,
    currency_code: str | None = None,
) -> str:
    return _minor_amount_label(amount_minor, currency_code or home_currency_code())


# Direct-template consumers (search/rules/import-batch/report aggregates) receive
# raw minor-unit columns. Keep their formatting on the same authority as route VMs.
templates.env.globals["home_amount_value"] = _home_amount_value
templates.env.globals["home_amount_label"] = _home_amount_label_value


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
        return primary, f"{original_code} · 汇率待同步{(' · ' + date_text) if date_text else ''}"
    rate = getattr(expense, "exchange_rate_to_cny", None)
    if rate is None:
        return primary, f"{original_code} · 汇率待同步{(' · ' + date_text) if date_text else ''}"
    meta = f"{original_code} · ≈ {_home_amount_label(amount_cents, home_code)} · 汇率 1 {original_code} = {rate} {home_code}"
    if date_text:
        meta += f" · {date_text}"
    return primary, meta


def _trend14_amounts(db: Session, ledger_id: str) -> list[dict]:
    """14-day trend. Delegates to web_stats_service."""
    return [_home_major_projection(row) for row in web_stats_service.trend14_amounts(db, ledger_id)]


def _confirmed_by_day(db: Session, ledger_id: str, month: str) -> list[dict]:
    """Per-day confirmed totals in month. Delegates to web_stats_service."""
    return [
        _home_major_projection(row)
        for row in web_stats_service.confirmed_by_day(db, ledger_id, month)
    ]


def _confirmed_source_breakdown(db: Session, ledger_id: str, month: str | None) -> list[dict]:
    """Source breakdown. Delegates to web_stats_service."""
    return web_stats_service.source_breakdown(db, ledger_id, month)


def _home_major_projection(row: dict) -> dict:
    """Attach currency-neutral major-unit fields to a raw minor-unit row."""

    amount_minor = int(row.get("amount_cents") or 0)
    amount_major = _minor_amount_number(amount_minor, home_currency_code())
    return {
        **row,
        "amount_major": amount_major,
        "amount_value": _amount_yuan(amount_minor),
        # Legacy JS/template compatibility; no longer semantically fixed yuan.
        "amount_yuan": amount_major,
    }


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
    source_label = web_stats_service.source_label(source_raw, "未知")
    # ADR-0029: a received split expense is itself the foot of a split chain and
    # cannot be re-split (服务端 ``create_invitation`` 也会 split_chain_not_allowed
    # 兜底)。发起卡据此隐藏。
    is_split_received = source_raw == bill_split_service.SPLIT_RECEIVED_SOURCE
    needs_amount = expense.amount_cents is None
    needs_merchant = not (expense.merchant or "").strip()
    is_duplicate = (getattr(expense, "duplicate_status", None) or "") == "suspected"
    return {
        "id": expense.id,
        "amount_yuan": _amount_yuan(expense.amount_cents),
        "amount_cents": expense.amount_cents,
        "home_currency_code": home_code,
        "original_currency_code": original_code,
        "home_currency_input": _currency_input_view(home_code),
        "original_currency_input": _currency_input_view(original_code),
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
        "tags": getattr(expense, "tags", None) or "",
        "status": expense.status,
        "expense_time": expense.expense_time.strftime("%Y-%m-%d %H:%M") if expense.expense_time else "",
        # datetime-local prefill in accounting tz (storage stays UTC); the edit
        # form's <input type="datetime-local"> binds to this, not the display
        # string above (which is the legacy raw-UTC label kept for list views).
        "expense_time_local": _expense_time_local_input(getattr(expense, "expense_time", None)),
        "updated_at_iso": _datetime_to_iso(getattr(expense, "updated_at", None)),
        # ADR-0041: row_version is the OCC token the hidden form fields carry now
        # (updated_at_iso kept for any display use).
        "row_version": getattr(expense, "row_version", None),
        "created_at": expense.created_at.strftime("%Y-%m-%d %H:%M") if expense.created_at else "",
        "has_image": has_image,
        "image_state": image_state,
        "duplicate_status": expense.duplicate_status,
        "is_duplicate": is_duplicate,
        "needs_amount": needs_amount,
        "needs_merchant": needs_merchant,
        "source_label": source_label,
        "is_split_received": is_split_received,
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


def _budget_top_rows(budget) -> list[dict]:
    """Top per-category budget rows for the dashboard 预算 card progress bars.

    Reuses ``budget.category_budgets`` (already computed by ``budget_service`` —
    no new aggregation): per category we have the limit (``amount_cents``),
    used (``spent_amount_cents``) and overspend. ``percent`` is used/limit
    capped at 100 for the bar width; ``overspent_yuan`` carries the
    over-the-limit amount so the template/JS can show a currency-aware excess. Sorted by spend
    desc so the most-used categories surface first, top 3."""
    rows = sorted(
        budget.category_budgets,
        key=lambda c: c.spent_amount_cents,
        reverse=True,
    )[:3]
    out: list[dict] = []
    for category in rows:
        limit_cents = int(category.amount_cents)
        spent_cents = int(category.spent_amount_cents)
        percent = int(round(spent_cents * 100 / limit_cents)) if limit_cents > 0 else 0
        out.append(
            {
                "name": category.category,
                "limit_yuan": _amount_yuan(limit_cents),
                "spent_yuan": _amount_yuan(spent_cents),
                "overspent_yuan": _amount_yuan(int(category.overspent_amount_cents)),
                "percent": min(percent, 100),
                "is_over": category.overspent_amount_cents > 0,
            }
        )
    return out


def _goals_top_rows(goals) -> list[dict]:
    """Top goal rows for the dashboard 目标 card progress bars.

    Reuses ``list_goals`` output (already carries ``progress_percent`` /
    ``progress_state`` from ``goal_service`` — no new aggregation). The bar
    width is ``progress_percent`` capped at 100; ``state`` drives the bar
    colour (over_limit → danger, near_limit → brand-primary, 对齐 dashboard
    bar 调色板——同卡上方的 pill 用 warn 琥珀,bar 与既有 cat-bar 同语自洽). Sorted by
    progress desc so the most-at-risk goals surface first, top 3."""
    rows = sorted(goals, key=lambda g: g.progress_percent, reverse=True)[:3]
    return [
        {
            "name": goal.name,
            "target_yuan": _amount_yuan(int(goal.target_amount_cents)),
            "spent_yuan": _amount_yuan(int(goal.spent_amount_cents)),
            "percent": min(int(goal.progress_percent), 100),
            "state": goal.progress_state,
        }
        for goal in rows
    ]


def _dashboard_budget_goals_block(budget, goals) -> dict:
    """budget/goals 两卡的 ctx 片段(从 ``_dashboard_cards`` 拆出守 80 行债线)。"""
    goal_risk_count = sum(1 for goal in goals if goal.progress_state in {"near_limit", "over_limit"})
    return {
        "budget_configured": budget.configured,
        "budget_total_yuan": _amount_yuan(int(budget.total_amount_cents)),
        "budget_remaining_yuan": _amount_yuan(int(budget.remaining_amount_cents)),
        "budget_overspent_yuan": _amount_yuan(int(budget.overspent_amount_cents)),
        "budget_is_over": budget.remaining_amount_cents < 0,
        "budget_top": _budget_top_rows(budget),
        "goals_count": len(goals),
        "goals_risk_count": goal_risk_count,
        "goals_top": _goals_top_rows(goals),
    }


def _dashboard_cards(db: Session, ledger_id: str) -> dict:
    pending_rows = list_pending(db, ledger_id)
    pending_count = len(pending_rows)
    needs_amount = sum(1 for e in pending_rows if e.amount_cents is None)
    needs_merchant = sum(1 for e in pending_rows if not (e.merchant or "").strip())
    suspected = sum(1 for e in pending_rows if (getattr(e, "duplicate_status", None) or "") == "suspected")
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
        **_dashboard_budget_goals_block(budget, goals),
        "recent_count": recent_count,
        "active_device_count": active_device_count,
        "backup_available": latest_backup is not None,
        "backup_age_days": backup_age_days,
    }


def _dashboard_category_share(db: Session, selected_id: str) -> list[dict]:
    month = current_month("Asia/Shanghai")
    stats = monthly_stats(db, month, selected_id, timezone_name="Asia/Shanghai")
    rows = []
    for item in stats.get("by_category", [])[:6]:
        amount_minor = int(item["amount_cents"])
        amount_major = _minor_amount_number(amount_minor, home_currency_code())
        rows.append(
            {
                "name": item["category"],
                "amount_major": amount_major,
                "amount_value": _amount_yuan(amount_minor),
                # Legacy dashboard/chart key; value now follows home-currency digits.
                "amount_yuan": amount_major,
                "amount_cents": amount_minor,
                "count": int(item["count"]),
            }
        )
    return rows


def _dashboard_data_payload(db: Session, selected_id: str) -> dict:
    cards = _dashboard_cards(db, selected_id)
    return {
        "selected_ledger_id": selected_id,
        "month": cards["month"],
        "has_any_expense": ledger_has_any_expense(db, selected_id),
        "cards": cards,
        "visible_layout": [item for item in cards["layout"] if item["visible"]],
        "trend14": _trend14_amounts(db, selected_id),
        "category_share": _dashboard_category_share(db, selected_id),
    }
