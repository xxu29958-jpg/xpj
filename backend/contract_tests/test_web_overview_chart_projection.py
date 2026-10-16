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
const data = VALUES.map((value,i) => ({name:'<原分类>'+i,amount_major:value,amount_yuan:999,amount_label:'JPY '+value,percent_label:'83.3%'}));
let option = null, instances = 0, resize;
const el = {getAttribute:() => JSON.stringify(data),clientWidth:0,clientHeight:0};
const document = {getElementById:() => el, documentElement:{}, querySelectorAll:() => []};
const window = {};
const echarts = {init:() => {instances++;return {setOption:value => option=value,resize(){}}}};
const context = {window,document,echarts,getComputedStyle:() => ({getPropertyValue:() => '#fff'}),
  ResizeObserver:class {constructor(fn){resize=fn}observe(){}},MutationObserver:class {observe(){}}};
vm.runInNewContext(fs.readFileSync(CORE,'utf8'), context);
vm.runInNewContext(fs.readFileSync(SOURCE,'utf8'), context);
window.TicketboxWeb.initCategoryDonut();
if (instances !== 0) throw new Error('hidden narrow chart initialised');
el.clientWidth=el.clientHeight=240;
if (resize) {resize();el.clientWidth=0;resize();el.clientWidth=240;resize();}
if (instances > 1) throw new Error('responsive change duplicated chart');
process.stdout.write(JSON.stringify(option ? {values:option.series[0].data.map(d => d.value),
  tip:option.tooltip.formatter({name:'<原分类>',data:{amountLabel:'JPY 100',percentLabel:'83.3%'},percent:83})} : null));
"""
    script = script.replace("VALUES", json.dumps(values)).replace("SOURCE", json.dumps(str(source)))
    script = script.replace("CORE", json.dumps(str(source.with_name("core.js"))))
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    if expected is None:
        assert actual is None
    else:
        assert actual["values"] == expected
        assert "&lt;原分类&gt;" in actual["tip"] and "JPY 100" in actual["tip"]
        assert "83.3%" in actual["tip"]
