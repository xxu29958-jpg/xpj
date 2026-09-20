/* The shared, shipped intent consumer must preserve both OCC legs and command identity. */
const assert = require('node:assert/strict');
const {environment, scope, original, fresh, target, repaymentId, tick} = require('./repayment_draft_contract.cjs');
const values = {debt_public_id:target, ledger_id:'ledger', origin_binding:JSON.stringify(scope),
  home_currency_code:'CNY', command:'create', proposal_public_id:'', expected_row_version:'4',
  expected_return_row_version:'2', new_share_amount_major:'20.00', settlement_net_amount_major:'-10.00',
  reason:'商家部分退款，双方重新约定', supersedes_proposal_public_id:''};
const options = {splitChange:true, fieldNames:Object.keys(values), draftPrefix:'ticketbox:split-change-draft:v1:', values};
const cases = {
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
