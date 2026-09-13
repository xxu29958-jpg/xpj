(async function () {
  const drafts = window.TicketboxManualDrafts;
  const result = {};
  function check(value, label) { if (!value) throw Error(label); }
  async function until(predicate, label) {
    const deadline = performance.now() + 2000;
    while (performance.now() < deadline) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    throw Error(label);
  }
  const form = frame => frame.contentDocument.querySelector('form');
  const state = frame => form(frame)?.dataset.manualDraftState;
  async function frameAt(url, expected) {
    const frame = document.createElement('iframe');
    frame.src = url;
    document.body.append(frame);
    await until(() => state(frame) === expected, 'open:' + expected);
    return frame;
  }
  function fill(frame, name, value) {
    const input = form(frame).elements.namedItem(name);
    input.value = value;
    input.dispatchEvent(new frame.contentWindow.Event('input', {bubbles:true}));
  }
  try {
    const first = await frameAt('/form', 'editing');
    check(!first.contentDocument.querySelector('details').open, 'progressive disclosure');
    fill(first, 'amount_major', '28.50');
    fill(first, 'currency_code', 'EUR');
    fill(first, 'note', '合成备注');
    const ref = form(first).elements.client_ref.value;
    const record = drafts.read(ref);
    check(record.values.csrf_token === undefined, 'no credential retention');
    const loaded = new Promise(resolve => first.addEventListener('load', resolve, {once:true}));
    first.contentWindow.location.reload();
    await loaded;
    await until(() => state(first) === 'editing', 'reload ready');
    check(form(first).elements.amount_major.value === '28.50', 'reload amount');
    check(form(first).elements.note.value === '合成备注', 'reload note');
    check(form(first).elements.client_ref.value === ref, 'reload identity');
    result.reload = true;
    const duplicate = await frameAt('/form#manual-' + ref, 'locked');
    check(form(duplicate).querySelector('fieldset').disabled, 'second editor disabled');
    check(drafts.read(ref).values.amount_major === '28.50', 'second tab unchanged');
    duplicate.remove();
    const fresh = await frameAt('/form', 'editing');
    check(form(fresh).elements.client_ref.value !== ref, 'independent fresh identity');
    fresh.remove();
    result.lock = true;
    // Real native POST. The synthetic server returns a 503, not a saved receipt.
    form(first).querySelector('[data-manual-submit]').click();
    await until(() => first.contentWindow.location.pathname === '/submit', 'unknown native response');
    check(drafts.read(ref).phase === 'submitted', 'submission not acknowledged');
    first.remove();
    const retry = await frameAt('/form#manual-' + ref, 'submitted');
    check(form(retry).elements.amount_major.readOnly, 'submitted input immutable');
    check(form(retry).elements.currency_code.disabled, 'submitted currency immutable');
    check(form(retry).elements.client_ref.value === ref, 'retry identity');
    form(retry).querySelector('[data-manual-submit]').click();
    await until(() => drafts.read(ref) === null, 'canonical consumer retires draft');
    result.retry = true;
    result.ack = true;
    retry.remove();
    // Re-enrollment can expose a readable original, but never a rebound writer.
    const old = await frameAt('/form', 'editing');
    fill(old, 'amount_major', '41');
    const oldRef = form(old).elements.client_ref.value;
    old.remove();
    const replacement = await frameAt('/form?deviceId=replacement#manual-' + oldRef, 'blocked');
    check(form(replacement).elements.amount_major.value === '41', 'old values readable');
    check(form(replacement).querySelector('[data-manual-submit]').disabled, 'old device refused');
    check(drafts.read(oldRef).scope.deviceId === 'device', 'original binding retained');
    replacement.remove();
    for (const axis of ['datasetId', 'clientGeneration', 'accountId', 'ledgerId']) {
      const changed = await frameAt('/form?' + axis + '=changed#manual-' + oldRef, 'blocked');
      check(form(changed).elements.amount_major.value === '', 'no foreign restore:' + axis);
      check(drafts.read(oldRef).values.amount_major === '41', 'foreign record preserved');
      changed.remove();
    }
    result.quarantine = true;
    for (const unavailable of ['noStorage', 'noLocks']) {
      const fallback = await frameAt('/form?' + unavailable + '=1', 'unavailable');
      check(!form(fallback).querySelector('fieldset').disabled, 'native fields stay usable');
      check(!form(fallback).querySelector('[data-manual-submit]').disabled, 'native command stays usable');
      fallback.remove();
    }
    const quota = await frameAt('/form', 'editing');
    fill(quota, 'amount_major', '12');
    const quotaRef = form(quota).elements.client_ref.value;
    Object.defineProperty(quota.contentWindow.Storage.prototype, 'setItem', {value() {throw Error('quota');}});
    fill(quota, 'amount_major', '13');
    check(state(quota) === 'storage-error', 'failed retention visible');
    form(quota).querySelector('[data-manual-submit]').click();
    check(state(quota) === 'storage-error', 'failed snapshot prevents POST');
    check(drafts.read(quotaRef).values.amount_major === '12', 'prior durable input not falsified');
    quota.remove();
    result.storage = true;
    window.__manualDraftProbe = result;
  } catch (error) {
    window.__manualDraftProbe = {error: String(error), completed: result};
  }
})();
