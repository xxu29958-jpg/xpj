const assert = require('node:assert/strict');
const {environment, scope, original, fresh, target, tick} = require('./repayment_draft_contract.cjs');
const values = {debt_public_id:target, ledger_id:'ledger', origin_binding:JSON.stringify(scope),
  expected_row_version:'7', debt_kind:'revolving'};
const options = {kind:'debt-kind', fieldNames:Object.keys(values),
  draftPrefix:'ticketbox:debt-kind-draft:v1:', values};
function kindPage(env, overrides = {}) {
  const page = env.page({...options, ...overrides});
  page.fields.debt_kind.tagName = 'SELECT';
  page.nativeKind = () => [...Object.values(page.fields), ...page.form.children]
    .filter(field => field.name === 'debt_kind' && !field.disabled).map(field => field.value);
  return page;
}
(async function () {
  const env = environment(), first = kindPage(env, {ref:original});
  first.start(); await tick();
  assert.equal(first.fields.debt_kind.disabled, false);
  assert.equal(first.form.fire('submit').defaultPrevented, false);
  assert.equal(first.fields.debt_kind.disabled, true, 'native select must really lock the accepted candidate');
  assert.deepEqual(first.nativeKind(), ['revolving'], 'disabled select still sends exactly one original value');
  assert.deepEqual({...first.store.read(original).values}, values);
  first.window.fire('pagehide'); await tick();
  const resumed = kindPage(env, {canCreate:false, ref:'', values:{debt_kind:'installment', expected_row_version:'99'}});
  resumed.start(); await tick();
  assert.deepEqual(resumed.snapshot(), values, 'refresh cannot replace original choice or OCC with current debt');
  assert.equal(resumed.fields.debt_kind.disabled, true);
  resumed.fields.debt_kind.value = 'one_off';
  assert.equal(resumed.form.fire('submit').defaultPrevented, false);
  assert.deepEqual(resumed.nativeKind(), ['revolving'], 'retry serializes stored original even after attempted change');
  assert.equal(resumed.fields.idempotency_key.value, original);
  assert.equal(resumed.store.read(fresh), null, 'unknown original cannot mint a fresh intent');
  resumed.window.fire('pagehide'); await tick();
  const viewer = kindPage(env, {canCreate:false, canRecover:false, ref:''});
  viewer.start(); await tick();
  assert.deepEqual(viewer.snapshot(), values, 'same identity becoming readonly still shows original input');
  assert.equal(viewer.panel.hidden, false);
  assert.equal(viewer.fields.idempotency_key.value, original);
  assert.equal(viewer.form.fire('submit').defaultPrevented, true, 'viewer may read but cannot resubmit');
  viewer.window.fire('pagehide'); await tick();
  for (const debtKind of ['installment', 'revolving']) {
    const receipt = kindPage(env, {canCreate:false, ref:'',
      ack:{scope, clientRef:original, resultPublicId:target, values, debtKind}});
    receipt.start(); await tick();
    assert.equal(receipt.store.read(original) === null, debtKind === 'revolving', 'only exact original receipt retires input');
    receipt.window.fire('pagehide'); await tick();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
