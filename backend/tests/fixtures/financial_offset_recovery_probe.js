(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async predicate => {
    for (let n = 0; n < 240; n++) { const result = predicate(); if (result) return result; await pause(25); }
    throw Error("Offset recovery did not settle: " + frame.contentDocument.body.textContent);
  };
  const results = [];
  for (const [id, kind] of [[10, "money"], [11, "reversal"], [12, "offset-original"]]) {
    const url = "/web/expenses/" + id + "/edit?ledger_id=owner";
    const loaded = new Promise(resolve => { frame.onload = resolve; }); frame.src = url; await loaded;
    let form = await wait(() => {
      const node = frame.contentDocument.querySelector('[data-offset-plan-id="' + id + ':' + kind + '"]');
      return node && !node.querySelector('[data-offset-submit]').disabled ? node : null;
    });
    const snapshot = () => [...form.elements].filter(input => input.name && input.type !== "submit" &&
      (input.type !== "radio" || input.checked)).map(input => [input.name, input.value]);
    const changes = id === 12 ? {void_reason: " 原撤销原因 "} : {reason: " 原退款或冲销原因 ", accounting_date: "2026-09-29"};
    if (id === 10) Object.assign(changes, {kind: "chargeback", original_amount: " 0005.50 "});
    for (const [name, value] of Object.entries(changes)) {
      form.elements.namedItem(name).value = value;
      form.dispatchEvent(new frame.contentWindow.Event("input", {bubbles: true}));
    }
    const before = snapshot(), ref = form.elements.namedItem("draft_client_ref").value;
    form.requestSubmit(form.querySelector('[data-offset-submit]'));
    await wait(() => form.dataset.offsetDraftPhase === "blocked" && !form.querySelector('[data-offset-submit]').disabled);
    const frozen = form.elements.namedItem(id === 12 ? "void_reason" : "reason").readOnly &&
      [...form.querySelectorAll('[type="radio"]')].every(input => input.disabled);
    const reloaded = new Promise(resolve => { frame.onload = resolve; }); frame.contentWindow.location.reload(); await reloaded;
    form = await wait(() => {
      const node = frame.contentDocument.querySelector('[data-offset-plan-id="' + id + ':' + kind + '"]');
      return node?.dataset.offsetDraftPhase === "blocked" && !node.querySelector('[data-offset-submit]').disabled ? node : null;
    });
    const saved = Object.fromEntries(before), after = Object.fromEntries(snapshot());
    for (const value of [saved, after]) value.draft_scope = JSON.stringify(Object.entries(JSON.parse(value.draft_scope)).sort());
    const same = Object.keys(saved).every(key => saved[key] === after[key]);
    form.requestSubmit(form.querySelector('[data-offset-submit]'));
    await wait(() => frame.contentWindow.location.search.includes("accepted=1"));
    results.push({kind, frozen, same, differences: Object.keys(saved).filter(key => saved[key] !== after[key]),
      removed: localStorage.getItem("ticketbox:offset-edit-draft:v1:" + ref) === null});
  }
  window.__offsetRecoveryProbe = {results};
})().catch(error => { window.__offsetRecoveryProbe = {error: String(error), stack: error.stack}; });
