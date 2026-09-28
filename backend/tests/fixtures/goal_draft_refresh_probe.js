(async function () {
  const spec = window.__goalDraftCase;
  const result = {before: null, after: null, reopened: null, error: null};
  let frame = document.createElement('iframe'), stage = 'open goal form';
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const form = () => frame.contentDocument.querySelector('form[action="' + spec.action + '"]');
  const field = name => form().elements.namedItem(name);
  const submit = () => form().querySelector('[type="submit"]:not([name])');
  async function until(predicate) {
    const deadline = performance.now() + 2000;
    while (performance.now() < deadline) {
      if (predicate()) return;
      await pause(25);
    }
    throw Error('goal state did not settle: ' + stage);
  }
  function loaded() {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('goal page did not load: ' + stage)), 3000);
      frame.addEventListener('load', () => { clearTimeout(timer); resolve(); }, {once: true});
    });
  }
  function snapshot() {
    return {fields: Object.fromEntries(spec.fields.map(name => [name, field(name).value])),
      navigationType: frame.contentWindow.performance.getEntriesByType('navigation')[0]?.type,
      current: frame.contentDocument.querySelector('[aria-label="当前已保存的目标"]')?.textContent.trim(),
      amountLabel: frame.contentDocument.querySelector('label[for="goal-' + spec.kind + '-amount"]')?.textContent.trim()};
  }
  async function restored() {
    const deadline = performance.now() + 1500;
    let value;
    do {
      await pause(25); value = snapshot();
      if (spec.fields.every(name => value.fields[name] === result.before.fields[name])) return value;
    } while (performance.now() < deadline);
    return value;
  }
  try {
    let loading = loaded();
    frame.src = spec.open; document.body.append(frame); await loading;
    const deadline = performance.now() + 2000;
    while (field('name').readOnly && performance.now() < deadline) await pause(25);
    if (field('name').readOnly) throw Error('original goal cannot be edited');
    for (const [name, value] of Object.entries(spec.input)) {
      field(name).value = value;
      field(name).dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    }
    await pause(100); result.before = snapshot();
    stage = 'reload without losing original goal';
    loading = loaded(); frame.contentWindow.location.reload(); await loading;
    result.after = await restored();
    if (!spec.fields.every(name => result.after.fields[name] === result.before.fields[name])) {
      window.__goalDraftProbe = result; return;
    }
    stage = 'close and reopen from current month';
    frame.remove(); frame = document.createElement('iframe');
    loading = loaded(); frame.src = spec.reopen; document.body.append(frame); await loading;
    result.reopened = await restored();
    stage = 'publish the original with an unknown receipt';
    form().requestSubmit(submit());
    await until(() => form().dataset.goalDraftPhase === 'blocked');
    result.unknown = snapshot();
    result.frozen = field('name').readOnly && field('target_amount_yuan').readOnly;
    stage = 'reopen unresolved original after later goal changes';
    loading = loaded(); frame.contentWindow.location.reload(); await loading;
    await until(() => form().dataset.goalDraftPhase === 'blocked' && !submit().disabled);
    result.unresolved = snapshot();
    result.archived = form().dataset.goalArchived === 'true';
    stage = 'accept same original then return to the original task';
    loading = loaded(); form().requestSubmit(submit()); await loading;
    result.destination = frame.contentWindow.location.pathname + frame.contentWindow.location.search + frame.contentWindow.location.hash;
    result.remaining = window.localStorage.getItem('ticketbox:goal-' + spec.kind + '-draft:v1:' + result.before.fields.idempotency_key);
  } catch (error) { result.error = {stage, message: String(error?.message || error)}; }
  window.__goalDraftProbe = result;
})();
