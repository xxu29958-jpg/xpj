"""HTML contract assertions shared by the Web reports integration tests."""

from __future__ import annotations

import json
import re
from html import unescape

_TABLE_SPECS = (
    (
        "最近六个月实际支出与预算",
        ("月份", "实际支出", "预算", "入账笔数"),
    ),
    (
        "本月各时间段支出金额与入账笔数",
        ("时间段", "支出金额", "入账笔数"),
    ),
    (
        "分类支出本月、上月与去年同月对比",
        ("分类", "本月", "上月", "去年同月"),
    ),
    (
        "本月商家支出金额与入账笔数排行",
        ("名次", "商家", "支出金额", "入账笔数"),
    ),
)


def _report_table_markup(response_text: str, caption: str) -> str:
    match = re.search(
        rf"<table[^>]*>\s*<caption[^>]*>{re.escape(caption)}</caption>.*?</table>",
        response_text,
        re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def _cell_text(markup: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markup)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _table_rows(table_markup: str) -> list[list[tuple[str, str, str]]]:
    body = re.search(r"<tbody>(.*?)</tbody>", table_markup, re.DOTALL)
    assert body is not None
    rows: list[list[tuple[str, str, str]]] = []
    for row_markup in re.findall(r"<tr>(.*?)</tr>", body.group(1), re.DOTALL):
        rows.append(
            [
                (tag, attributes, _cell_text(content))
                for tag, attributes, content in re.findall(
                    r"<(th|td)([^>]*)>(.*?)</\1>",
                    row_markup,
                    re.DOTALL,
                )
            ]
        )
    return rows


def _report_tables(response_text: str) -> dict[str, str]:
    tables = {
        caption: _report_table_markup(response_text, caption)
        for caption, _ in _TABLE_SPECS
    }
    for caption, headers in _TABLE_SPECS:
        for label in headers:
            assert re.search(
                rf'<th[^>]*scope="col"[^>]*>\s*{re.escape(label)}\s*</th>',
                tables[caption],
            )
    return tables


def _assert_month_rows(response_text: str, table_markup: str) -> None:
    series_match = re.search(
        r'<div id="chart-trend"[^>]*data-series=\'([^\']+)\'',
        response_text,
        re.DOTALL,
    )
    assert series_match is not None
    six_month = json.loads(unescape(series_match.group(1)))
    month_rows = _table_rows(table_markup)
    assert len(month_rows) == len(six_month)
    for cells, point in zip(month_rows, six_month, strict=True):
        expected_budget = (
            f"¥{point['budget_yuan']:.2f}"
            if point["budget_cents"] > 0
            else "未设置"
        )
        assert [(tag, text) for tag, _, text in cells] == [
            ("th", point["month"]),
            ("td", f"¥{point['amount_yuan']:.2f}"),
            ("td", expected_budget),
            ("td", str(point["count"])),
        ]
        assert 'scope="row"' in cells[0][1]


def _assert_trend_rows(overview: dict, table_markup: str) -> None:
    rows = _table_rows(table_markup)
    assert len(rows) == len(overview["trend"])
    for cells, point in zip(rows, overview["trend"], strict=True):
        assert [(tag, text) for tag, _, text in cells] == [
            ("th", point["label"]),
            ("td", f"¥{point['amount_yuan']}"),
            ("td", str(point["count"])),
        ]
        assert 'scope="row"' in cells[0][1]


def _assert_category_rows(overview: dict, table_markup: str) -> None:
    rows = _table_rows(table_markup)
    categories = overview["category_comparison"][:8]
    assert len(rows) == len(categories)
    for cells, row in zip(rows, categories, strict=True):
        assert [(tag, text) for tag, _, text in cells] == [
            ("th", row["category"]),
            ("td", f"¥{row['amount_yuan']}"),
            ("td", f"¥{row['previous_amount_yuan']}"),
            ("td", f"¥{row['year_over_year_amount_yuan']}"),
        ]
        assert 'scope="row"' in cells[0][1]


def _assert_merchant_rows(overview: dict, table_markup: str) -> None:
    rows = _table_rows(table_markup)
    merchants = overview["merchant_ranking"][:8]
    assert len(rows) == len(merchants)
    for rank, (cells, row) in enumerate(
        zip(rows, merchants, strict=True),
        start=1,
    ):
        assert [(tag, text) for tag, _, text in cells] == [
            ("td", str(rank)),
            ("th", row["merchant"]),
            ("td", f"¥{row['amount_yuan']}"),
            ("td", str(row["count"])),
        ]
        assert 'scope="row"' not in cells[0][1]
        assert 'scope="row"' in cells[1][1]


def assert_report_data_tables(response_text: str, overview: dict) -> None:
    tables = _report_tables(response_text)
    _assert_month_rows(response_text, tables["最近六个月实际支出与预算"])
    _assert_trend_rows(overview, tables["本月各时间段支出金额与入账笔数"])
    _assert_category_rows(
        overview,
        tables["分类支出本月、上月与去年同月对比"],
    )
    _assert_merchant_rows(
        overview,
        tables["本月商家支出金额与入账笔数排行"],
    )


def parse_reports_overview(response_text: str) -> dict:
    blob = re.search(
        r'<script type="application/json" id="reports-overview-data">(.*?)</script>',
        response_text,
        re.DOTALL,
    )
    assert blob is not None
    overview = json.loads(blob.group(1))
    assert {
        "trend",
        "merchant_ranking",
        "ranking_metric",
        "category_comparison",
        "year_over_year_month",
        "has_previous_baseline",
        "has_year_over_year_baseline",
    } <= overview.keys()
    assert overview["has_previous_baseline"] is False
    assert overview["has_year_over_year_baseline"] is False
    assert overview["ranking_metric"] == "count"
    return overview


def _assert_chart_accessibility(response_text: str) -> None:
    for chart_id, title_id, summary_id in (
        ("chart-trend", "six-month-trend-title", "six-month-trend-summary"),
        ("reports-trend-chart", "reports-trend-title", "reports-trend-summary"),
        ("reports-category-chart", "reports-category-title", "reports-category-summary"),
        ("reports-merchant-chart", "reports-merchant-title", "reports-merchant-summary"),
    ):
        chart_markup = re.search(
            rf'<div id="{chart_id}".*?</div>',
            response_text,
            re.DOTALL,
        )
        assert chart_markup is not None
        assert f'aria-labelledby="{title_id}"' in chart_markup.group(0)
        assert f'aria-describedby="{summary_id}"' in chart_markup.group(0)


def _assert_report_disclosures(response_text: str) -> None:
    for label in (
        "查看月度趋势数据",
        "查看支出趋势数据",
        "查看分类对比数据",
        "查看商家排行数据",
    ):
        assert f">{label}</summary>" in response_text
    assert '<caption class="sr-only">最近六个月实际支出与预算</caption>' in response_text
    assert "本月各时间段支出金额与入账笔数" in response_text
    assert "分类支出本月、上月与去年同月对比" in response_text
    assert "本月商家支出金额与入账笔数排行" in response_text


def assert_reports_surface(response_text: str) -> None:
    assert '<span class="product-eyebrow">洞察 / 分析</span>' in response_text
    assert '<h1 class="page-title">分析</h1>' in response_text
    assert "动态报表，六个月看清节奏。" not in response_text
    for copy in ("月报摘要", "预算解释", "历史不足", "¥60.00"):
        assert copy in response_text
    assert "上月无数据" in response_text
    assert "去年同月无数据" in response_text
    assert "同比 ¥60.00" not in response_text
    assert "分类对比" in response_text
    assert "去年同月" in response_text
    assert "灰度账本商家" not in response_text
    for query_contract in (
        "/web/reports/export.csv",
        "granularity=week",
        "ranking_metric=count",
        "merchant_category=%E9%A4%90%E9%A5%AE",
    ):
        assert query_contract in response_text
    for element_id in (
        "reports-overview-data",
        "reports-trend-chart",
        "reports-merchant-chart",
        "reports-category-chart",
        "reports-export-png",
    ):
        assert f'id="{element_id}"' in response_text
    _assert_chart_accessibility(response_text)
    _assert_report_disclosures(response_text)
    for asset in (
        "/static/web/reports.js",
        "/static/web/vendor/echarts.min.js",
        "/static/web/desktop.js",
    ):
        assert asset in response_text
    assert "商家排行" in response_text
    assert 'style="' not in response_text
    assert 'class="report-export-dialog"' in response_text
