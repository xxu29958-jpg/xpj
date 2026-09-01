"""ui_theme cookie readers: only paper/midnight resolve; anything else → paper.

Three independent readers (web pages, owner console, HTML error pages) must
agree. The cookie only ever carries a *resolved* render theme: ``system`` is a
browser-local preference mode and is never a valid cookie value, and the
retired ``mono`` theme must fall back to the paper default like any garbage.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.errors import _error_page_theme
from app.routes.owner_console._shared import _read_ui_theme as read_owner_theme
from app.routes.web_common import _read_ui_theme as read_web_theme

_READERS = [read_web_theme, read_owner_theme, _error_page_theme]


def _request_with_cookie(value: str | None) -> SimpleNamespace:
    cookies = {} if value is None else {"ui_theme": value}
    return SimpleNamespace(cookies=cookies)


@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize(
    ("cookie", "expected"),
    [
        (None, "paper"),
        ("paper", "paper"),
        ("midnight", "midnight"),
        ("mono", "paper"),
        ("system", "paper"),
        ("garbage", "paper"),
    ],
)
def test_ui_theme_cookie_resolves_only_paper_or_midnight(reader, cookie, expected) -> None:
    assert reader(_request_with_cookie(cookie)) == expected
