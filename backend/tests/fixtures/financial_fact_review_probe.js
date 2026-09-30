(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async predicate => {
    for (let n = 0; n < 240; n++) { const result = predicate(); if (result) return result; await pause(25); }
    throw Error("Financial review did not settle: " + frame.contentDocument.body.textContent);
  };
  const loaded = new Promise(resolve => { frame.onload = resolve; });
  frame.src = "/web/expenses/7/correct?ledger_id=owner"; await loaded;
  let form = await wait(() => {
    const node = frame.contentDocument.querySelector(".correction-form");
    return node && !node.querySelector('[data-correction-submit]').disabled ? node : null;
  });
  for (const [name, value] of Object.entries({reason: "保留原原因", merchant: "自己的商家", amount_yuan: "0005.50",
      original_currency: "CNY", value_score: "4", regret_score: "2"})) {
    form.elements.namedItem(name).value = value;
    form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
  }
  const ref = form.elements.namedItem("draft_client_ref").value;
  form.requestSubmit(form.querySelector('[data-correction-submit]'));
  if (window.financialNativeReview) {
    await wait(() => form.dataset.correctionDraftPhase === "blocked" && !form.querySelector('[data-correction-submit]').disabled);
    form.querySelector('[data-correction-original-result]').click();
    form = await wait(() => {
      const node = frame.contentDocument.querySelector(".correction-form");
      return node?.dataset.correctionNativeResult === "rejected" && !node.querySelector('[data-correction-submit]').disabled ? node : null;
    });
  }
  await wait(() => !form.querySelector('[data-correction-review]').hidden && !form.querySelector('[data-correction-review]').disabled);
  form.requestSubmit(form.querySelector('[data-correction-review]'));
  form = await wait(() => {
    const node = frame.contentDocument.querySelector(".correction-form");
    return node?.dataset.correctionNativeResult === "prepared" && !node.querySelector('[data-correction-submit]').disabled ? node : null;
  });
  form.requestSubmit(form.querySelector('[data-correction-submit]'));
  await wait(() => frame.contentWindow.location.pathname.endsWith("/edit"));
  window.__financialReviewProbe = {originalRemoved: localStorage.getItem("ticketbox:correction-edit-draft:v1:" + ref) === null};
})().catch(error => { window.__financialReviewProbe = {error: String(error), stack: error.stack}; });
