const assert = require('node:assert/strict');
const {environment, scope, original, fresh, target, repaymentId, tick} = require('./repayment_draft_contract.cjs');
const kind = process.argv[4];
const values = {debt_public_id:target, ledger_id:'ledger', origin_binding:JSON.stringify(scope),
  expected_row_version:'7', reason:'原提交原因，不以当前状态判断接受',
  repayment_public_id:kind === 'repayment-void' ? repaymentId : ''};
const options = {kind, fieldNames:Object.keys(values), draftPrefix:'ticketbox:' + kind + '-draft:v1:', values};
(async function () {
  if (kind === 'repayment-void') {
    const combined = environment();
    const shell = combined.page({...options, canCreate:false, ref:'', values:{...values, repayment_public_id:''}});
    const row = combined.page({...options, ref:original});
    const other = combined.page({...options, ref:fresh, values:{...values, repayment_public_id:fresh}});
    shell.document.querySelectorAll = () => [shell.form, row.form, other.form];
    shell.form.closest = () => shell.document;
    row.form.closest = () => row.document;
    other.form.closest = () => other.document;
    shell.start(); await tick();
    assert.equal(row.submit.disabled, false, 'empty recovery shelf cannot steal a native row lease');
    assert.equal(other.submit.disabled, false, 'different repayment rows retain their native capabilities');
    assert.equal(row.form.fire('submit').defaultPrevented, false);
    assert.equal(other.form.fire('submit').defaultPrevented, true, 'another unresolved submission on the same debt requires review first');
    assert.equal(row.store.read(original).values.repayment_public_id, repaymentId);
    assert.equal(other.store.read(fresh), null, 'other fact cannot silently replace the submitted original');
  }
  const env = environment(), first = env.page({...options, ref:original});
  first.start(); await tick();
  assert.equal(first.form.fire('submit').defaultPrevented, false);
  assert.deepEqual({...first.store.read(original).values}, values, 'original typed intent persists before native POST');
  assert.equal(first.store.read(original).values.amount_major, undefined);
  first.window.fire('pagehide'); await tick();
  const reopened = env.page({...options, canCreate:false, ref:'', values:{expected_row_version:'99', reason:''}});
  reopened.start(); await tick();
  assert.equal(reopened.fields.idempotency_key.value, original);
  assert.deepEqual(reopened.snapshot(), values, 'terminal debt/fact cannot erase original target, reason or OCC');
  reopened.fields.reason.value = 'silently changed';
  assert.equal(reopened.form.fire('submit').defaultPrevented, false);
  assert.deepEqual(reopened.snapshot(), values, 'retry sends immutable original');
  reopened.window.fire('pagehide'); await tick();
  const wrong = env.page({...options, scope:{...scope, deviceId:'new-device'}});
  wrong.start(); await tick();
  assert.equal(wrong.submit.disabled, true);
  assert.equal(wrong.form.fire('submit').defaultPrevented, true);
  wrong.window.fire('pagehide'); await tick();
  for (const changed of [{values:{...values, reason:'other reason'}}, {resultPublicId:repaymentId},
    {scope:{...scope, clientGeneration:'other'}}, null]) {
    const ack = {scope, clientRef:original, resultPublicId:target, values, ...changed};
    const page = env.page({...options, canCreate:false, ref:'', ack}); page.start(); await tick();
    assert.equal(page.store.read(original) === null, changed === null, 'only exact command receipt clears original');
    page.window.fire('pagehide'); await tick();
  }
  assert.equal(first.store.read(fresh), null, 'no replacement command was created');
  const legacy = env.page({...options, ref:original, result:'accepted-review'});
  legacy.store.save(scope, original, 'submitted', values);
  legacy.start(); await tick();
  assert.equal(legacy.submit.disabled, true, 'old accepted receipt must not invite replacement or resend');
  assert.equal(legacy.store.read(original).phase, 'blocked');
  assert.equal(legacy.form.fire('submit').defaultPrevented, true);
  legacy.finishReview.fire('click');
  assert.equal(legacy.store.read(original), null, 'explicit review can end this exact local recovery');
  assert.equal(legacy.store.read(fresh), null);

})().catch(error => { console.error(error); process.exitCode = 1; });
