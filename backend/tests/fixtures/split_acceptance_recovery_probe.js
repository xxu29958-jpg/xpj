(async () => {
  const frame = document.createElement("iframe"); document.body.append(frame);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const wait = async predicate => {
    for (let n = 0; n < 240; n++) { const result = predicate(); if (result) return result; await pause(25); }
    throw Error("Acceptance did not settle: " + frame.contentDocument.body.textContent);
  };
  const navigate = async url => {
    const loaded = new Promise(resolve => { frame.onload = resolve; }); frame.src = url; await loaded;
  };
  const readyForm = () => wait(() => {
    const form = frame.contentDocument.querySelector("form[data-splitaccept-draft-scope]");
    const button = form?.elements.namedItem("splitaccept_submit");
    return button?.form === form && !button.disabled ? form : null;
  });
  const openInvitation = async () => {
    const entry = frame.contentDocument.querySelector("[data-splitaccept-open]");
    if (!entry) throw Error("Inbox has no invitation task entry");
    const loaded = new Promise(resolve => { frame.onload = resolve; }); entry.click(); await loaded;
  };
  const inbox = "/web/bill-splits/inbox?ledger_id=viewer-book";
  await navigate(inbox);
  await openInvitation();
  let form = await readyForm();
  const target = form.elements.namedItem("target_ledger_id");
  target.value = "travel"; target.dispatchEvent(new frame.contentWindow.Event("change", {bubbles: true}));
  const ref = form.elements.namedItem("draft_ref").value;
  const key = "ticketbox:splitaccept-edit-draft:v1:" + ref;
  await navigate(inbox);
  await openInvitation();
  form = await readyForm();
  const selectedAfterReload = form.elements.namedItem("target_ledger_id").value;
  if (selectedAfterReload !== "travel") throw Error("Selected target replaced");
  form.requestSubmit(form.elements.namedItem("splitaccept_submit"));
  await wait(() => form.dataset.splitacceptDraftPhase === "blocked" && !form.elements.namedItem("splitaccept_submit").disabled);
  if (!form.elements.namedItem("target_ledger_id").disabled || !form.querySelector("[data-splitaccept-review]").hidden) {
    throw Error("Unknown acceptance became editable");
  }
  await navigate(inbox);
  const link = await wait(() => frame.contentDocument.querySelector("[data-splitaccept-draft-list] a"));
  if (frame.contentDocument.querySelector("form[action$='/accept']")) throw Error("Accepted invitation offered a new write in inbox");
  const recovery = link.href;
  const changed = new URL(recovery); changed.searchParams.set("changed", "1");
  await navigate(changed.href);
  await wait(() => frame.contentDocument.querySelector("[data-splitaccept-draft-status]").textContent.includes("原浏览器身份"));
  const scopeBlocked = frame.contentDocument.querySelector("[data-splitaccept-submit]").disabled;
  await navigate(recovery);
  form = await readyForm();
  const restoredName = form.elements.namedItem("target_ledger_id").selectedOptions[0].textContent;
  form.requestSubmit(form.elements.namedItem("splitaccept_submit"));
  await wait(() => form.querySelector("[data-splitaccept-draft-status]").textContent.includes("暂未收到保存回执"));
  const wrongReceiptRetained = localStorage.getItem(key) !== null;
  form.requestSubmit(form.elements.namedItem("splitaccept_submit"));
  await wait(() => new URL(frame.contentWindow.location.href).searchParams.has("accepted"));
  window.__splitAcceptanceRecovery = {selectedAfterReload, scopeBlocked, restoredName, wrongReceiptRetained,
    originalRemoved: localStorage.getItem(key) === null};
})().catch(error => { window.__splitAcceptanceRecovery = {error: String(error), stack: error.stack}; });
