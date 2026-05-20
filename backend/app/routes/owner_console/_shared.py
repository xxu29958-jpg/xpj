"""Shared infrastructure for the owner_console route package.

Sub-routers import the templates instance, the LocalOnly dependency,
the base context builder, and the datetime filter from here. There is
no business logic in this module — only what the sub-routers need to
keep their handler bodies tight.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.fx_constants import CURRENCY_SYMBOLS, DEFAULT_HOME_CURRENCY_CODE
from app.network_boundary import require_owner_console_local
from app.version import BACKEND_VERSION


logger = logging.getLogger(__name__)


_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "owner"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _format_owner_datetime(value: object, tz: str = "Asia/Shanghai") -> str:
    """Format ISO-like datetimes for Owner Console tables.

    Accepts ``str`` (ISO-8601), ``datetime``, or anything falsy. Returns ``"—"``
    for falsy / unparseable input. Naive datetimes are assumed to be UTC; the
    output is rendered in the requested IANA timezone using ``YYYY-MM-DD HH:MM``
    so columns line up. Falls back to a simple ``[:16]`` slice if the runtime
    lacks the requested zone (e.g. minimal Windows base image without tzdata).
    """
    if not value:
        return "—"
    from datetime import datetime, timezone

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "—"
        try:
            # Python's fromisoformat handles "...+00:00"; replace trailing Z.
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw[:16].replace("T", " ")
    elif isinstance(value, datetime):
        dt = value
    else:
        return str(value)[:16].replace("T", " ")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        local = dt.astimezone(ZoneInfo(tz))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        # Unknown timezone string or corrupt datetime — fall back to raw
        # value rather than 500ing the owner index.
        local = dt
    return local.strftime("%Y-%m-%d %H:%M")


templates.env.filters["owner_datetime"] = _format_owner_datetime


def _require_local(request: Request) -> None:
    """Block non-loopback clients.

    v0.3-rc1-preflight: also reject public Host headers (Cloudflare Tunnel
    forwards to loopback so the TCP peer alone is insufficient).
    """
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


_VALID_UI_THEMES = {"paper", "mono", "midnight"}


def _read_ui_theme(request: Request) -> str:
    raw = request.cookies.get("ui_theme")
    if raw in _VALID_UI_THEMES:
        return raw
    return "paper"


def _base(request: Request, db: Session) -> dict:
    """Common template context injected into every page."""
    cfg = get_settings()
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"
    home_currency = (cfg.fx_home_currency_code or DEFAULT_HOME_CURRENCY_CODE).upper()
    return {
        "backend_version": BACKEND_VERSION,
        "upload_dir_status": upload_status,
        "ui_theme": _read_ui_theme(request),
        "home_currency_code": home_currency,
        "home_currency_symbol": CURRENCY_SYMBOLS.get(home_currency, f"{home_currency} "),
    }
