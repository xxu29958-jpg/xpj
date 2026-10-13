(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async predicate => {
    for (let n = 0; n < 240; n++) { const result = predicate(); if (result) return result; await pause(25); }
    throw Error("CSV recovery did not settle: " + frame.contentDocument.body.textContent);
  };
  const path = "/web/import/eed35556-b580-468c-9406-6087538829a4/rows/3/review?ledger_id=family";
  const open = async () => {
    const loaded = new Promise(resolve => { frame.onload = resolve; });
    frame.src = path; await loaded;
    return wait(() => {
      const form = frame.contentDocument.querySelector("#import-event-form");
      return form && !form.querySelector("[data-csvreview-submit]").disabled ? form : null;
    });
  };
  let form = await open();
  form.elements.namedItem("reason").value = "原退款说明";
  form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
  const ref = form.elements.namedItem("draft_client_ref").value;
  form.requestSubmit(form.querySelector("[data-csvreview-submit]"));
  await wait(() => form.dataset.csvreviewDraftPhase === "blocked" && !form.querySelector("[data-csvreview-submit]").disabled);
  form = await open();
  const frozen = form.elements.namedItem("reason").readOnly && form.elements.namedItem("expected_row_version").value === "9";
  const reviewHidden = form.querySelector("[data-csvreview-review]").hidden;
  form.requestSubmit(form.querySelector("[data-csvreview-submit]"));
  await wait(() => localStorage.getItem("ticketbox:csvreview-edit-draft:v1:" + ref) === null);
  window.__csvRecovery = {frozen, reviewHidden, originalRemoved: true};
})().catch(error => { window.__csvRecovery = {error: String(error), stack: error.stack}; });
