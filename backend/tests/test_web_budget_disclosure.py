"""Execute the real budget enhancement without application or database fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_budget_disclosure_reveals_native_validation_without_copying_rules() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for the budget disclosure contract")
    source = Path(__file__).resolve().parents[1] / "app/static/web/desktop/budgets.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
function mount(startExpanded, withSummary = true) {
  const inside = {};
  const summary = {hidden: true};
  let invalid;
  const form = {addEventListener(name, handler, capture) {
    assert.equal(name, 'invalid');
    assert.equal(capture, true);
    invalid = handler;
  }};
  const options = {
    open: true,
    querySelector: selector => selector === 'summary' && withSummary ? summary : null,
    closest: selector => selector === 'form' ? form : null,
    getAttribute: name => name === 'data-start-expanded' ? String(startExpanded) : null,
    contains: target => target === inside,
  };
  const document = {
    readyState: 'complete',
    querySelector: selector => selector === '#budget-options' ? options : null,
  };
  vm.runInNewContext(source, {window: {}, document});
  return {options, summary, inside, invalid};
}
const first = mount(false);
assert.equal(first.options.open, false);
assert.equal(first.summary.hidden, false);
first.invalid({target: {}});
assert.equal(first.options.open, false);
first.invalid({target: first.inside});
assert.equal(first.options.open, true);
const existingOrError = mount(true);
assert.equal(existingOrError.options.open, true);
assert.equal(existingOrError.summary.hidden, false);
const incomplete = mount(false, false);
assert.equal(incomplete.options.open, true);
assert.equal(incomplete.summary.hidden, true);
"""
    completed = subprocess.run(
        [node, "-e", script, str(source)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
