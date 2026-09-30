/* Capture review uses the real shared form engine, store and exclusive leases. */
const assert = require('node:assert/strict');
const {environment, scope, original, fresh, target, repaymentId, tick} = require('./repayment_draft_contract.cjs');
const fieldNames = ['draft_public_id', 'ledger_id', 'origin_binding', 'review_action', 'target_choice', 'original_currency', 'original_amount'];
const draftPrefix = 'ticketbox:repayment-review-draft:v1:';
const parent = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const values = {draft_public_id:target, ledger_id:scope.ledgerId, origin_binding:JSON.stringify(scope),
  review_action:'confirm', target_choice:parent + ':7', original_currency:'CNY', original_amount:' 90.'};
function page(env, options = {}) {
  const result = env.page({kind:'repayment-review', fieldNames, draftPrefix, values, ...options});
  for (const name of ['review_action', 'target_choice', 'original_currency']) {
    const control = result.fields[name];
    control.tagName = 'SELECT'; control.options = [{value:control.value}];
    control.appendChild = option => { control.options.push(option); };
  }
  return result;
}

async function continuity() {
  const env = environment(), editing = page(env, {ref:original});
  editing.start(); await tick();
  editing.form.fire('input');
  assert.equal(editing.store.read(original).values.original_amount, ' 90.');
  editing.window.fire('pagehide'); await tick();
  const reopened = page(env, {values:{...values, target_choice:parent + ':99', original_currency:'USD', original_amount:'100'}});
  reopened.start(); await tick();
  assert.deepEqual(reopened.snapshot(), values, 'raw input, selected debt and its original version survive reopening');
  assert.ok(reopened.fields.target_choice.options.some(option => option.value === parent + ':7'), 'missing stale option is retained');
  reopened.fields.original_amount.value = '90.00'; reopened.form.fire('input');
  const submitted = {...values, original_amount:'90.00'};
  assert.equal(reopened.form.fire('submit').defaultPrevented, false);
  assert.equal(reopened.store.read(original).phase, 'submitted');
  reopened.window.fire('pagehide'); await tick();
  const retry = page(env, {canCreate:false, ref:'', values:{...values, target_choice:'', original_amount:''}});
  retry.start(); await tick();
  assert.deepEqual(retry.snapshot(), submitted, 'unreadable or processed capture restores the exact original');
  assert.equal(retry.fields.idempotency_key.value, original);
  for (const name of ['review_action', 'target_choice', 'original_currency']) {
    assert.equal(retry.fields[name].disabled, true);
    const mirror = retry.form.children.find(input => input.name === name);
    assert.equal(mirror.disabled, false, 'disabled select has a native POST carrier');
    assert.equal(mirror.value, submitted[name]);
  }
  retry.fields.review_action.value = 'dismiss';
  assert.equal(retry.form.fire('submit').defaultPrevented, false);
  assert.deepEqual(retry.snapshot(), submitted, 'retry cannot change the action, money, key or OCC');
  retry.window.fire('pagehide'); await tick();
  const badAck = {scope, clientRef:original, values:submitted, resultPublicId:target, repaymentPublicId:repaymentId, status:'dismissed'};
  const invalid = page(env, {canCreate:false, ack:badAck}); invalid.start(); await tick();
  assert.ok(invalid.store.read(original), 'a mismatched result never removes the original');
  invalid.window.fire('pagehide'); await tick();
  const accepted = page(env, {canCreate:false, ack:{...badAck, status:'confirmed'}}); accepted.start(); await tick();
  assert.equal(accepted.store.read(original), null);
  assert.equal(accepted.store.read(fresh), null, 'receipt does not create another command');
}

async function rejectionAndBinding() {
  const env = environment(), conflict = page(env, {ref:original, result:'blocked', rejected:true});
  conflict.store.save(scope, original, 'submitted', values); conflict.start(); await tick();
  assert.equal(conflict.fields.target_choice.disabled, true);
  assert.equal(conflict.form.fire('submit').defaultPrevented, true, 'fresh page OCC cannot replace a rejected original');
  conflict.window.fire('pagehide'); await tick();
  const reopened = page(env, {rejected:true}); reopened.start(); await tick();
  assert.equal(reopened.submit.disabled, true);
  reopened.finishRejected.fire('click');
  assert.equal(reopened.store.read(original), null, 'only explicit completion retires the known rejected original');
  reopened.window.fire('pagehide'); await tick();
  const old = page(env, {ref:original}); old.store.save(scope, original, 'submitted', values);
  const changedScope = {...scope, deviceId:'another-browser'};
  const changed = page(env, {scope:changedScope, values:{...values, origin_binding:JSON.stringify(changedScope)}}); changed.start(); await tick();
  assert.deepEqual(changed.snapshot(), values, 'same owner can inspect retained old identity');
  assert.equal(changed.form.fire('submit').defaultPrevented, true);
  assert.equal(changed.store.read(original).values.origin_binding, values.origin_binding);
}

async function parentSubmission() {
  const env = environment(), capture = page(env, {ref:original, values:{...values, target_choice:target + ':7'}});
  capture.store.save(scope, original, 'submitted', {...values, target_choice:target + ':7'});
  const debt = env.page(); debt.start(); await tick();
  debt.fields.amount_major.value = '20.00';
  assert.equal(debt.form.fire('submit').defaultPrevented, true, 'same parent cannot get a second fresh local fact while review is unresolved');
  assert.equal(debt.store.read(fresh), null);
}

const scenarios = {continuity, rejectionAndBinding, parentSubmission};
assert.ok(scenarios[process.argv[4]], 'unknown capture scenario');
scenarios[process.argv[4]]().catch(error => { console.error(error); process.exitCode = 1; });
