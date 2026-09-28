(async function () {
  const result = {before: null, after: null, unknown: null, duplicate: null, completed: null, discarded: null, error: null};
  let stage = 'open original income form';
  const names = [
    'label', 'amount_yuan', 'source_type', 'frequency', 'pay_day',
    'income_month_year', 'income_month_number', 'intent_month',
    'home_currency_code', 'idempotency_key'
  ];
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const frame = document.createElement('iframe');
  const form = () => frame.contentDocument.querySelector('form[action="/web/income-plans/create"]');
  const submit = target => target.contentDocument.querySelector('form[action="/web/income-plans/create"] [type="submit"]:not([name="review_new"])');
  const storageKey = ref => 'ticketbox:income-create-draft:v1:' + ref;
  const record = ref => JSON.parse(window.localStorage.getItem(storageKey(ref)));
  async function until(predicate) {
    const deadline = performance.now() + 1500;
    while (performance.now() < deadline) {
      if (predicate()) return;
      await pause(25);
    }
    throw Error('business state did not settle: ' + stage);
  }
  function field(name) {
    const input = form()?.elements.namedItem(name);
    if (!input) throw Error('original income form missing field: ' + name);
    return input;
  }
  function snapshot() {
    const doc = frame.contentDocument;
    return {
      fields: Object.fromEntries(names.map(name => [name, field(name).value])),
      amountLabel: doc.querySelector('label[for="income-create-amount"]')?.textContent.trim(),
      amountPlaceholder: field('amount_yuan').placeholder,
      amountInputmode: field('amount_yuan').inputMode,
      intentNotice: form().querySelector('p.meta')?.textContent.trim(),
      hash: frame.contentWindow.location.hash,
      navigationType: frame.contentWindow.performance.getEntriesByType('navigation')[0]?.type
    };
  }
  function documentLoaded(target = frame) {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('income document load timed out: ' + stage)), 2500);
      target.addEventListener('load', () => {clearTimeout(timeout); resolve();}, {once: true});
    });
  }
  try {
    // The iframe owns the genuine loopback origin, storage and navigator.locks.
    const opened = documentLoaded();
    frame.src = '/web/income-plans?ledger_id=income-ledger';
    document.body.append(frame);
    await opened;
    await pause(100);
    stage = 'fill original income form';
    for (const [name, value] of Object.entries({
      label: '九月接单收入草稿', amount_yuan: ' 001200 ', source_type: 'freelance',
      frequency: 'monthly', pay_day: '23', income_month_year: '2026', income_month_number: '9'
    })) {
      const input = field(name);
      input.value = value;
      for (const type of ['input', 'change']) {
        input.dispatchEvent(new frame.contentWindow.Event(type, {bubbles: true}));
      }
    }
    await pause(150);
    result.before = snapshot();
    stage = 'reload original income form';
    const reloaded = documentLoaded();
    // Preserve whatever address/hash the actual page consumer assigned to this draft.
    frame.contentWindow.location.reload();
    await reloaded;
    stage = 'observe refreshed original income form';
    // Allow asynchronous restore to settle, but always report actual fields.
    // Missing persistence fails Python's business assertion, never an enhancer-marker timeout.
    const deadline = performance.now() + 1000;
    do {
      await pause(25);
      result.after = snapshot();
      if (names.every(name => result.after.fields[name] === result.before.fields[name])) break;
    } while (performance.now() < deadline);
    if (!names.every(name => result.after.fields[name] === result.before.fields[name])) {
      // Keep the first business RED at the observed lost fields, before attempting the rest of the chain.
      window.__incomeDraftRefreshProbe = result;
      return;
    }
    const originalRef = result.before.fields.idempotency_key;
    stage = 'correct raw amount without replacing the restored task';
    field('amount_yuan').value = '1200';
    field('amount_yuan').dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    await pause(50);
    stage = 'submit original form to synthetic unavailable response';
    await until(() => submit(frame) && !submit(frame).disabled);
    submit(frame).click();
    await until(() => record(originalRef)?.phase === 'blocked' && !submit(frame).disabled);
    result.unknown = {
      ...snapshot(), record: record(originalRef),
      frozen: names.filter(name => field(name).type !== 'hidden').every(name =>
        field(name).tagName === 'SELECT' ? field(name).disabled : field(name).readOnly)
    };

    stage = 'open same original draft in a second tab';
    const duplicate = document.createElement('iframe');
    const duplicateLoaded = documentLoaded(duplicate);
    duplicate.src = '/web/income-plans?ledger_id=income-ledger#income-create-' + originalRef;
    document.body.append(duplicate);
    await duplicateLoaded;
    await pause(100);
    submit(duplicate).click();
    await pause(100);
    result.duplicate = {submitDisabled: submit(duplicate).disabled, record: record(originalRef)};
    duplicate.remove();

    stage = 'retry original submission and consume matched synthetic receipt';
    const acknowledged = documentLoaded();
    submit(frame).click();
    await acknowledged;
    stage = 'verify matched ACK retires original and enables fresh form';
    await until(() => submit(frame) && !submit(frame).disabled);
    result.completed = {
      originalRemoved: window.localStorage.getItem(storageKey(originalRef)) === null,
      newFormAvailable: field('label').value === '' && field('amount_yuan').value === '' &&
        !field('label').readOnly && !field('source_type').disabled && !submit(frame).disabled,
      newKey: field('idempotency_key').value,
      location: frame.contentWindow.location.pathname + frame.contentWindow.location.search,
      hash: frame.contentWindow.location.hash
    };
    stage = 'deliberately retire a separate unknown local draft';
    const unwantedRef = field('idempotency_key').value;
    field('label').value = '已核对后不再续办的计划';
    field('amount_yuan').value = '80.00';
    field('label').dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    submit(frame).click();
    await until(() => record(unwantedRef)?.phase === 'blocked' && !submit(frame).disabled);
    let confirmation = '';
    frame.contentWindow.confirm = message => { confirmation = message; return true; };
    const retired = documentLoaded();
    frame.contentDocument.querySelector('[data-income-discard]').click();
    await retired;
    await until(() => submit(frame) && !submit(frame).disabled);
    result.discarded = {
      removed: window.localStorage.getItem(storageKey(unwantedRef)) === null,
      confirmation, newFormAvailable: field('label').value === '' && field('amount_yuan').value === '',
    };
  } catch (error) {
    result.error = {stage, message: String(error?.message || error)};
  }
  window.__incomeDraftRefreshProbe = result;
})();
