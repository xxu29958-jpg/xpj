"""Real Edge consumer gates for the responsive Web shell and dashboard refresh."""

from __future__ import annotations

import html
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOKENS_CSS = _REPO_ROOT / "backend" / "app" / "static" / "shared" / "tokens.css"
_SHELL_CSS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "product" / "shell.css"
_DASHBOARD_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "dashboard.js"
_CONFIRM_MODAL_JS = _REPO_ROOT / "backend" / "app" / "static" / "shared" / "confirm-modal.js"
_CONFIRM_MODAL_CSS = _REPO_ROOT / "backend" / "app" / "static" / "shared" / "confirm-modal.css"
_BULK_BAR_JS = _REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "bulk-bar.js"
_EDGE_CDP: ModuleType | None = None
_PRIMARY_TARGETS = [
    "/web/pending",
    "/web/confirmed",
    "/web/debts",
    "/web/budgets",
    "/web/overview",
]


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


def _primary_links() -> str:
    labels = ("收件", "流水", "往来", "计划", "洞察")
    links: list[str] = []
    for index, (target, label) in enumerate(zip(_PRIMARY_TARGETS, labels, strict=True)):
        active_class = " active" if index == 1 else ""
        current = ' aria-current="location"' if index == 1 else ""
        links.append(
            f'<a class="nav-item{active_class}" href="{target}"{current}><span>{label}</span></a>',
        )
    return "".join(links)


def _responsive_fixture(tmp_path: Path, *, width: int, height: int) -> Path:
    links = _primary_links()
    tokens_uri = html.escape(_TOKENS_CSS.as_uri(), quote=True)
    shell_uri = html.escape(_SHELL_CSS.as_uri(), quote=True)
    return _write_fixture(
        tmp_path,
        f"web-shell-{width}x{height}.html",
        f"""<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{tokens_uri}">
  <link rel="stylesheet" href="{shell_uri}">
</head>
<body>
  <div class="product-app">
    <aside class="sidebar">
      <nav class="mobile-primary-nav" aria-label="产品领域">{links}</nav>
      <nav class="desktop-nav" aria-label="产品导航">
        <div class="nav-primary">{links}</div>
      </nav>
    </aside>
    <main class="product-workspace">真实 Web 消费者门禁</main>
  </div>
  <script>
    (() => {{
      const mobile = document.querySelector(".mobile-primary-nav");
      const desktop = document.querySelector(".desktop-nav");
      const mobileDisplay = getComputedStyle(mobile).display;
      const desktopDisplay = getComputedStyle(desktop).display;
      const visibleNav = mobileDisplay !== "none" ? mobile : desktop;
      const visibleTargets = [...visibleNav.querySelectorAll("a")].filter((node) => {{
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }});
      const targetRects = visibleTargets.map((node) => node.getBoundingClientRect());
      window.__webConsumerProbe = {{
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        mobileDisplay,
        desktopDisplay,
        targetCount: visibleTargets.length,
        targets: visibleTargets.map((node) => node.getAttribute("href")),
        activeCount: visibleTargets.filter(
          (node) => node.classList.contains("active") &&
            node.getAttribute("aria-current") === "location"
        ).length,
        minimumTargetWidth: Math.min(...targetRects.map((rect) => rect.width)),
        minimumTargetHeight: Math.min(...targetRects.map((rect) => rect.height))
      }};
    }})();
  </script>
</body>
</html>""",
    )


@pytest.mark.parametrize(
    ("width", "height", "expected_mobile", "expected_desktop"),
    [
        (390, 844, "grid", "none"),
        (768, 1024, "grid", "none"),
        (1440, 900, "none", "flex"),
    ],
    ids=["compact-phone", "tablet", "desktop"],
)
def test_web_primary_navigation_is_real_edge_responsive(
    tmp_path: Path,
    width: int,
    height: int,
    expected_mobile: str,
    expected_desktop: str,
) -> None:
    page = _responsive_fixture(tmp_path, width=width, height=height)
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=width,
        height=height,
        profile_name=f"edge-shell-{width}x{height}",
    )

    minimum_width = probe.pop("minimumTargetWidth")
    minimum_height = probe.pop("minimumTargetHeight")
    assert isinstance(minimum_width, (int, float))
    assert isinstance(minimum_height, (int, float))
    assert minimum_width >= 24
    assert minimum_height >= 24
    assert probe == {
        "viewportWidth": width,
        "viewportHeight": height,
        "mobileDisplay": expected_mobile,
        "desktopDisplay": expected_desktop,
        "targetCount": 5,
        "targets": _PRIMARY_TARGETS,
        "activeCount": 1,
    }


_SUCCESS_PAYLOAD = {
    "selected_ledger_id": "owner",
    "has_any_expense": True,
    "cards": {
        "month": "2026-07",
        "total_amount_yuan": "123.45",
        "previous_total_amount_yuan": "100.00",
        "pending_count": 2,
        "needs_amount_count": 1,
        "goals_count": 1,
        "goals_top": [{"name": "餐饮", "percent": 25, "state": "on_track"}],
    },
    # Deliberately reversed: the browser must group by the fixed product lanes.
    "visible_layout": [
        {"key": "goals", "visible": True, "position": 0},
        {"key": "monthly_spend", "visible": True, "position": 1},
        {"key": "pending", "visible": True, "position": 2},
    ],
    "category_share": [],
}


_CONFIRM_MODAL_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "confirm_modal_contract.html"
_BULK_BAR_FIXTURE = _REPO_ROOT / "backend" / "tests" / "fixtures" / "bulk_bar_announcement_contract.html"
def _fetch_stub(scenario: str) -> str:
    if scenario == "deferred":
        return "window.fetch = function () { return new Promise(function () {}); };"
    if scenario == "rejected":
        return 'window.fetch = function () { return Promise.reject(new Error("offline")); };'
    payload = json.dumps(_SUCCESS_PAYLOAD, ensure_ascii=False)
    return f"""window.fetch = function () {{
  return Promise.resolve({{
    ok: true,
    json: function () {{ return Promise.resolve({payload}); }}
  }});
}};"""


def _dashboard_fixture(tmp_path: Path, scenario: str) -> Path:
    dashboard_uri = html.escape(_DASHBOARD_JS.as_uri(), quote=True)
    delay_ms = 2200 if scenario == "deferred" else 80
    return _write_fixture(
        tmp_path,
        f"web-dashboard-{scenario}.html",
        f"""<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body>
  <section id="dashboard-app" data-dashboard-url="/dashboard" data-dashboard-state="server">
    <section data-dashboard-status hidden>
      <strong data-dashboard-status-title></strong>
      <span data-dashboard-status-body></span>
      <button type="button" data-dashboard-retry hidden>重试</button>
    </section>
    <div data-dashboard-rendered>
      <article id="trusted-node" data-server-rendered="true">可信 SSR 账面结果</article>
    </div>
  </section>
  <script>
    window.TicketboxWeb = {{
      dashboardUrl: function (path) {{ return path; }},
      homeCurrencySymbol: function () {{ return "¥"; }}
    }};
    {_fetch_stub(scenario)}
  </script>
  <script src="{dashboard_uri}"></script>
  <script>
    (() => {{
      const trusted = document.getElementById("trusted-node");
      const target = document.querySelector("[data-dashboard-rendered]");
      window.TicketboxWeb.initDashboard();
      setTimeout(() => {{
        window.__webConsumerProbe = {{
          state: document.getElementById("dashboard-app").getAttribute("data-dashboard-state"),
          trustedConnected: trusted.isConnected,
          trustedFirst: target.firstElementChild === trusted,
          lanes: [...target.querySelectorAll(".insight-lane-heading h2")]
            .map((node) => node.textContent),
          cards: [...target.querySelectorAll("[data-dashboard-card]")]
            .map((node) => node.getAttribute("data-dashboard-card"))
        }};
      }}, {delay_ms});
    }})();
  </script>
</body>
</html>""",
    )


@pytest.mark.parametrize(
    ("scenario", "expected_state", "trusted_connected"),
    [
        ("deferred", "slow", True),
        ("rejected", "fallback", True),
        ("success", "ready", False),
    ],
)
def test_dashboard_refresh_preserves_ssr_until_real_edge_success(
    tmp_path: Path,
    scenario: str,
    expected_state: str,
    trusted_connected: bool,
) -> None:
    page = _dashboard_fixture(tmp_path, scenario)
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1440,
        height=900,
        profile_name=f"edge-dashboard-{scenario}",
    )

    assert probe["state"] == expected_state
    assert probe["trustedConnected"] is trusted_connected
    assert probe["trustedFirst"] is trusted_connected
    if scenario == "success":
        assert probe["lanes"] == ["需处理", "本月事实", "计划状态"]
        assert probe["cards"] == ["pending", "monthly_spend", "goals"]
    else:
        assert probe["lanes"] == []
        assert probe["cards"] == []


def _assert_confirm_modal_probe(probe: dict) -> None:
    assert probe["derived"] == {
        "labelledBy": "tb-confirm-title",
        "describedBy": "tb-confirm-message",
        "ariaModal": "true",
        "role": "alertdialog",
        "titleId": "tb-confirm-title",
        "messageId": "tb-confirm-message",
        "title": "确认永久删除",
        "action": "永久删除",
        "titleVisible": True,
        "safestFocus": True,
        "dangerClass": True,
        "dangerVisual": True,
    }
    assert probe["cancelRestoredFocus"] is True
    assert probe["confirmed"] == {
        "submissions": [
            {
                "name": "action",
                "value": "delete",
                "formAction": "https://example.invalid/permanent-delete",
                "csrfToken": "edge-contract-token",
            },
        ],
        "restoredFocus": True,
    }
    assert probe["overridden"] == {
        "role": None,
        "title": "应用这条规则？",
        "action": "应用规则",
        "primaryFocus": True,
        "dangerClass": False,
    }
    assert probe["overrideCancelRestoredFocus"] is True
    assert probe["escapeWasNotBlocked"] is True
    assert probe["escapeRestoredFocus"] is True
    assert probe["classDerivedDanger"] == {
        "role": "alertdialog",
        "safestFocus": True,
        "dangerClass": True,
    }
    assert probe["classDangerRestoredFocus"] is True
    assert probe["legacyConfirmed"] == {
        "submission": {
            "name": "action",
            "value": "delete",
            "formAction": "https://example.invalid/permanent-delete",
            "csrfToken": "edge-contract-token",
        },
        "restoredFocus": True,
    }
    assert probe["fallbackMessage"] == "将规则应用到待确认账单。"
    assert probe["overrideAccepted"] == 1
    assert probe["csrfSubmitEvents"] == 5


def test_confirm_modal_preserves_native_action_and_safe_focus_in_real_edge(
    tmp_path: Path,
) -> None:
    page = _write_fixture(
        tmp_path,
        "confirm-modal-contract.html",
        _CONFIRM_MODAL_FIXTURE.read_text(encoding="utf-8")
        .replace(
            "__TOKENS_CSS_URI__",
            html.escape(_TOKENS_CSS.as_uri(), quote=True),
        )
        .replace(
            "__CONFIRM_MODAL_CSS_URI__",
            html.escape(_CONFIRM_MODAL_CSS.as_uri(), quote=True),
        )
        .replace(
            "__CONFIRM_MODAL_URI__",
            html.escape(_CONFIRM_MODAL_JS.as_uri(), quote=True),
        ),
    )
    probe = _evaluate_fixture(
        tmp_path,
        page=page,
        width=1024,
        height=768,
        profile_name="edge-confirm-modal-contract",
    )
    _assert_confirm_modal_probe(probe)


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

    batch_mode = probe["batchMode"]
    assert batch_mode == {
        "ariaDisabled": "true",
        "tabIndex": "-1",
        "ariaCurrent": None,
        "checkboxChecked": True,
        "checkboxTabIndex": 0,
        "navigationPrevented": True,
        "locationHash": "",
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
