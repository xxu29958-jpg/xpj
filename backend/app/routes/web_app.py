"""Compatibility host for /web route tests and legacy imports.

Most /web pages now live in focused modules such as ``web_dashboard.py``,
``web_confirmed.py``, ``web_expense_edit.py``, and ``web_media.py``.

This module intentionally re-exports ``_require_local`` and ``templates``
because existing tests override/import them from here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.web_common import _require_local, templates

__all__ = ["router", "_require_local", "templates"]

router = APIRouter(prefix="/web", tags=["web"])
