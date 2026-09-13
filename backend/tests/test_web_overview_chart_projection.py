"""Execute the live category chart without fabricating partial percentages."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("values,expected", [([100, None], None), ([100, -20], None), ([0, 0], None), ([100, 20], [100, 20])])
def test_actual_donut_only_plots_complete_comparable_money(values, expected):
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the live chart consumer"
    source = Path(__file__).parents[1] / "app/static/web/desktop/category-donut.js"
    script = r"""
const vm = require('vm'), fs = require('fs');
const data = VALUES.map((value,i) => ({name:'<原分类>'+i,amount_major:value,amount_yuan:999,amount_label:'JPY '+value}));
let option = null;
const el = {getAttribute:() => JSON.stringify(data)};
const document = {getElementById:() => el, documentElement:{}, querySelectorAll:() => []};
const window = {TicketboxWeb:{readVar:() => '#fff',escapeHtml:value => value.replaceAll('<','&lt;')}};
const echarts = {init:() => ({setOption:value => option=value,resize(){}})};
vm.runInNewContext(fs.readFileSync(SOURCE,'utf8'), {window,document,echarts,
  ResizeObserver:class {observe(){}},MutationObserver:class {observe(){}}});
window.TicketboxWeb.initCategoryDonut();
process.stdout.write(JSON.stringify(option ? {values:option.series[0].data.map(d => d.value),
  tip:option.tooltip.formatter({name:'<原分类>',data:{amountLabel:'JPY 100'},percent:83})} : null));
"""
    script = script.replace("VALUES", json.dumps(values)).replace("SOURCE", json.dumps(str(source)))
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    if expected is None:
        assert actual is None
    else:
        assert actual["values"] == expected
        assert "&lt;原分类>" in actual["tip"] and "JPY 100" in actual["tip"]
