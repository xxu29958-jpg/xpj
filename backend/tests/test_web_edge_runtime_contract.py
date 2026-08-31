"""Real Edge consumer gate for the /web bulk bar (批选模式 + 异步反馈 aria 语义).

#218 C5a: only the bulk-bar slice lives here for now — the responsive-shell /
dashboard-refresh / confirm-modal consumer gates ride in with their own slices.
Skips cleanly on hosts without Microsoft Edge (CI lane that pins a real browser
runs it for real).
"""

from __future__ import annotations

import html
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BULK_BAR_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "bulk-bar.js"
_BULK_BAR_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "bulk_bar_announcement_contract.html"
_BULK_EMPTY_RELOAD_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "bulk_bar_empty_reload_contract.html"
)
_DRAWER_BULK_OCC_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "drawer_bulk_occ_contract.html"
_DRAWER_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "drawer.js"
_REVIEW_KEYBOARD_FIXTURE = (
    _REPO_ROOT / "backend" / "tests" / "fixtures" / "review_keyboard_contract.html"
)
_REVIEW_KEYBOARD_JS = (
    _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "review-keyboard.js"
)
_EDGE_CDP: ModuleType | None = None


def _discover_edge() -> str:
    if sys.platform != "win32":
        pytest.skip("real Web consumer gate requires Windows Microsoft Edge")

    candidates = [shutil.which("msedge")]
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("real Web consumer gate requires Microsoft Edge")


def _edge_cdp() -> ModuleType:
    """Reuse only Desktop's dependency-free Edge transport, not its product fixture."""
    global _EDGE_CDP
    if _EDGE_CDP is not None:
        return _EDGE_CDP
    module_path = _REPO_ROOT / "desktop" / "tests" / "_edge_cdp.py"
    spec = importlib.util.spec_from_file_location("_ticketbox_shared_edge_cdp", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _EDGE_CDP = module
    return module


def _write_fixture(tmp_path: Path, name: str, body: str) -> Path:
    page = tmp_path / name
    page.write_text("<!doctype html>\n" + body, encoding="utf-8")
    return page


def _evaluate_fixture(
    tmp_path: Path,
    *,
    page: Path,
    width: int,
    height: int,
    profile_name: str,
) -> dict[str, object]:
    value = _edge_cdp().evaluate_page(
        _discover_edge(),
        profile=tmp_path / profile_name,
        url=page.as_uri(),
        width=width,
        height=height,
        expression="window.__webConsumerProbe || undefined",
    )
    assert isinstance(value, dict)
    return value


def _assert_bulk_queue_exhaustion_reloads_authoritative_page(tmp_path: Path) -> None:
    page = _write_fixture(
        tmp_path,
        "bulk-bar-empty-reload-contract.html",
        _BULK_EMPTY_RELOAD_FIXTURE.read_text(encoding="utf-8").replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-bulk-bar-empty-reload-contract",
    )
    assert probe == {
        "authoritativeReloaded": True,
        "navigationType": "reload",
    }


def _assert_review_keyboard_behaves_in_real_edge(tmp_path: Path) -> None:
    page = _write_fixture(
        tmp_path,
        "review-keyboard-contract.html",
        _REVIEW_KEYBOARD_FIXTURE.read_text(encoding="utf-8").replace(
            "__REVIEW_KEYBOARD_URI__",
            html.escape(_REVIEW_KEYBOARD_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-review-keyboard-contract",
    )
    assert probe == {
        "down": {"active": "row-3", "prevented": True},
        "up": {"active": "row-1", "prevented": True},
        "end": {"active": "row-3", "prevented": True},
        "home": {"active": "row-1", "prevented": True},
        "j": {"active": "row-1", "prevented": False},
        "k": {"active": "row-1", "prevented": False},
        "composing": {"active": "row-1", "prevented": False},
        "inputArrow": {"active": "editor", "prevented": False},
        "drawerArrow": {"active": "row-1", "prevented": False},
        "confirm": {"active": "row-1", "prevented": True},
        "confirmCalls": 1,
    }


def test_bulk_async_feedback_has_announcement_semantics_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "bulk-bar-announcement-contract.html",
        _BULK_BAR_FIXTURE.read_text(encoding="utf-8").replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-bulk-bar-announcement-contract",
    )

    assert probe["beforeEnhancement"] == {
        "checkAllHidden": True,
        "enhanced": False,
    }
    batch_mode = probe["batchMode"]
    assert batch_mode == {
        "enhanced": True,
        "checkAllHidden": False,
        "ariaDisabled": None,
        "tabIndex": None,
        "ariaCurrent": "true",
        "checkboxChecked": True,
        "checkboxTabIndex": 0,
        "navigationPrevented": False,
        "locationHash": "#row-1-navigation",
    }

    cleared = probe["cleared"]
    assert cleared == {
        "ariaDisabled": None,
        "hasTabIndex": False,
        "ariaCurrent": "true",
        "checkboxChecked": False,
        "activeElement": "check-1",
        "clearButtonType": "button",
        "formActive": False,
    }

    success = probe["successWithUndo"]
    assert success["role"] == "status"
    assert success["live"] == "polite"
    assert success["atomic"] == "true"
    assert "已确认 1 条流水。" in success["message"]
    assert success["undoLabel"] == "撤销刚才的批量操作"
    assert success["undoButtonLabel"] == "撤销刚才处理的 1 条流水"

    failure = probe["failure"]
    assert failure["role"] == "alert"
    assert failure["live"] == "assertive"
    assert failure["atomic"] == "true"
    assert failure["message"] == "批量操作失败，请重试。"
    _assert_bulk_queue_exhaustion_reloads_authoritative_page(tmp_path)


def test_drawer_save_resynchronizes_selected_row_occ_consumers_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "drawer-bulk-occ-contract.html",
        _DRAWER_BULK_OCC_FIXTURE.read_text(encoding="utf-8")
        .replace(
            "__BULK_BAR_URI__",
            html.escape(_BULK_BAR_JS.as_uri(), quote=True),
        )
        .replace(
            "__DRAWER_URI__",
            html.escape(_DRAWER_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-drawer-bulk-occ-contract",
    )

    assert probe == {
        "drawerOpenedWhileSelected": True,
        "checkboxChecked": True,
        "checkboxDataRowVersion": "12",
        "checkboxValue": "1:12",
        "quickConfirmSnapshot": "1:12",
        "bulkTokens": ["12"],
        "selectedCount": "1",
    }
    _assert_review_keyboard_behaves_in_real_edge(tmp_path)
