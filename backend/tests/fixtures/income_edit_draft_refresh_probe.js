(async function () {
  const result = {before: null, after: null, reopened: null, peer: null, error: null};
  const names = ['label', 'amount_yuan', 'source_type', 'frequency', 'income_month', 'pay_day',
    'intent_month', 'expected_row_version', 'idempotency_key'];
  let stage = 'open original income editor';
  let frame = document.createElement('iframe');
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const form = target => target.contentDocument.querySelector('form[action$="/edit"]');
  const field = (target, name) => form(target).elements.namedItem(name);
  async function until(predicate) {
    const deadline = performance.now() + 2000;
    while (performance.now() < deadline) {
      if (predicate()) return;
      await pause(25);
    }
    throw Error('business state did not settle: ' + stage);
  }
  function loaded(target) {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('income editor load timed out: ' + stage)), 3000);
      target.addEventListener('load', () => { clearTimeout(timeout); resolve(); }, {once: true});
    });
  }
  function snapshot(target) {
    const doc = target.contentDocument;
    return {
      fields: Object.fromEntries(names.map(name => [name, field(target, name).value])),
      hash: target.contentWindow.location.hash,
      navigationType: target.contentWindow.performance.getEntriesByType('navigation')[0]?.type,
      amountLabel: doc.querySelector('label[for="income-edit-amount"]')?.textContent.trim(),
      intentNotice: (doc.querySelector('[data-income-intent]') || doc.querySelector('header .product-page-summary'))?.textContent.trim(),
      current: doc.querySelector('[aria-label="当前已保存的收入计划"]')?.textContent.trim(),
      status: doc.querySelector('[data-income-draft-status]')?.textContent.trim(),
      scriptErrors: target.contentWindow.__incomeScriptErrors || [],
    };
  }
  const matches = snap => names.every(name => snap.fields[name] === result.before.fields[name]);
  async function observeOriginal(target) {
    const deadline = performance.now() + 1200;
    let value;
    do {
      await pause(25);
      value = snapshot(target);
      if (matches(value)) return value;
    } while (performance.now() < deadline);
    return value;
  }
  try {
    let loading = loaded(frame);
    frame.src = '/web/income-plans/income-original/edit?ledger_id=income-ledger&intent_month=2026-09';
    document.body.append(frame);
    await loading;
    await until(() => !field(frame, 'label').readOnly && !field(frame, 'source_type').disabled);
    stage = 'retain original raw correction';
    for (const [name, value] of Object.entries({label: '九月调薪原稿', amount_yuan: ' 001200 ',
      source_type: 'freelance', frequency: 'monthly', income_month: '2026-11', pay_day: '23'})) {
      const input = field(frame, name);
      input.value = value;
      input.dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
      input.dispatchEvent(new frame.contentWindow.Event('change', {bubbles: true}));
    }
    await pause(150);
    result.before = snapshot(frame);
    stage = 'reload while another revision is now visible';
    loading = loaded(frame);
    frame.contentWindow.location.reload();
    await loading;
    result.after = await observeOriginal(frame);
    if (!matches(result.after)) { window.__incomeEditDraftProbe = result; return; }

    stage = 'close editor and reopen from the next month';
    frame.remove();
    frame = document.createElement('iframe');
    loading = loaded(frame);
    frame.src = '/web/income-plans/income-original/edit?ledger_id=income-ledger&intent_month=2026-10';
    document.body.append(frame);
    await loading;
    result.reopened = await observeOriginal(frame);
    if (!matches(result.reopened)) { window.__incomeEditDraftProbe = result; return; }

    stage = 'open a different income plan without adopting this draft';
    const peer = document.createElement('iframe');
    loading = loaded(peer);
    peer.src = '/web/income-plans/income-peer/edit?ledger_id=income-ledger&intent_month=2026-10';
    document.body.append(peer);
    await loading;
    await until(() => !field(peer, 'label').readOnly && !field(peer, 'source_type').disabled);
    result.peer = snapshot(peer);
    result.originalAfterPeer = snapshot(frame);
  } catch (error) {
    result.error = {stage, message: String(error?.message || error)};
  }
  window.__incomeEditDraftProbe = result;
})();
