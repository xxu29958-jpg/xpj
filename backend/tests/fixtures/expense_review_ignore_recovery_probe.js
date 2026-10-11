/* Both original decisions survive reload; undo never acquires a later rejection. */
(async function () {
  "use strict";
  const stateKey = "expense-ignore-recovery", prefix = "ticketbox:expensereview-edit-draft:v1:";
  const query = new URL(location.href).searchParams;
  const state = JSON.parse(sessionStorage.getItem(stateKey) || "null") ||
    {stage: "edit", entry: query.get("entry"), later: query.get("later") === "1", requests: {reject: [], undo: []}};
  const save = () => sessionStorage.setItem(stateKey, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => {
    for (let n = 0; n < 200; n++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
    throw Error("ignore recovery stalled at " + state.stage);
  };
  const form = () => document.querySelector("form[data-expensereview-plan-id]");
  const primary = () => form()?.querySelector("[data-expensereview-submit]");
  const undo = () => document.querySelector("form[data-expenseundo-plan-id]");
  const undoSubmit = () => undo()?.querySelector("[data-expenseundo-submit]");
  const requestLock = navigator.locks.request.bind(navigator.locks);
  navigator.locks.request = (name, options, callback) => requestLock(name, options, async lock => {
    if (state.stage === "resumeFinancial" && name.startsWith(prefix)) await new Promise(resolve => setTimeout(resolve, 300));
    return callback(lock);
  });
  const originalFetch = window.fetch;
  window.fetch = async (url, options) => {
    const action = new URL(url, location.href).pathname.split("/").pop();
    if (options?.method !== "POST" || !["reject", "undo"].includes(action)) return originalFetch(url, options);
    state.requests[action].push([...options.body].filter(([name]) => name !== "csrf_token")); save();
    const response = await originalFetch(url, options);
    assert(response.ok, action + " was not accepted");
    if (!state[action + "_lost"]) {
      await response.text(); state[action + "_lost"] = true; save();
      throw new TypeError("accepted " + action + " reply lost");
    }
    return response;
  };
  async function ignoreOriginal() {
    if (state.entry === "drawer") {
      await wait(() => window.TicketboxWeb?.drawerApi);
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    }
    await wait(() => form()?.dataset.expensereviewDraftPhase === "editing" && !primary().disabled && !form().elements.merchant.readOnly);
    form().elements.merchant.value = "忽略前的原填写";
    form().elements.merchant.dispatchEvent(new Event("input", {bubbles: true}));
    state.ref = form().elements.draft_ref.value; state.key = form().elements.idempotency_key.value;
    state.stage = "rejectSent"; save();
    form().querySelector(".review-more-actions summary")?.click();
    form().querySelector('button[formaction$="/reject"]').click();
    await wait(() => document.querySelector("#tb-confirm-modal[open]") || state.requests.reject.length);
    assert(state.requests.reject.length === 0, "ignore was sent before human confirmation opened");
    document.querySelector("#tb-confirm-modal .tb-confirm-ok").click();
    await wait(() => state.reject_lost && !primary().disabled);
    assert(JSON.parse(localStorage.getItem(prefix + state.ref)).values.command_action === "reject", "ignore original missing");
    state.stage = "rejectReload"; save(); location.reload();
  }
  async function startUndo() {
    await wait(() => undo()?.dataset.expenseundoDraftPhase === "editing" && !undoSubmit().disabled);
    document.getAnimations().filter(animation => animation.animationName === "undo-banner-dismiss").forEach(animation => animation.finish());
    assert(undo().closest(".undo-banner").getBoundingClientRect().height > 0, "original undo task disappeared before the user could continue");
    const retained = JSON.parse(localStorage.getItem(prefix + state.ref));
    assert(retained.phase === "editing" && retained.values.merchant === "忽略前的原填写" &&
      retained.values.idempotency_key === state.key && retained.values.expected_row_version === "4", "ignore consumed or rebased financial input");
    assert(undo().elements.expected_row_version.value === "5", "undo did not target the first rejection");
    state.undoKey = undo().elements.idempotency_key.value; state.stage = "undoSent"; save(); undoSubmit().click();
    await wait(() => state.undo_lost && !undoSubmit().disabled);
    if (state.later) await originalFetch("/ignore-later", {method: "POST"});
    state.stage = "undoShelf"; save(); location.assign("/web/pending?ledger_id=owner&filter=ready");
  }
  async function finishOriginal() {
    const current = await (await originalFetch("/ignore-current")).json();
    const retained = JSON.parse(localStorage.getItem(prefix + state.ref));
    assert(retained?.values.merchant === "忽略前的原填写" && retained.values.expected_row_version === "4" &&
      retained.values.idempotency_key === state.key, "undo discarded or rebased original financial input");
    state.financial_retained = true;
    assert(!localStorage.getItem("ticketbox:expenseundo-edit-draft:v1:" + state.undoKey), "accepted undo original was not acknowledged");
    if (state.later) {
      assert(current.status === "rejected" && current.version === 9 && current.merchant === "同伴后来再次忽略", "old undo overwrote later ignore");
      window.__expenseReviewResult = state; return;
    }
    assert(current.status === "pending" && current.version === 6, "undo did not restore pending status");
    document.querySelector('[data-expensereview-scope] summary').click();
    state.stage = "resumeFinancial"; save(); document.querySelector('[data-expensereview-ref="' + state.ref + '"]').click();
    if (state.entry === "drawer") await reviewFinancial();
  }
  async function reviewFinancial() {
    await wait(() => form()?.dataset.expensereviewDraftPhase === "editing");
    const review = form().querySelector("[data-expensereview-review]");
    if (form().elements.merchant.readOnly) assert(review.disabled, "review enabled before the original draft lease was acquired");
    await wait(() => !review.disabled && !form().elements.merchant.readOnly);
    assert(primary().disabled, "financial command acquired undo's current version silently");
    state.stage = "reviewed"; save(); form().requestSubmit(review);
  }
  async function resumeDecision() {
    if (state.stage === "rejectReload") {
      await wait(() => form()?.dataset.expensereviewDraftPhase === "submitted" && !primary().disabled);
      assert(primary().textContent === "核实这次忽略" && form().elements.expected_row_version.value === "4", "reload lost original ignore");
      state.stage = "rejectAccepted"; save(); primary().click();
    } else if (state.stage === "rejectAccepted") await startUndo();
    else if (state.stage === "undoShelf") {
      await wait(() => document.querySelector('[data-expenseundo-ref="' + state.undoKey + '"]'));
      document.querySelector('[data-expenseundo-scope] summary').click();
      state.stage = "undoTask"; save(); document.querySelector('[data-expenseundo-ref="' + state.undoKey + '"]').click();
    } else if (state.stage === "undoTask") {
      await wait(() => undo()?.dataset.expenseundoDraftPhase === "submitted" && !undoSubmit().disabled);
      assert(undo().elements.expected_row_version.value === "5" && undo().elements.idempotency_key.value === state.undoKey, "reopened undo was retargeted");
      state.stage = "undone"; save(); undoSubmit().click();
    }
  }
  try {
    if (state.stage === "edit") await ignoreOriginal();
    else if (["rejectReload", "rejectAccepted", "undoShelf", "undoTask"].includes(state.stage)) await resumeDecision();
    else if (state.stage === "undone") await finishOriginal();
    else if (state.stage === "resumeFinancial") await reviewFinancial();
    else if (state.stage === "reviewed") {
      await wait(() => form()?.dataset.expensereviewDraftPhase === "editing" && !primary().disabled && !form().elements.merchant.readOnly);
      assert(form().elements.merchant.value === "忽略前的原填写" && form().elements.expected_row_version.value === "6", "explicit review lost financial input");
      state.stage = "confirmed"; save(); primary().click();
    } else if (state.stage === "confirmed") {
      assert(document.querySelector("[data-expense-confirmation]"), "confirmed receipt missing");
      window.__expenseReviewResult = state;
    } else throw Error("unexpected navigation at " + state.stage);
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error), url: location.href,
    undoPhase: undo()?.dataset.expenseundoDraftPhase, undoDisabled: undoSubmit()?.disabled,
    body: document.body.textContent.slice(-2200)}; }
})();
