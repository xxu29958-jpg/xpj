"""Execute the actual report charts with nullable ECharts data and captured JPY metadata."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_CHART_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const report = {
  home_currency_code: 'JPY', ranking_metric: METRIC,
  trend: [{label:'第一周', amount_cents:null, count:2}, {label:'第二周', amount_cents:1200, count:1}],
  merchant_ranking: [{merchant:'原商家', amount_cents:null, count:2}],
  category_comparison: [{category:'餐饮', amount_cents:null, previous_amount_cents:1200,
    year_over_year_amount_cents:null, delta_amount_cents:null, year_over_year_delta_amount_cents:null}],
};
const history = [{month:'2026-04', amount_cents:1200, budget_cents:1500},
  {month:'2026-05', amount_cents:null, budget_cents:null}];
const attrs = {'data-home-currency':'JPY','data-home-currency-symbol':'¥','data-home-currency-minor-digits':'0'};
const charts = {};
const elements = {};
['reports-trend-chart','reports-merchant-chart','reports-category-chart','chart-trend'].forEach(id => {
  elements[id] = {id, getAttribute: () => JSON.stringify(history), closest: () => ({classList:{add(){}}})};
});
elements['reports-overview-data'] = {textContent:JSON.stringify(report)};
const document = {readyState:'complete', documentElement:{getAttribute:name => attrs[name]},
  getElementById:id => elements[id] || null};
const echarts = {init:el => ({setOption:option => {charts[el.id] = option;}, resize(){}, getDom:() => el})};
const window = {echarts, getComputedStyle:() => ({getPropertyValue:() => '#123456'}), addEventListener(){}};
const context = {window, document, echarts, Intl, Number, BigInt, String, Math, URLSearchParams,
  getComputedStyle:window.getComputedStyle, ResizeObserver:class {observe(){}}, MutationObserver:class {observe(){}}};
for (const name of ['desktop/core.js','reports.js','desktop/trend-chart.js']) {
  vm.runInNewContext(fs.readFileSync(ROOT + '/' + name, 'utf8'), context);
}
window.TicketboxWeb.initTrendChart();
const trend = charts['reports-trend-chart'];
const category = charts['reports-category-chart'];
const months = charts['chart-trend'];
const merchant = charts['reports-merchant-chart'];
process.stdout.write(JSON.stringify({
  weekValues:trend.series[0].data,
  weekUnknown:trend.tooltip.formatter([{dataIndex:0}]),
  weekKnown:trend.tooltip.formatter([{dataIndex:1}]),
  categoryUnknown:category.tooltip.formatter([{dataIndex:0}]),
  monthValues:months.series[1].data.map(item => item.value),
  budgetValues:months.series[0].data.map(item => item.value),
  monthUnknown:months.tooltip.formatter([{axisValue:'5月', data:months.series[1].data[1], seriesName:'支出', color:'#000'}]),
  merchantValues:merchant ? merchant.series[0].data.map(item => item.value) : null,
}));
"""


@pytest.mark.parametrize("metric", ["amount", "count"])
def test_actual_report_charts_do_not_plot_unknown_money_as_zero(metric):
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the real chart consumers"
    root = Path(__file__).resolve().parents[1] / "app/static/web"
    script = _CHART_SCRIPT.replace("ROOT", json.dumps(str(root))).replace("METRIC", json.dumps(metric))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["weekValues"] == [None, 1200]
    assert actual["monthValues"] == [1200, None] and actual["budgetValues"] == [1500, None]
    assert "待补汇率" in actual["weekUnknown"] and "待补汇率" in actual["monthUnknown"]
    assert "待补汇率" in actual["categoryUnknown"] and "¥0" not in actual["categoryUnknown"]
    assert "1,200" in actual["weekKnown"] and "12.00" not in actual["weekKnown"]
    assert actual["merchantValues"] == ([2] if metric == "count" else None)
