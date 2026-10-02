/* The shared, shipped intent consumer must preserve both OCC legs and command identity. */
const assert = require('node:assert/strict');
const {environment, scope, original, fresh, target, repaymentId, tick} = require('./repayment_draft_contract.cjs');
const values = {debt_public_id:target, ledger_id:'ledger', origin_binding:JSON.stringify(scope),
  home_currency_code:'CNY', command:'create', proposal_public_id:'', expected_row_version:'4',
  expected_return_row_version:'2', new_share_amount_major:'20.00', settlement_net_amount_major:'-10.00',
  reason:'商家部分退款，双方重新约定', supersedes_proposal_public_id:''};
const options = {splitChange:true, fieldNames:Object.keys(values), draftPrefix:'ticketbox:split-change-draft:v1:', values};
const cases = {
  async direction_and_original_recovery() {
    const env = environment(), page = env.page(options);
    page.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    page.start(); await tick();
    assert.equal(page.settlement.controls.hidden, false, 'Users must choose a direction without encoding a signed amount');
    assert.equal(page.settlement.direction.value, 'return');
    assert.equal(page.settlement.amount.value, '10.00');
    assert.equal(page.fields.settlement_net_amount_major.value, '-10.00');
    page.settlement.direction.value = 'pay';
    page.form.fire('input', {target:page.settlement.direction});
    assert.equal(page.store.read(fresh).values.settlement_net_amount_major, '10.00');
    page.settlement.direction.value = 'return';
    page.form.fire('input', {target:page.settlement.direction});
    page.settlement.amount.value = '';
    page.form.fire('input', {target:page.settlement.amount});
    assert.equal(page.store.read(fresh).values.settlement_net_amount_major, '-', 'An unfinished return keeps its direction');
    page.window.fire('pagehide'); await tick();
    const restored = env.page(options);
    restored.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    restored.start(); await tick();
    assert.equal(restored.settlement.direction.value, 'return');
    assert.equal(restored.settlement.amount.value, '');
    restored.settlement.amount.value = '0012.3400';
    restored.form.fire('input', {target:restored.settlement.amount});
    assert.equal(restored.store.read(fresh).values.settlement_net_amount_major, '-0012.3400');
    assert.equal(restored.store.read(fresh).values.settlement_explicit, 'true');
    assert.equal(restored.form.fire('submit').defaultPrevented, false);
    const submitted = {...restored.store.read(fresh).values};
    restored.window.fire('pagehide'); await tick();
    const recover = env.page({...options, values:{...values, settlement_net_amount_major:'90.00'}});
    recover.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    recover.start(); await tick();
    assert.equal(recover.settlement.direction.value, 'return');
    assert.equal(recover.settlement.amount.value, '0012.3400');
    assert.equal(recover.settlement.direction.disabled, true);
    assert.equal(recover.settlement.amount.readOnly, true);
    assert.equal(recover.form.fire('submit').defaultPrevented, false);
    assert.deepEqual({...recover.store.read(fresh).values}, submitted, 'Retry retains the signed amount, both versions and command identity');
  },
  async explicit_settlement_and_legacy_submission() {
    const env = environment(), page = env.page(options);
    page.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    page.start(); await tick();
    page.form.fire('input', {target:page.fields.settlement_net_amount_major});
    page.fields.new_share_amount_major.value = '12.00';
    page.form.fire('input', {target:page.fields.new_share_amount_major});
    assert.equal(page.store.read(fresh).values.settlement_explicit, 'true');
    page.window.fire('pagehide'); await tick();
    const restored = env.page(options);
    restored.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    restored.start(); await tick();
    assert.equal(restored.fields.settlement_explicit.value, 'true');
    assert.equal(restored.fields.settlement_net_amount_major.value, '-10.00');
    assert.equal(restored.form.fire('submit').defaultPrevented, false);
    const financial = {...restored.store.read(fresh).values}; delete financial.settlement_explicit;
    restored.window.fire('pagehide'); await tick();
    const ack = env.page({...options, ack:{scope, clientRef:fresh, resultPublicId:repaymentId, values:financial}});
    ack.start(); await tick();
    assert.equal(ack.store.read(fresh), null, 'The same accepted command closes its draft even without UI metadata in the receipt');
    ack.window.fire('pagehide'); await tick();
    const legacy = env.page(options);
    legacy.fields.settlement_explicit = {name:'settlement_explicit', value:'false'};
    legacy.store.save(scope, original, 'submitted', values);
    legacy.start(); await tick();
    assert.equal(legacy.fields.idempotency_key.value, original);
    assert.equal(legacy.form.fire('submit').defaultPrevented, false);
    assert.deepEqual({...legacy.store.read(original).values}, values, 'Old submitted snapshots acquire no new metadata or body');
  },
  async pending_retained_draft() {
    const env = environment(), page = env.page({...options, canCreate:false});
    page.store.save(scope, original, 'editing', values); page.start(); await tick();
    assert.equal(page.fields.reason.value, values.reason);
    assert.equal(page.fields.reason.readOnly, false);
    assert.equal(page.submit.disabled, true, 'editing does not authorize a new command while a proposal is pending');
    assert.equal(page.form.fire('submit').defaultPrevented, true);
    assert.equal(page.preview.disabled, false);
    assert.equal(page.form.fire('submit', {submitter:page.preview}).defaultPrevented, false);
    assert.equal(page.store.read(original).phase, 'editing');
  },
  async replacement_context() {
    const env = environment(), nextValues = {...values, supersedes_proposal_public_id:repaymentId};
    const page = env.page({...options, values:nextValues});
    page.store.save(scope, original, 'editing', values); page.start(); await tick();
    assert.equal(page.fields.idempotency_key.value, fresh);
    assert.equal(page.fields.supersedes_proposal_public_id.value, repaymentId);
    assert.equal(page.store.read(original).values.supersedes_proposal_public_id, '');
    assert.equal(page.submit.disabled, false);
    page.window.fire('pagehide'); await tick();
    const old = env.page({...options, values:nextValues, hash:'#split-change-' + original});
    old.start(); await tick();
    assert.equal(old.fields.supersedes_proposal_public_id.value, '');
    assert.equal(old.submit.disabled, true, 'opening an old draft does not borrow the replacement authority');
    assert.equal(old.fields.reason.readOnly, false);
  },
  async preview() {
    const env = environment(), page = env.page(options);
    page.start(); await tick();
    page.fields.new_share_amount_major.value = '15.00'; page.form.fire('input');
    assert.equal(page.form.fire('submit', {submitter:page.preview}).defaultPrevented, false);
    assert.equal(page.store.read(fresh).phase, 'editing');
    page.window.fire('pagehide'); await tick();
    const result = env.page({...options, result:'preview', values:{...values,
      new_share_amount_major:'15.00', settlement_net_amount_major:'-15.00', expected_row_version:'5'}});
    result.start(); await tick();
    assert.equal(result.fields.reason.value, values.reason);
    assert.equal(result.fields.settlement_net_amount_major.value, '-15.00');
    assert.equal(result.store.read(fresh).phase, 'editing');
    assert.equal(result.form.fire('submit').defaultPrevented, false);
    result.fields.expected_return_row_version.value = '99';
    result.window.fire('pagehide'); await tick();
    const recovered = env.page({...options, canCreate:false}); recovered.start(); await tick();
    assert.equal(recovered.fields.expected_return_row_version.value, '2');
    assert.equal(recovered.fields.expected_row_version.value, '5');
    assert.equal(recovered.fields.idempotency_key.value, fresh);
  },
  async command_replacement() {
    const accepted = {...values, command:'accept', proposal_public_id:repaymentId};
    const replacement = {clientRef:fresh, values:{...values, expected_row_version:'5',
      expected_return_row_version:'3', supersedes_proposal_public_id:repaymentId}};
    const env = environment(), page = env.page({...options, ref:original, values:accepted,
      result:'blocked', replacement, canCreate:false});
    page.store.save(scope, original, 'submitted', accepted); page.start(); await tick();
    assert.equal(page.fields.reason.readOnly, true);
    assert.equal(page.preview.hidden, true);
    assert.match(page.form.action, new RegExp('/' + repaymentId + '/accept$'));
    assert.equal(page.replace.hidden, false);
    page.replace.fire('click');
    assert.equal(page.store.read(original), null);
    assert.equal(page.fields.command.value, 'create');
    assert.equal(page.fields.reason.readOnly, false);
    assert.equal(page.preview.hidden, false);
    assert.match(page.form.action, /\/split-changes$/);
    assert.equal(page.fields.expected_return_row_version.value, '3');
    page.fields.reason.value = '核对后修改原因'; page.form.fire('input');
    assert.equal(page.form.fire('submit').defaultPrevented, false);
    assert.equal(page.store.read(fresh).values.reason, '核对后修改原因');
  },
  async ack_and_repayment() {
    const env = environment(), page = env.page({...options,
      ack:{scope, clientRef:original, resultPublicId:repaymentId, values}});
    page.store.save(scope, original, 'submitted', values);
    const repayment = env.page();
    repayment.start(); page.start(); await tick();
    assert.equal(page.store.read(original), null, 'exact split receipt retires only the split intent');
    assert.equal(repayment.submit.disabled, false, 'original leg repayment remains separately available');
    assert.equal(page.submit.disabled, false);
    assert.notEqual(env.requests[0], env.requests[1]);
  },
};
assert.ok(cases[process.argv[4]]);
cases[process.argv[4]]().catch(error => { console.error(error); process.exitCode = 1; });
