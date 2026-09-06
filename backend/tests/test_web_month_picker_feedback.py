"""The shared month-picker drops transient feedback and keeps each page's scope."""

import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined


@pytest.mark.parametrize(
    "path,filters",
    [
        ("/web/reports", [("granularity", "week"), ("ranking_metric", "count"), ("merchant_category", "餐饮")]),
        ("/web/confirmed", [("tag", "家庭")]),
        ("/web/budgets", []),
        ("/web/goals", [("include_archived", "1")]),
    ],
)
def test_month_switch_drops_feedback_and_page_but_keeps_page_scope(path, filters):
    query = [
        ("ledger_id", "family"), ("month", "2026-05"), ("page", "2"),
        *filters, ("msg", "原记录已不存在"), ("flash_type", "error"),
    ]
    request = Request({
        "type": "http", "scheme": "http", "server": ("testserver", 80),
        "root_path": "", "path": path, "headers": [],
        "query_string": urlencode(query).encode(),
    })
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "app/templates/web"))
    templates.env.undefined = StrictUndefined
    rendered = templates.env.get_template("_month_picker.html").render(
        request=request, selected_month="2026-05",
    )
    hrefs = re.findall(r'href="([^"]+)"', rendered)
    assert len(hrefs) == 2
    for href, target_month in zip(hrefs, ("2026-04", "2026-06"), strict=True):
        target = urlsplit(unescape(href))
        assert target.path == path
        assert parse_qsl(target.query) == [("ledger_id", "family"), *filters, ("month", target_month)]
