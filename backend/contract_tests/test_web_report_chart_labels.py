"""Report chart labels state the exact amount the tooltip states (issue #259, C03-AMOUNT-001).

A bar label or axis tick that rounds chart geometry can contradict the
tooltip — a ¥0.40 bar labelled ¥0, a ¥0.50 bar labelled ¥1. Labels are read
from the exact minor-unit text; only amounts of 10,000 or more use the
explicitly approximate 万 unit.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const report = {home_currency_code: CURRENCY, ranking_metric: 'amount', trend: [], merchant_ranking: ROWS, category_comparison: []};
const attrs = {'data-home-currency': CURRENCY, 'data-home-currency-symbol': SYMBOL, 'data-home-currency-minor-digits': DIGITS};
const charts = {};
const elements = {'reports-overview-data': {textContent: JSON.stringify(report)}};
['reports-trend-chart', 'reports-merchant-chart', 'reports-category-chart'].forEach(id => {
  elements[id] = {id, clientWidth: 480, getAttribute: () => '[]', closest: s => s === '.reports-panel' ? {classList: {add(){}}} : null};
});
const document = {readyState: 'complete', addEventListener(){}, documentElement: {getAttribute: name => attrs[name]},
  getElementById: id => elements[id] || null};
const echarts = {getInstanceByDom: () => null, init: el => ({setOption: option => { charts[el.id] = option; }, resize(){}, getDom: () => el})};
const window = {echarts, location: {hash: ''}, matchMedia: () => ({matches: false}), addEventListener(){},
  getComputedStyle: () => ({getPropertyValue: name => name === '--type-caption-size' ? '13px' : '#123456'})};
const context = {window, document, echarts, Intl, Number, BigInt, String, Math, URLSearchParams,
  getComputedStyle: window.getComputedStyle, ResizeObserver: class { observe(){} }, MutationObserver: class { observe(){} }};
for (const name of ['desktop/core.js', 'reports.js']) {
  vm.runInNewContext(fs.readFileSync(ROOT + '/' + name, 'utf8'), context);
}
const merchant = charts['reports-merchant-chart'];
process.stdout.write(JSON.stringify({
  labels: merchant.series[0].data.map(item => merchant.series[0].label.formatter({value: item.value})),
  tooltips: merchant.series[0].data.map((_item, index) =>
    merchant.tooltip.formatter([{dataIndex: index}]).split('<strong>')[1].replace('</strong>', '')),
  ticks: TICKS.map(merchant.xAxis.axisLabel.formatter),
  gridRight: merchant.grid.right,
}));
"""


def _run(currency: str, symbol: str, digits: int, amounts: list[int], ticks: list[int]) -> dict:
    node = shutil.which("node")
    assert node is not None, "Node.js is required to verify the real chart consumers"
    root = Path(__file__).resolve().parents[1] / "app/static/web"
    rows = [{"merchant": f"商家{index}", "amount_cents": amount, "count": 1} for index, amount in enumerate(amounts)]
    script = (_SCRIPT.replace("ROOT", json.dumps(str(root))).replace("CURRENCY", json.dumps(currency))
              .replace("SYMBOL", json.dumps(symbol)).replace("DIGITS", json.dumps(str(digits)))
              .replace("ROWS", json.dumps(rows)).replace("TICKS", json.dumps(ticks)))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("currency,symbol,digits,amounts", [
    ("CNY", "¥", 2, [40, 50, 250, 123456, 300000, -1999]),
    ("JPY", "¥", 0, [40, 9999]),
    ("KWD", "KD", 3, [400, 1500, 9999999]),
])
def test_bar_labels_state_the_tooltip_amount(currency, symbol, digits, amounts):
    actual = _run(currency, symbol, digits, amounts, [])
    for label, tooltip in zip(actual["labels"], actual["tooltips"], strict=True):
        # A whole amount drops its zero fraction; nothing is rounded to another value.
        assert label in (tooltip, tooltip.rsplit(".", 1)[0]), (label, tooltip)
        if label != tooltip:
            assert set(tooltip.rsplit(".", 1)[1]) == {"0"}, (label, tooltip)


def test_large_amounts_use_the_approximate_unit_and_fit_beside_the_bar():
    actual = _run("CNY", "¥", 2, [1234567, 999999], [])
    # Bars are drawn bottom-up, so labels come in reverse ranking order.
    assert actual["labels"] == ["¥9,999.99", "¥1.2万"]
    # Room for the widest label ("¥9,999.99", 9 characters at 13px) beside the longest bar.
    assert actual["gridRight"] >= 8 + 0.62 * 13 * 9


def test_small_axis_ticks_stay_distinct():
    actual = _run("CNY", "¥", 2, [50], [0, 10, 20, 30, 40, 50])
    assert actual["ticks"] == ["¥0", "¥0.10", "¥0.20", "¥0.30", "¥0.40", "¥0.50"]
