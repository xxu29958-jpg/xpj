/* The real comparison owns one original decision through cancellation, refusal and reply loss. */
(async function () {
  "use strict";
  const key = "duplicate-decision-probe", prefix = "ticketbox:duplicatechoice-edit-draft:v1:";
  const query = new URL(location.href).searchParams;
  const state = JSON.parse(sessionStorage.getItem(key) || "null") ||
    {stage: "start", action: query.get("choice"), fault: query.get("fault"), requests: []};
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  let waitStep = 0;
  const wait = async condition => {
    const step = ++waitStep, started = performance.now();
    for (let n = 0; n < 200; n++) { if (condition()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
    throw Error("duplicate recovery stalled at " + state.stage + ":" + step + " after " + Math.round(performance.now() - started) + "ms; last condition=" + Boolean(condition()));
  };
  const form = () => document.querySelector('form[action="/web/duplicates/42/' + state.action + '"]');
  const submit = () => form()?.querySelector("[data-duplicatechoice-submit]");
  const originalFetch = window.fetch;
  window.fetch = async (url, options) => {
    if (options?.method !== "POST" || new URL(url, location.href).pathname !== "/web/duplicates/42/" + state.action) return originalFetch(url, options);
    state.requests.push([...options.body].filter(([name]) => name !== "csrf_token")); save();
    const response = await originalFetch(url, options);
    if (state.fault === "reply" && state.requests.length === 1) {
      assert(response.ok, "first decision was not accepted");
      await response.text(); state.replyLost = true; save(); throw new TypeError("accepted decision reply lost");
    }
    return response;
  };
  async function start() {
    await wait(() => form()?.dataset.duplicatechoiceDraftPhase === "editing" && !submit().disabled);
    state.ref = form().elements.draft_ref.value; state.command = form().elements.idempotency_key.value;
    if (state.action !== "keep") {
      submit().click(); await wait(() => document.querySelector("#tb-confirm-modal[open]"));
      document.querySelector(".tb-confirm-cancel").click();
      await new Promise(resolve => setTimeout(resolve, 50));
      assert(state.requests.length === 0, "cancel already mutated a bill");
    }
    if (state.fault === "conflict") await originalFetch("/duplicate-peer", {method: "POST"});
    submit().click();
    if (state.action !== "keep") {
      await wait(() => document.querySelector("#tb-confirm-modal[open]")); document.querySelector(".tb-confirm-ok").click();
    }
    await wait(() => state.requests.length && !submit().disabled && (state.replyLost || form().dataset.duplicatechoiceDraftPhase === "blocked"));
    if (state.fault === "reply") await originalFetch("/duplicate-peer", {method: "POST"});
    state.stage = "shelf"; save(); location.assign("/web/duplicates?ledger_id=owner");
  }
  async function restore() {
    await wait(() => document.querySelector('[data-duplicatechoice-ref="' + state.ref + '"]'));
    state.stage = "task"; save();
    const link = document.querySelector('[data-duplicatechoice-ref="' + state.ref + '"]');
    link.closest("details").open = true; link.click();
  }
  async function resume() {
    await wait(() => form()?.dataset.duplicatechoiceDraftPhase && !submit().disabled);
    const record = JSON.parse(localStorage.getItem(prefix + state.ref));
    assert(record.values.expected_row_version === "4" && record.values.idempotency_key === state.command, "restoration rebased the original");
    if (state.fault === "reply") {
      assert(form().dataset.duplicatechoiceDraftPhase === "submitted", "unknown original did not reopen");
      state.stage = "done"; save(); submit().click();
    } else {
      assert(form().dataset.duplicatechoiceDraftPhase === "blocked", "refusal was lost");
      state.stage = "prepared"; save(); form().querySelector("[data-duplicatechoice-review]").click();
    }
  }
  async function prepare() {
    await wait(() => form()?.dataset.duplicatechoiceDraftPhase === "editing" && !submit().disabled);
    assert(form().elements.expected_row_version.value === "9" && form().elements.idempotency_key.value !== state.command, "explicit review did not adopt fresh basis and key");
    const facts = await (await originalFetch("/duplicate-facts")).json();
    assert(facts.current_version === 9 && facts.original_version === 11 && facts.receipt_count === 0 && state.requests.length === 1,
      "review itself changed a fact or wrote a receipt");
    state.stage = "done"; save(); submit().click();
  }
  async function finish() {
    const facts = await (await originalFetch("/duplicate-facts")).json();
    assert(!localStorage.getItem(prefix + state.ref), "accepted decision remained an unknown draft");
    assert(facts.current_merchant === "后来修改本次" && facts.original_merchant === "后来修改参考" && facts.original_version === 11, "later manual facts were overwritten");
    if (state.fault === "reply") {
      assert(facts.current_version === 9 && JSON.stringify(state.requests[0]) === JSON.stringify(state.requests[1]), "replay changed the original command or current bill");
    } else assert(facts.current_version === 10 && facts.current_duplicate === "none", "the explicitly reviewed decision did not apply");
    state.complete = true; window.__expenseReviewResult = state;
  }
  try {
    if (state.stage === "start") await start();
    else if (state.stage === "shelf") await restore();
    else if (state.stage === "task") await resume();
    else if (state.stage === "prepared") await prepare();
    else if (state.stage === "done") await finish();
  } catch (error) {
    window.__expenseReviewResult = {error: String(error), state: structuredClone(state), body: document.body.innerText,
      controls: [...document.querySelectorAll("form[data-duplicatechoice-plan-id]")].map(current => ({
        task: current.dataset.duplicatechoicePlanId, phase: current.dataset.duplicatechoiceDraftPhase,
        disabled: current.querySelector("[data-duplicatechoice-submit]").disabled,
        status: current.querySelector("[data-duplicatechoice-draft-status]").textContent,
      }))};
  }
})();
