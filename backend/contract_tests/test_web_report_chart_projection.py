"""Execute report charts with nullable data and captured zero/three-digit currencies."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_CHART_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const report = {
  home_currency_code: CURRENCY, ranking_metric: METRIC,
  trend: [{label:'第一周', amount_cents:null, count:2}, {label:'第二周', amount_cents:12345, count:1}],
  merchant_ranking: [{merchant:'原商家', amount_cents:null, count:2}],
  category_comparison: [{category:'餐饮', amount_cents:null, previous_amount_cents:12345,
    year_over_year_amount_cents:null, delta_amount_cents:null, year_over_year_delta_amount_cents:null}],
};
const history = [{month:'2026-04', amount_cents:12345, budget_cents:20000, budget_status:'set'},
  {month:'2026-05', amount_cents:null, budget_cents:null, budget_status:'unavailable'},
  {month:'2026-06', amount_cents:0, budget_cents:null, budget_status:'not_set'}];
const attrs = {'data-home-currency':CURRENCY,'data-home-currency-symbol':SYMBOL,'data-home-currency-minor-digits':DIGITS};
const charts = {};
const instances = {};
const elements = {};
const creations = {};
const observers = [];
let themeColor = '#123456';
let exportClick;
let exported;
['reports-trend-chart','reports-merchant-chart','reports-category-chart','chart-trend'].forEach(id => {
  elements[id] = {id, clientWidth:480, getAttribute: () => JSON.stringify(history), closest: selector => selector === '.reports-panel' ? {classList:{add(){}}} : null};
});
elements['reports-overview-data'] = {textContent:JSON.stringify(report)};
elements['reports-export-png'] = {addEventListener:(_event, listener) => {exportClick = listener;}};
elements['reports-export-dialog'] = {showModal(){}};
elements['reports-export-image'] = {};
const document = {readyState:'complete', addEventListener(){}, documentElement:{getAttribute:name => attrs[name]},
  getElementById:id => elements[id] || null};
const echarts = {getInstanceByDom:el => instances[el.id], init:el => {
  creations[el.id] = (creations[el.id] || 0) + 1;
  return instances[el.id] = {setOption:option => {charts[el.id] = option;}, resize(){}, getDom:() => el,
    getDataURL:options => {exported = options; return 'data:image/png;base64,preview';}};
}};
const window = {echarts, location:{hash:''}, matchMedia:() => ({matches:false}), getComputedStyle:() => ({getPropertyValue:name =>
  name === '--type-caption-size' ? '13px' : name === '--text-faint' ? '#111111' : themeColor}), addEventListener(){}};
const context = {window, document, echarts, Intl, Number, BigInt, String, Math, URLSearchParams,
  getComputedStyle:window.getComputedStyle, ResizeObserver:class {observe(){}},
  MutationObserver:class {constructor(callback){observers.push(callback);} observe(){}}};
for (const name of ['desktop/core.js','reports.js','desktop/trend-chart.js']) {
  vm.runInNewContext(fs.readFileSync(ROOT + '/' + name, 'utf8'), context);
}
window.TicketboxWeb.initTrendChart();
const values = () => JSON.stringify(Object.fromEntries(Object.entries(charts).map(([id, option]) =>
  [id, option.series.map(series => series.data.map(point =>
    point && typeof point === 'object' ? point.value : point))])));
const originalValues = values();
themeColor = '#abcdef';
observers.forEach(callback => callback([{attributeName:'data-theme'}]));
exportClick();
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
  budgetValues:months.series[0].data.map(item => item.value[1]),
  budgetUnavailable:months.tooltip.formatter([{axisValue:'5月', data:months.series[0].data[1], seriesName:'预算', color:'#000'}]),
  budgetUnset:months.tooltip.formatter([{axisValue:'6月', data:months.series[0].data[2], seriesName:'预算', color:'#000'},
    {axisValue:'6月', data:months.series[1].data[2], seriesName:'净支出', color:'#000'}]),
  monthUnknown:months.tooltip.formatter([{axisValue:'5月', data:months.series[1].data[1], seriesName:'支出', color:'#000'}]),
  monthKnown:months.tooltip.formatter([{axisValue:'4月', data:months.series[1].data[0], seriesName:'支出', color:'#000'}]),
  merchantValues:merchant ? merchant.series[0].data.map(item => item.value) : null,
  themeLabels:Object.values(charts).flatMap(option => [option.xAxis.axisLabel.color, option.yAxis.axisLabel.color]),
  financialValuesUnchanged:values() === originalValues,
  creations, exportBackground:exported.backgroundColor,
}));
"""


@pytest.mark.parametrize("metric", ["amount", "count"])
@pytest.mark.parametrize("currency,digits,symbol,label", [("JPY", 0, "¥", "¥12,345"), ("KWD", 3, "", "KWD 12.345")])
def test_actual_report_charts_preserve_money_when_the_existing_views_change_theme(metric, currency, digits, symbol, label):
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the real chart consumers"
    root = Path(__file__).resolve().parents[1] / "app/static/web"
    script = _CHART_SCRIPT.replace("ROOT", json.dumps(str(root))).replace("METRIC", json.dumps(metric))
    script = script.replace("CURRENCY", json.dumps(currency)).replace("DIGITS", json.dumps(str(digits)))
    script = script.replace("SYMBOL", json.dumps(symbol))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    major = 12345 / 10 ** digits
    # The report keeps minor units for geometry; its tooltip converts them.
    # The monthly consumer projects geometry to major units before rendering.
    assert actual["weekValues"] == [None, 12345]
    assert actual["monthValues"] == [major, None, 0] and actual["budgetValues"] == [20000 / 10 ** digits, None, None]
    # A set budget waiting for its rate is still named; a month without a budget has none to show.
    assert "预算" in actual["budgetUnavailable"] and "待补汇率" in actual["budgetUnavailable"]
    assert "预算" not in actual["budgetUnset"] and "净支出" in actual["budgetUnset"]
    assert "待补汇率" in actual["weekUnknown"] and "待补汇率" in actual["monthUnknown"]
    assert "待补汇率" in actual["categoryUnknown"] and "¥0" not in actual["categoryUnknown"]
    assert label in actual["weekKnown"] and label in actual["monthKnown"]
    assert actual["merchantValues"] == ([2] if metric == "count" else None)
    assert set(actual["themeLabels"]) == {"#abcdef"}, "Every chart must reread its theme colors"
    assert actual["financialValuesUnchanged"], "Appearance must not reinterpret financial values"
    assert set(actual["creations"].values()) == {1}, "Theme changes must reuse the displayed charts"
    assert actual["exportBackground"] == "#abcdef", "PNG export must use the current appearance"
