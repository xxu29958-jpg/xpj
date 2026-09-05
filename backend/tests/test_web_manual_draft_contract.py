"""Small Node contract for the shipped local-intent store, without DB or browser."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_manual_draft_store_retains_one_bound_intent() -> None:
    node = shutil.which("node")
    assert node is not None, "The web contract lane requires Node"
    script = Path(__file__).parents[1] / "app/static/web/manual-drafts.js"
    assert script.is_file(), "missing real browser draft consumer"
    program = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const entries = new Map();
const storage = {
  get length() { return entries.size; },
  key: i => [...entries.keys()][i],
  getItem: key => entries.get(key) ?? null,
  setItem: (key, value) => entries.set(key, value),
  removeItem: key => entries.delete(key),
};
const window = {localStorage: storage};
vm.runInNewContext(fs.readFileSync(SCRIPT, 'utf8'), {window});
const drafts = window.TicketboxManualDrafts;
const scope = {datasetId:'dataset', clientGeneration:'generation', accountId:'account', ledgerId:'ledger', deviceId:'device'};
const ref = 'a'.repeat(32);
const fields = {amount_major:'28.50', currency_code:'CNY', merchant:'合成咖啡店', category:'其他', spent_at:'2026-09-06T12:30', note:'合成草稿', csrf_token:'never-store', token:'never-store'};
const record = drafts.save(scope, ref, 'editing', fields);
assert.equal(record.clientRef, ref);
assert.equal(drafts.read(ref).values.amount_major, '28.50');
assert.equal(drafts.read(ref).values.csrf_token, undefined);
assert.equal(drafts.read(ref).values.token, undefined);
assert.equal(drafts.list(scope).length, 1);
for (const axis of Object.keys(scope)) {
  const other = {...scope, [axis]: 'changed'};
  assert.equal(drafts.matches(scope, other), false);
  if (axis !== 'deviceId') assert.equal(drafts.list(other).length, 0);
  assert.throws(() => drafts.save(other, ref, 'editing', fields));
  assert.equal(drafts.acknowledge({scope:other, clientRef:ref}), false);
  assert.notEqual(drafts.read(ref), null);
}
// Same-account/ledger old Device drafts remain discoverable, never rebound.
assert.equal(drafts.list({...scope, deviceId:'replacement'}).length, 1);
drafts.save(scope, ref, 'submitted', fields);
assert.throws(() => drafts.save(scope, ref, 'editing', fields));
assert.throws(() => drafts.save(scope, ref, 'submitted', {...fields, amount_major:'99'}));
assert.equal(drafts.save(scope, ref, 'submitted', fields).values.amount_major, '28.50');
// Only the native rejection for this exact scope/ref permits correction.
drafts.save(scope, ref, 'editing', fields, 'rejected');
drafts.save(scope, ref, 'editing', {...fields, amount_major:'30'});
assert.equal(drafts.read(ref).values.amount_major, '30');
assert.equal(drafts.acknowledge({scope, clientRef:'b'.repeat(32)}), false);
assert.equal(drafts.acknowledge({scope, clientRef:ref}), true);
assert.equal(drafts.read(ref), null);
assert.equal(drafts.list(scope).length, 0);
// Unknown/corrupt data is not interpreted or overwritten as a fresh intent.
entries.set(drafts.key(ref), JSON.stringify({...record, version:2}));
assert.throws(() => drafts.read(ref));
assert.throws(() => drafts.save(scope, ref, 'editing', fields));
assert.equal(JSON.parse(entries.get(drafts.key(ref))).version, 2);
entries.clear();
storage.setItem = () => { throw Error('quota'); };
assert.throws(() => drafts.save(scope, ref, 'editing', fields));
assert.equal(drafts.read(ref), null);
""".replace("SCRIPT", json.dumps(str(script)))
    result = subprocess.run(
        [node, "-e", program], capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("ref", ["", "../ledger", "a" * 31, "a" * 33])
def test_manual_draft_store_rejects_non_intent_keys(ref: str) -> None:
    node = shutil.which("node")
    assert node is not None
    script = Path(__file__).parents[1] / "app/static/web/manual-drafts.js"
    assert script.is_file(), "missing real browser draft consumer"
    result = subprocess.run(
        [node, "-e", "const window = {}; " + script.read_text(encoding="utf-8")
         + f"; require('node:assert/strict').throws(() => window.TicketboxManualDrafts.key({json.dumps(ref)}));"],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_locked_page_bfcache_return_does_not_replace_the_requested_intent() -> None:
    node = shutil.which("node")
    assert node is not None
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [node, str(root / "tests/fixtures/manual_draft_bfcache_contract.cjs"),
         str(root / "app/static/web/manual-drafts.js"), str(root / "app/static/web/manual-entry.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr
