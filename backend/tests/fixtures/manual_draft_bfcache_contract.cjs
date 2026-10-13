/* Execute the real consumer's persisted page lifecycle without a browser/DB. */
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const scope = {datasetId:'dataset', clientGeneration:'generation', accountId:'account', ledgerId:'ledger', deviceId:'device'};
const original = 'a'.repeat(32), fresh = 'b'.repeat(32);
const entries = new Map(), handlers = {}, requests = [];
const names = ['amount_major','currency_code','merchant','category','spent_at','note','home_currency_code','return_to','return_recurring_public_id','return_month','return_payment_expense_id','return_payment_month','return_query'];
const defaults = ['', 'JPY', '', '其他', '2026-09-06T12:30', '', 'JPY', 'recurring_occurrence', '6dce3575-fb65-4df5-bb93-7bb270e8df9b', '2026-09', '41', 'all', '宽带 & 返还'];
const elements = Object.fromEntries(names.map((name, i) => [name, {
  name, value:defaults[i], tagName:name === 'currency_code' ? 'SELECT' : 'INPUT',
}]));
elements.client_ref = {value:fresh};
for (const [name, value] of Object.entries({time_precision:'instant', calendar_revision:'2',
 user_local_date:'2026-09-06', source_timezone:'America/New_York', source_utc_offset_seconds:'-14400', accounting_date:''})) {
  elements[name] = {name, value, tagName:name === 'time_precision' ? 'SELECT' : 'INPUT'};
}
const fields = {}, submit = {}, status = {}, summary = {}, result = {};
const options = {dataset:{startExpanded:'false'}, querySelector:() => summary, contains:() => false};
const actions = {}, list = {replaceChildren(){}, appendChild(){}}, count = {};
const shelf = {querySelector:selector => selector.includes('list') ? list : count};
const form = {
  dataset:{manualDraftScope:JSON.stringify(scope), manualDraftResult:''},
  elements:{namedItem:name => elements[name]}, addEventListener(){},
  querySelectorAll:selector => selector === '.manual-expense-options' ? [options] : [],
  querySelector:selector => selector.includes('manual-original') ? null : selector.includes('edit-fields') ? fields :
    selector.includes('submit') ? submit : selector.includes('status') ? status : selector.includes('result') ? result : options,
};
const createdNodes = [];
const document = {
  querySelector:selector => selector.includes('scope') ? form : selector.includes('actions') ? actions : shelf,
  createElement:() => { const node = {append(){}}; createdNodes.push(node); return node; },
};
const window = {
  localStorage:{
    get length(){return entries.size;}, key:i => [...entries.keys()][i],
    getItem:key => entries.get(key) ?? null, setItem:(key, value) => entries.set(key, value),
    removeItem:key => entries.delete(key),
  },
  location:{href:'https://ticketbox.test/web/expenses/new', hash:'#manual-' + original}, history:{replaceState(){}},
  addEventListener:(name, handler) => {handlers[name] = handler;},
  navigator:{locks:{request:(key, _options, callback) => {
    requests.push(key);
    return Promise.resolve().then(() => callback(requests.length === 1 ? null : {}));
  }}},
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {window});
const drafts = window.TicketboxManualDrafts;
drafts.save(scope, original, 'submitted', {...Object.fromEntries(names.map((name, i) => [name, defaults[i]])), amount_major:'28.50', currency_code:'CNY', home_currency_code:'CNY'});
vm.runInNewContext(fs.readFileSync(process.argv[3], 'utf8'), {window, document, URL});
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
  assert.equal(elements.currency_code.value, 'CNY');
  assert.equal(elements.home_currency_code.value, 'CNY');
  assert.equal(elements.return_payment_month.value, 'all');
  assert.equal(elements.return_query.value, '宽带 & 返还');
  const continuation = createdNodes.find(node => node.href?.endsWith('#manual-' + original));
  const returnQuery = new URL(continuation.href, window.location.href).searchParams;
  assert.equal(returnQuery.get('return_month'), '2026-09');
  assert.equal(returnQuery.get('return_payment_month'), 'all');
  assert.equal(returnQuery.get('return_query'), '宽带 & 返还');
  assert.equal(elements.amount_major.readOnly, true);
  assert.equal(elements.calendar_revision.disabled, true, 'old original body must not acquire current calendar');
  assert.equal(elements.time_precision.disabled, true);
  assert.equal(drafts.read(original).values.calendar_revision, undefined);
  assert.equal(window.location.hash, '#manual-' + original);
  assert.equal(drafts.read(original).phase, 'submitted');
  assert.equal(drafts.read(fresh), null);
})().catch(error => {console.error(error); process.exitCode = 1;});
