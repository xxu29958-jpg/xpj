(async function () {
  const result = {before: null, after: null, error: null};
  let stage = 'open original income form';
  const names = [
    'label', 'amount_yuan', 'source_type', 'frequency', 'pay_day',
    'income_month_year', 'income_month_number', 'intent_month',
    'home_currency_code', 'idempotency_key'
  ];
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const frame = document.createElement('iframe');
  const form = () => frame.contentDocument.querySelector('form[action="/web/income-plans/create"]');
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
  function documentLoaded() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('income document load timed out')), 2500);
      frame.addEventListener('load', () => {clearTimeout(timeout); resolve();}, {once: true});
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
  } catch (error) {
    result.error = {stage, message: String(error?.message || error)};
  }
  window.__incomeDraftRefreshProbe = result;
})();
