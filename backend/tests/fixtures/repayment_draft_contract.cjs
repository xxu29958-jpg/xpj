/* Real shipped JS with browser-shaped DOM, shared storage and exclusive leases. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const scope = {datasetId:'dataset', clientGeneration:'generation', accountId:'account', ledgerId:'ledger', deviceId:'device'};
const original = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const fresh = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const target = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const repaymentId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const names = ['debt_public_id','ledger_id','origin_binding','home_currency_code',
  'expected_row_version','amount_major','paid_at','paid_at_timezone'];
const values = {debt_public_id:target, ledger_id:'ledger', origin_binding:JSON.stringify(scope),
  home_currency_code:'USD', expected_row_version:'4', amount_major:'0012.3400',
  paid_at:'2026-07-19', paid_at_timezone:'America/Los_Angeles'};
const prefix = 'ticketbox:repayment-draft:v1:';
const tick = async () => { for (let i = 0; i < 30; i += 1) await Promise.resolve(); };

function element(initial = {}) {
  const handlers = {};
  return Object.assign({hidden:false, disabled:false, readOnly:false, value:'', textContent:'',
    dataset:{}, children:[], tagName:'INPUT',
    addEventListener(name, fn) { handlers[name] = fn; },
    fire(name, extra = {}) {
      const event = {defaultPrevented:false, preventDefault() { this.defaultPrevented = true; }, ...extra};
      if (handlers[name]) handlers[name](event);
      return event;
    },
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    replaceChildren(...items) { this.children = items; },
  }, initial);
}

function environment() {
  const entries = new Map(), occupied = new Map(), requests = [], windows = [];
  const faults = {read:false, write:false, remove:false};
  const storage = {
    get length() { return entries.size; }, key:i => [...entries.keys()][i],
    getItem(key) { if (faults.read) throw Error('storage unavailable'); return entries.get(key) ?? null; },
    setItem(key, value) { if (faults.write) throw Error('quota'); entries.set(key, value); },
    removeItem(key) { if (faults.remove) throw Error('storage unavailable'); entries.delete(key); },
  };
  const locks = {request(key, options, callback) {
    if (typeof options === 'function') { callback = options; options = {}; }
    requests.push(key);
    if (occupied.has(key)) {
      assert.equal(options.ifAvailable, true, 'recovery must not wait on a page-long lease');
      return Promise.resolve().then(() => callback(null));
    }
    const lock = {name:key};
    occupied.set(key, lock);
    return Promise.resolve().then(() => callback(lock)).finally(() => {
      if (occupied.get(key) === lock) occupied.delete(key);
    });
  }};
  function page(options = {}) {
    const currentScope = options.scope || scope;
    const defaults = {...values, origin_binding:JSON.stringify(currentScope), amount_major:'',
      home_currency_code:'JPY', expected_row_version:'99', paid_at:'2026-09-12', paid_at_timezone:'Asia/Tokyo'};
    const shown = {...defaults, ...(options.values || {})};
    const fields = Object.fromEntries(names.map(name => [name, element({name, value:shown[name]})]));
    fields.idempotency_key = element({name:'idempotency_key', value:options.ref ?? fresh});
    fields.csrf_token = element({name:'csrf_token', value:'never-persist-credential'});
    const status = element({hidden:true}), submit = element(), panel = element({hidden:options.canCreate === false});
    const replace = options.replacement ? element({hidden:true}) : null, label = element();
    const list = element(), shelf = element({hidden:true, querySelector:() => list});
    const ackStatus = element();
    const ack = options.ack ? element({dataset:{repaymentAck:JSON.stringify(options.ack)},
      getAttribute:() => JSON.stringify(options.ack)}) : null;
    const form = element({dataset:{repaymentScope:JSON.stringify(currentScope),
      repaymentResult:options.result || '', repaymentCanCreate:options.canCreate === false ? 'false' : 'true',
      repaymentCanRecover:options.canRecover === false ? 'false' : 'true',
      repaymentTarget:target, repaymentReplacement:options.replacement ? JSON.stringify(options.replacement) : ''},
      elements:{namedItem:name => fields[name]},
      querySelector:selector => ({'[data-repayment-submit]':submit, '[data-repayment-status]':status,
        '[data-repayment-replace]':replace, 'label[for="debt-repay-amount"]':label})[selector] || null});
    const selectors = {'[data-repayment-scope]':form, '[data-repayment-panel]':panel,
      '[data-repayment-shelf]':shelf, '[data-repayment-list]':list,
      '[data-repayment-ack]':ack, '[data-repayment-ack-status]':ackStatus};
    const document = {querySelector:selector => selectors[selector] || null, createElement:() => element()};
    const window = element({localStorage:storage, navigator:{locks},
      location:{hash:options.hash || '', pathname:'/web/debts/' + target, search:'?ledger_id=ledger'}});
    window.history = {replaceState(_state, _title, url) {
      const hash = String(url).indexOf('#'); window.location.hash = hash < 0 ? '' : String(url).slice(hash);
    }};
    vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {window});
    const store = window.TicketboxDraftStore.createStore({prefix, fields:names,
      validRef:/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i});
    const start = () => vm.runInNewContext(fs.readFileSync(process.argv[3], 'utf8'), {window, document});
    windows.push(window);
    return {window, form, fields, status, submit, panel, shelf, list, ackStatus, store, start, replace, label,
      snapshot:() => Object.fromEntries(names.map(name => [name, fields[name].value]))};
  }
  return {entries, faults, requests, occupied, page,
    storageEvent() { windows.forEach(window => window.fire('storage')); }};
}

const cases = {
  async continuity() {
    const env = environment(), page = env.page({canCreate:false, ref:''});
    page.store.save(scope, original, 'submitted', values);
    page.start(); await tick();
    assert.equal(page.panel.hidden, false, 'cleared/read-failed detail must restore the original form');
    assert.equal(page.fields.idempotency_key.value, original);
    assert.deepEqual(page.snapshot(), values);
    assert.equal(page.fields.amount_major.readOnly, true);
    assert.match(page.label.textContent, /USD/, 'restored amount must identify its original currency');
    page.window.fire('hashchange'); await tick();
    assert.equal(page.submit.disabled, false, 'reopening a fragment releases its own lease before reacquiring');
    page.fields.amount_major.value = '900';
    assert.equal(page.form.fire('submit').defaultPrevented, false);
    assert.deepEqual(page.snapshot(), values, 'retry sends immutable original values');
    assert.equal(page.form.fire('submit').defaultPrevented, true, 'double click cannot send twice');
    page.window.fire('pagehide'); await tick();
    const reopened = env.page({canCreate:false, ref:''}); reopened.start(); await tick();
    assert.equal(reopened.fields.idempotency_key.value, original);
    assert.deepEqual(reopened.snapshot(), values);
    assert.equal(reopened.store.read(fresh), null);
  },
  async binding_and_lease() {
    const env = environment(), first = env.page(), second = env.page({ref:original});
    first.start(); second.start(); await tick();
    assert.equal(second.submit.disabled, true, 'two fresh keys still compete for one target lease');
    assert.equal(second.form.fire('submit').defaultPrevented, true);
    first.fields.amount_major.value = '0004.5600'; first.form.fire('input');
    assert.equal(first.store.read(fresh).values.amount_major, '0004.5600');
    assert.equal(first.store.read(fresh).values.csrf_token, undefined);
    first.window.fire('pagehide'); await tick();
    second.window.fire('pageshow', {persisted:true}); await tick();
    assert.equal(second.fields.idempotency_key.value, fresh, 'BFCache must adopt original target intent, not its initial key');
    assert.equal(second.fields.amount_major.value, '0004.5600');
    assert.equal(second.store.read(original), null);
    second.window.fire('pagehide'); await tick();
    const oldDevice = env.page({scope:{...scope, deviceId:'replacement'}}); oldDevice.start(); await tick();
    assert.equal(oldDevice.fields.amount_major.value, '0004.5600');
    assert.equal(oldDevice.submit.disabled, true);
    assert.equal(oldDevice.form.fire('submit').defaultPrevented, true);
    assert.equal(first.store.read(fresh).scope.deviceId, 'device');
  },
  async validation() {
    const env = environment(), raw = {...values, amount_major:'1..2'};
    const page = env.page({ref:original, result:'rejected', values:raw});
    page.store.save(scope, original, 'submitted', raw); page.start(); await tick();
    assert.equal(page.fields.amount_major.value, '1..2');
    assert.equal(page.fields.amount_major.readOnly, false);
    page.fields.amount_major.value = '0001.20'; page.form.fire('input');
    assert.equal(page.form.fire('submit').defaultPrevented, false);
    assert.equal(page.fields.idempotency_key.value, original);
    assert.equal(page.store.read(original).values.expected_row_version, '4');
    assert.equal(page.store.read(original).values.paid_at_timezone, 'America/Los_Angeles');
    assert.equal(page.store.read(fresh), null);
    page.window.fire('pagehide'); await tick();
    const mismatch = env.page({ref:original, result:'rejected', values:raw}); mismatch.start(); await tick();
    assert.equal(mismatch.submit.disabled, true, 'unrelated rejection cannot unlock a retained unknown command');
    assert.equal(mismatch.store.read(original).phase, 'submitted');
  },
  async ack() {
    for (const change of [null, {values:{...values, amount_major:'9'}}, {scope:{...scope, deviceId:'wrong'}},
      {values:{...values, debt_public_id:'wrong'}}, {repaymentPublicId:''}]) {
      const env = environment(), ack = {scope, clientRef:original, repaymentPublicId:repaymentId, values, ...change};
      const page = env.page({ack, hash:'#repayment-' + original});
      page.store.save(scope, original, 'submitted', values); page.start(); await tick();
      assert.equal(page.store.read(original) === null, change === null);
      if (change === null) {
        assert.equal(page.submit.disabled, false, 'short ACK lease must finish before form lease');
        assert.equal(page.fields.idempotency_key.value, fresh);
        assert.equal(env.requests[0], env.requests[1]);
      } else {
        assert.deepEqual(JSON.parse(JSON.stringify(page.store.read(original).values)), values);
      }
    }
    const env = environment(), page = env.page({canCreate:false, ref:original, values,
      ack:{scope, clientRef:original, repaymentPublicId:repaymentId, values}});
    page.store.save(scope, original, 'submitted', values); page.start(); await tick();
    assert.equal(page.store.read(original), null);
    assert.equal(page.panel.hidden, true, 'accepted fallback must not resurrect its native POST body');
    const hiddenEnv = environment(), hidden = hiddenEnv.page({
      ack:{scope, clientRef:original, repaymentPublicId:repaymentId, values}});
    hidden.store.save(scope, original, 'submitted', values);
    hidden.start(); hidden.window.fire('pagehide'); await tick();
    assert.equal(hiddenEnv.requests.length, 1, 'late ACK must not acquire a form lease after pagehide');
    hidden.window.fire('pageshow', {persisted:true}); await tick();
    assert.equal(hidden.submit.disabled, false);
  },
  async storage() {
    const env = environment(), page = env.page(); page.start(); await tick();
    page.fields.amount_major.value = '12.30'; page.form.fire('input');
    const before = env.entries.get(prefix + fresh);
    env.faults.write = true;
    assert.equal(page.form.fire('submit').defaultPrevented, true);
    assert.equal(env.entries.get(prefix + fresh), before);
    page.window.fire('pagehide'); await tick();
    env.faults.read = true;
    const failed = env.page(); failed.start(); await tick();
    assert.equal(failed.form.fire('submit').defaultPrevented, true);
  },
  async removed() {
    const env = environment(), page = env.page({hash:'#repayment-' + original});
    page.store.save(scope, original, 'submitted', values); page.start(); await tick();
    page.window.fire('pagehide'); await tick();
    env.entries.delete(prefix + original);
    page.window.fire('pageshow', {persisted:true}); await tick();
    assert.equal(page.submit.disabled, true);
    assert.equal(page.form.fire('submit').defaultPrevented, true);
    assert.equal(page.store.read(original), null);
    assert.equal(page.store.read(fresh), null);
  },
  async replacement() {
    const replacement = {clientRef:fresh, values:{...values, expected_row_version:'5'}};
    const env = environment(), page = env.page({ref:original, result:'blocked', values, replacement});
    page.store.save(scope, original, 'submitted', values); page.start(); await tick();
    assert.equal(page.store.read(fresh), null, 'fresh OCC is never adopted before explicit correction');
    assert.equal(page.submit.disabled, true);
    assert.equal(page.replace.hidden, false);
    page.replace.fire('click');
    assert.equal(page.store.read(original), null);
    assert.equal(page.fields.idempotency_key.value, fresh);
    assert.equal(page.fields.expected_row_version.value, '5');
    assert.equal(page.fields.amount_major.value, values.amount_major);
    assert.equal(page.fields.amount_major.readOnly, false);
    assert.equal(page.form.fire('submit').defaultPrevented, false);
    page.window.fire('pagehide'); await tick();

    const failedEnv = environment(), failed = failedEnv.page({ref:original, result:'blocked', values, replacement});
    failed.store.save(scope, original, 'submitted', values); failed.start(); await tick();
    failedEnv.faults.write = true;
    failed.replace.fire('click');
    assert.equal(failed.form.fire('submit').defaultPrevented, true);
    assert.equal(failed.store.read(original).values.expected_row_version, '4');
    assert.equal(failed.store.read(fresh), null);
    failedEnv.faults.write = false; failedEnv.faults.remove = true;
    failed.replace.fire('click');
    assert.equal(failed.form.fire('submit').defaultPrevented, true);
    assert.equal(failed.store.read(original).values.expected_row_version, '4');
    assert.equal(failed.store.read(fresh).values.expected_row_version, '5');
    failedEnv.faults.remove = false; failed.replace.fire('click');
    assert.equal(failed.store.read(original), null, 'explicit correction can finish after storage recovers');
    assert.equal(failed.fields.idempotency_key.value, fresh);
    assert.equal(failed.submit.disabled, false);

    const unknownEnv = environment(), unknown = unknownEnv.page({ref:original, result:'submitted', values});
    unknown.store.save(scope, original, 'submitted', values); unknown.start(); await tick();
    assert.equal(unknown.replace, null);
    assert.equal(unknown.store.read(original).phase, 'submitted');
    assert.equal(unknown.store.read(fresh), null);
  },
  async blocked_recovery() {
    const env = environment(), denied = env.page({canCreate:false, canRecover:false});
    denied.store.save(scope, original, 'blocked', values); denied.start(); await tick();
    assert.equal(denied.form.fire('submit').defaultPrevented, true);
    denied.window.fire('pagehide'); await tick();
    const restored = env.page({canCreate:false}); restored.start(); await tick();
    assert.equal(restored.fields.idempotency_key.value, original);
    assert.equal(restored.fields.amount_major.readOnly, true);
    assert.equal(restored.form.fire('submit').defaultPrevented, false, 'recovered permission can explicitly retry original bytes');
    assert.deepEqual(restored.snapshot(), values);
    assert.equal(restored.store.read(original).phase, 'submitted');
    restored.window.fire('pagehide'); await tick();

    const replacement = {clientRef:fresh, values:{...values, expected_row_version:'5'}};
    const conflict = env.page({ref:original, result:'blocked', values, replacement}); conflict.start(); await tick();
    env.faults.remove = true; conflict.replace.fire('click');
    assert.equal(conflict.store.read(original).phase, 'blocked', 'failed retirement leaves the original immutable');
    assert.equal(conflict.store.read(fresh).phase, 'editing');
    conflict.window.fire('pagehide'); await tick(); env.faults.remove = false;
    const reopened = env.page(); reopened.start(); await tick();
    assert.equal(reopened.fields.idempotency_key.value, original, 'multiple records prefer the immutable original');
    assert.equal(reopened.form.fire('submit').defaultPrevented, false);
    assert.deepEqual(reopened.snapshot(), values, 'only original bytes are sent despite another editing candidate');
    reopened.window.fire('pagehide'); await tick();
    const unused = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
    const renewed = env.page({ref:original, result:'blocked', values,
      replacement:{...replacement, clientRef:unused}}); renewed.start(); await tick();
    renewed.replace.fire('click');
    assert.equal(renewed.fields.idempotency_key.value, fresh, 'new refusal reuses the already retained matching candidate');
    assert.equal(renewed.store.read(original), null);
    assert.equal(renewed.store.read(unused), null, 'no third key is manufactured');
    assert.equal(renewed.submit.disabled, false);
  },
};
assert.ok(cases[process.argv[4]], 'unknown browser scenario');
cases[process.argv[4]]().catch(error => { console.error(error); process.exitCode = 1; });
