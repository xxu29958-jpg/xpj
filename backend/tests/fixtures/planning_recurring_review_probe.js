(async () => {
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function until(check, label) {
    for (let n = 0; n < 160; n++) { if (check()) return; await pause(25); } throw Error(label);
  }
  const frame = document.createElement("iframe"); document.body.append(frame);
  const kind = new URL(location.href).searchParams.get('kind') || 'recurring-edit';
  let family = 'recurring';
  const form = () => frame.contentDocument?.querySelector('form[data-' + family + '-draft-scope]');
  const save = () => form()?.querySelector('[data-' + family + '-submit]');
  const ready = () => form()?.dataset[family + 'DraftPhase'] && save() && !save().disabled;
  function input(name, value) {
    form().elements.namedItem(name).value = value;
    form().elements.namedItem(name).dispatchEvent(new frame.contentWindow.Event("input", {bubbles:true}));
  }
  frame.src = '/fixture?kind=recurring-create';
  await until(ready, 'create task unavailable');
  input('merchant', '另一份未提交原稿');
  const unrelated = form().elements.namedItem('idempotency_key').value;
  const unrelatedKey = Object.keys(localStorage).find(name => name.endsWith(unrelated));
  const originalDocument = frame.contentDocument;
  family = kind === 'candidate' ? 'candidate' : 'recurring';
  frame.src = '/fixture?kind=' + kind;
  await until(() => frame.contentDocument !== originalDocument && ready(), 'edit task unavailable');
  if (kind === 'candidate') input('next_expected_date', '');
  else input('baseline_amount_yuan', '2500');
  const original = form().elements.namedItem('idempotency_key').value;
  const originalKey = Object.keys(localStorage).find(name => name.endsWith(original));
  form().requestSubmit(save());
  await until(() => form().dataset[family + 'DraftPhase'] === 'blocked', 'refusal not retained');
  if (!localStorage.getItem(originalKey)) throw Error('Rejected input disappeared before review');
  const beforeReview = frame.contentDocument;
  form().requestSubmit(form().querySelector('[data-' + family + '-review]'));
  await until(() => frame.contentDocument !== beforeReview && ready(), 'review did not return an editor');
  const replacement = form().elements.namedItem('idempotency_key').value;
  const replacementKey = Object.keys(localStorage).find(name => name.endsWith(replacement));
  if (original === replacement || localStorage.getItem(originalKey) !== null) throw Error('Reviewed draft left a rejected duplicate');
  const replacementRetainedBeforeSave = !!replacementKey && JSON.parse(localStorage.getItem(replacementKey)).phase === 'editing';
  form().requestSubmit(save());
  await until(() => frame.contentDocument.querySelector('[data-confirmed]'), 'new command did not confirm');
  if (localStorage.getItem(replacementKey) !== null) throw Error('Accepted task remains pending');
  window.__recurringReview = {original, replacement, replacementRetainedBeforeSave, confirmed:true,
    unrelatedRetained: JSON.parse(localStorage.getItem(unrelatedKey)).values.merchant === '另一份未提交原稿'};
})().catch(error => window.__recurringReview = {error:String(error), stack:error.stack});
