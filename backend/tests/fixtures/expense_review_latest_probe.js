/* Exercise the real page and drawer through one original draft and an explicit fresh read. */
(async function () {
  if (window.top !== window) return;
  const result = {before: null, after: null, retained: null, error: null};
  const frame = document.createElement('iframe');
  const drawer = new URLSearchParams(location.search).get('drawer') === 'true';
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const form = () => frame.contentDocument.querySelector('form[action="/web/expenses/42/save"]');
  const field = name => form().elements.namedItem(name);
  const snapshot = () => Object.fromEntries(['amount_yuan', 'merchant', 'expected_row_version', 'draft_ref'].map(name => [name, field(name).value]));
  async function until(predicate) {
    const end = performance.now() + 3000;
    while (performance.now() < end) {
      if (predicate()) return;
      await pause(25);
    }
    throw Error('Review did not become ready: ' + JSON.stringify(form() ? snapshot() : null));
  }
  try {
    const loaded = new Promise(resolve => frame.addEventListener('load', resolve, {once: true}));
    frame.src = drawer ? '/web/pending?ledger_id=owner' : '/web/expenses/42/edit?ledger_id=owner&return_to=pending';
    document.body.append(frame);
    await loaded;
    if (drawer) frame.contentDocument.querySelector('[data-expense-id="42"] [data-fragment-url]').click();
    await until(() => form()?.dataset.expensereviewDraftPhase === 'editing' && !field('amount_yuan').readOnly);
    result.saved = snapshot();
    field('amount_yuan').value = '29.00';
    field('amount_yuan').dispatchEvent(new frame.contentWindow.Event('input', {bubbles: true}));
    await fetch('/probe-latest-bill', {method: 'POST'});
    form().querySelector('[formaction$="/fx-status"]').click();
    await until(() => frame.contentDocument.querySelector('[data-drawer-reload]') && form()?.dataset.expensereviewDraftPhase === 'editing');
    result.before = snapshot();
    frame.contentDocument.querySelector('[data-drawer-reload]').click();
    await until(() => form()?.dataset.expensereviewDraftPhase === 'editing' &&
      !field('amount_yuan').readOnly && field('draft_ref').value !== result.saved.draft_ref);
    result.after = snapshot();
    result.retained = JSON.parse(localStorage.getItem('ticketbox:expensereview-edit-draft:v1:' + result.saved.draft_ref));
  } catch (error) {
    result.after = form() ? snapshot() : null;
    result.error = String(error?.message || error);
  }
  window.__expenseReviewResult = result;
})();
