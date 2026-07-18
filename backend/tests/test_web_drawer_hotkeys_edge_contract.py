"""Real Edge contract for drawer auth failures and scoped character shortcuts."""

from __future__ import annotations

import html
from pathlib import Path

import pytest
from test_web_edge_runtime_contract import _REPO_ROOT, _evaluate_fixture, _write_fixture

_DRAWER_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "drawer.js"
_REVIEW_HOTKEYS_JS = (
    _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "review-hotkeys.js"
)
_DRAWER_HOTKEYS_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "drawer_hotkeys_contract.html"
)


@pytest.mark.parametrize(
    "scenario",
    ["get_redirect", "mutation_redirect"],
)
def test_drawer_rejects_login_redirects_and_scopes_character_hotkeys_in_real_edge(
    tmp_path: Path,
    scenario: str,
) -> None:
    page = _write_fixture(
        tmp_path,
        f"drawer-hotkeys-{scenario}.html",
        _DRAWER_HOTKEYS_FIXTURE.read_text(encoding="utf-8")
        .replace("__SCENARIO__", scenario)
        .replace("__DRAWER_URI__", html.escape(_DRAWER_JS.as_uri(), quote=True))
        .replace(
            "__HOTKEYS_URI__",
            html.escape(_REVIEW_HOTKEYS_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name=f"edge-drawer-hotkeys-{scenario}",
    )

    assert probe == {
        "globalSelection": None,
        "firstScopedSelection": "row-1",
        "secondScopedSelection": "row-2",
        "scopedActiveElement": "row-2",
        "rowCount": 2,
        "currentRow": "row-1",
        "sessionExpired": True,
        "loginSentinelInjected": False,
        "loginPath": "/web/auth/login",
        "row1Connected": True,
        "row2Connected": True,
    }
