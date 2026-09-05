/* Execute the real consumer's persisted page lifecycle without a browser/DB. */
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const scope = {datasetId:'dataset', clientGeneration:'generation', accountId:'account', ledgerId:'ledger', deviceId:'device'};
const original = 'a'.repeat(32), fresh = 'b'.repeat(32);
const entries = new Map(), handlers = {}, requests = [];
const names = ['amount_major','currency_code','merchant','category','spent_at','note'];
const defaults = ['', 'CNY', '', '其他', '2026-09-06T12:30', ''];
const elements = Object.fromEntries(names.map((name, i) => [name, {
  name, value:defaults[i], tagName:name === 'currency_code' ? 'SELECT' : 'INPUT',
}]));
elements.client_ref = {value:fresh};
const fields = {}, submit = {}, status = {}, summary = {};
const options = {dataset:{startExpanded:'false'}, querySelector:() => summary, contains:() => false};
const actions = {}, list = {replaceChildren(){}, appendChild(){}}, count = {};
const shelf = {querySelector:selector => selector.includes('list') ? list : count};
const form = {
  dataset:{manualDraftScope:JSON.stringify(scope), manualDraftResult:''},
  elements:{namedItem:name => elements[name]}, addEventListener(){},
  querySelector:selector => selector.includes('edit-fields') ? fields :
    selector.includes('submit') ? submit : selector.includes('status') ? status : options,
};
const document = {
  querySelector:selector => selector.includes('scope') ? form : selector.includes('actions') ? actions : shelf,
  createElement:() => ({append(){}}),
};
const window = {
  localStorage:{
    get length(){return entries.size;}, key:i => [...entries.keys()][i],
    getItem:key => entries.get(key) ?? null, setItem:(key, value) => entries.set(key, value),
    removeItem:key => entries.delete(key),
  },
  location:{hash:'#manual-' + original}, history:{replaceState(){}},
  addEventListener:(name, handler) => {handlers[name] = handler;},
  navigator:{locks:{request:(key, _options, callback) => {
    requests.push(key);
    return Promise.resolve().then(() => callback(requests.length === 1 ? null : {}));
  }}},
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {window});
const drafts = window.TicketboxManualDrafts;
drafts.save(scope, original, 'submitted', {...Object.fromEntries(names.map((name, i) => [name, defaults[i]])), amount_major:'28.50'});
vm.runInNewContext(fs.readFileSync(process.argv[3], 'utf8'), {window, document});
(async function () {
  await Promise.resolve(); await Promise.resolve();
  assert.equal(form.dataset.manualDraftState, 'locked');
  handlers.pagehide({persisted:true});
  handlers.pageshow({persisted:true});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(requests[1], drafts.key(original), 'return must request the original lock');
  assert.equal(form.dataset.manualDraftState, 'submitted');
  assert.equal(elements.client_ref.value, original);
  assert.equal(elements.amount_major.value, '28.50');
  assert.equal(elements.amount_major.readOnly, true);
  assert.equal(window.location.hash, '#manual-' + original);
  assert.equal(drafts.read(original).phase, 'submitted');
  assert.equal(drafts.read(fresh), null);
})().catch(error => {console.error(error); process.exitCode = 1;});
