(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async predicate => {
    for (let n = 0; n < 240; n++) { const result = predicate(); if (result) return result; await pause(25); }
    throw Error("Financial recovery did not settle: " + frame.contentDocument.body.textContent);
  };
  const open = async () => {
    const loaded = new Promise(resolve => { frame.onload = resolve; });
    frame.src = "/web/expenses/7/correct?ledger_id=owner"; await loaded;
    return wait(() => {
      const form = frame.contentDocument.querySelector(".correction-form");
      return form && !form.querySelector('[data-correction-submit]').disabled ? form : null;
    });
  };
  let form = await open();
  for (const [name, value] of Object.entries({reason: "原提交原因", merchant: "原提交商家", original_currency: "USD", amount_yuan: "005.50",
      value_score: "4", regret_score: "2"})) {
    form.elements.namedItem(name).value = value;
    form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
  }
  const original = [...new FormData(form)].filter(([name]) => name !== "csrf_token");
  form.requestSubmit(form.querySelector('[data-correction-submit]'));
  await wait(() => form.dataset.correctionDraftPhase === "blocked" && !form.querySelector('[data-correction-submit]').disabled);
  const frozen = form.querySelector('[name="merchant"]').readOnly && form.querySelector('[name="value_score"]').disabled;
  const reviewHidden = form.querySelector('[data-correction-review]').hidden;
  const ref = form.elements.namedItem("idempotency_key").value;
  form = await open();
  form.requestSubmit(form.querySelector('[data-correction-submit]'));
  await wait(() => frame.contentWindow.location.pathname.endsWith("/edit"));
  window.__financialRecoveryProbe = {original, frozen, reviewHidden,
    originalRemoved: localStorage.getItem("ticketbox:correction-edit-draft:v1:" + ref) === null};
})().catch(error => { window.__financialRecoveryProbe = {error: String(error), stack: error.stack}; });
