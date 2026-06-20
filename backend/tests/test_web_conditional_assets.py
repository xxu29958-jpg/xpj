"""issue #64 W1: ECharts vendor + report scripts load per-page, not globally.

Before W1, ``base.html`` pulled the ~1.1MB ``echarts.min.js`` (plus the chart /
report modules) on EVERY /web page. Now only the two chart-bearing pages —
the dashboard (JS-rendered ``#chart-category`` donut) and reports (``#chart-trend``
+ ``#reports-*`` charts) — fill ``{% block page_scripts %}`` with them; the rest of
the console skips that payload. These tests pin both directions so a future edit
can't silently re-globalize ECharts or drop it from a page that renders charts.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ``web_client`` (loopback-gate-bypassed /web client) comes from conftest.py.

_ECHARTS = "/static/web/vendor/echarts.min.js"
_CATEGORY_DONUT = "/static/web/desktop/category-donut.js"
_TREND_CHART = "/static/web/desktop/trend-chart.js"
_REPORTS_JS = "/static/web/reports.js"
_DASHBOARD_JS = "/static/web/desktop/dashboard.js"
# ``/static/web/desktop.js`` (the boot script) — the ".js" right after "desktop"
# makes this substring distinct from the ``/static/web/desktop/<module>.js`` files.
_DESKTOP_JS = "/static/web/desktop.js"


def test_non_chart_pages_do_not_load_echarts(web_client: TestClient) -> None:
    for path in ("/web/pending", "/web/confirmed", "/web/debts"):
        resp = web_client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        assert _ECHARTS not in resp.text, f"{path} unexpectedly loads ECharts"
        assert _REPORTS_JS not in resp.text, f"{path} unexpectedly loads reports.js"
        assert _CATEGORY_DONUT not in resp.text, f"{path} unexpectedly loads category-donut.js"
        assert _TREND_CHART not in resp.text, f"{path} unexpectedly loads trend-chart.js"


def test_dashboard_loads_echarts_and_category_donut_only(web_client: TestClient) -> None:
    resp = web_client.get("/web")
    assert resp.status_code == 200
    assert _ECHARTS in resp.text
    assert _CATEGORY_DONUT in resp.text
    assert _DASHBOARD_JS in resp.text
    # The reports trend / report charts are reports-only, not on the dashboard.
    assert _REPORTS_JS not in resp.text
    assert _TREND_CHART not in resp.text
    _assert_chart_script_order(resp.text, [_ECHARTS, _CATEGORY_DONUT, _DASHBOARD_JS])


def test_reports_loads_echarts_trend_and_reports_scripts_only(web_client: TestClient) -> None:
    resp = web_client.get("/web/reports")
    assert resp.status_code == 200
    assert _ECHARTS in resp.text
    assert _TREND_CHART in resp.text
    assert _REPORTS_JS in resp.text
    # The dashboard donut module is not needed on reports.
    assert _CATEGORY_DONUT not in resp.text
    assert _DASHBOARD_JS not in resp.text
    _assert_chart_script_order(resp.text, [_ECHARTS, _TREND_CHART, _REPORTS_JS])


def _assert_chart_script_order(html: str, page_block_scripts: list[str]) -> None:
    """Pin the load-bearing order base.html relies on (see its page_scripts note):
    ECharts first within the block (the chart modules reference the global
    ``echarts``), every page_scripts script before ``desktop.js`` (its boot() calls
    the chart init fns immediately, so they must already be defined). A future reorder
    that breaks this renders no chart in the browser but leaves the in/out asserts green.
    """
    positions = [html.index(src) for src in page_block_scripts]
    assert positions == sorted(positions), (page_block_scripts, positions)
    assert positions[-1] < html.index(_DESKTOP_JS), "page_scripts must precede desktop.js"
