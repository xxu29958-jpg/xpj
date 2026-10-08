/* Actual review routes and forms: lost acknowledgement, reload, original replay and explicit next confirm. */
(async function () {
  "use strict";
  if (sessionStorage.getItem("expense-drawer-probe")) {
    window.__expenseReviewResult = {...JSON.parse(sessionStorage.getItem("expense-drawer-probe")), error: "drawer unexpectedly left the pending queue"};
    return;
  }
  const stateKey = "expense-review-probe", prefix = "ticketbox:expensereview-edit-draft:v1:";
  const state = JSON.parse(sessionStorage.getItem(stateKey) || "null") || {
    operation: new URL(location.href).searchParams.get("probe"), stage: "edit", requests: [],
  };
  const save = () => sessionStorage.setItem(stateKey, JSON.stringify(state));
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const wait = async predicate => {
    for (let n = 0; n < 200; n += 1) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("review consumer did not reach " + state.stage);
  };
  const originalFetch = window.fetch;
  window.fetch = async (url, options) => {
    const path = new URL(url, location.href).pathname;
    if (!/\/expenses\/42\/(save|confirm)$/.test(path)) return originalFetch(url, options);
    // The financial action is identified by its endpoint. CSRF, the action marker and
    // keys for separate related decisions were not part of the legacy financial request.
    state.requests.push({path, fields: [...options.body].filter(([name]) =>
      !["csrf_token", "command_action", "keep_idempotency_key", "reject_idempotency_key"].includes(name))});
    save();
    const response = await originalFetch(url, options);
    if (state.stage === "lost") {
      assert(response.ok, "first save/confirm was not accepted");
      state.stage = "unknown"; save();
      throw Error("accepted response lost");
    }
    return response;
  };
  try {
    if (document.querySelector("[data-expense-confirmation]")) {
      assert(state.stage === "confirm" || state.stage === "replay", "unexpected financial receipt");
      window.__expenseReviewResult = {...state, original_removed: !localStorage.getItem(prefix + state.ref),
        receipt_visible: document.querySelector("[data-expense-confirmation]").textContent.includes("这张，记好了")};
      return;
    }
    const form = document.querySelector("form.edit-form"), field = name => form.elements.namedItem(name);
    const primary = form.querySelector("[data-expensereview-submit]");
    await wait(() => form.dataset.expensereviewDraftPhase && !primary.disabled);
    if (state.stage === "edit") {
      field("merchant").value = "浏览器原填写";
      field("merchant").dispatchEvent(new Event("input", {bubbles: true}));
      state.key = field("idempotency_key").value; state.ref = field("draft_ref").value;
      state.stage = "lost"; save();
      const submit = state.operation === "save" ? [...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿") : primary;
      form.requestSubmit(submit);
      await wait(() => state.stage === "unknown" && form.querySelector("[data-expensereview-draft-status]").textContent.includes("暂未收到"));
      if (state.operation === "legacy-confirm") {
        const record = JSON.parse(localStorage.getItem(prefix + state.ref));
        const laterFields = ["command_action", "keep_idempotency_key", "reject_idempotency_key"];
        laterFields.forEach(name=>delete record.values[name]);
        record.values.present_fields = JSON.stringify(JSON.parse(record.values.present_fields).filter(name => !laterFields.includes(name)));
        localStorage.setItem(prefix + state.ref, JSON.stringify(record));
      }
      location.reload();
    } else if (state.stage === "unknown") {
      assert(form.dataset.expensereviewDraftPhase === "submitted", "original submission was replaced by an editable draft");
      assert(field("merchant").value === "浏览器原填写" && field("idempotency_key").value === state.key, "original input or key changed");
      assert(field("expected_row_version").value === "4", "original basis was replaced by the saved version");
      state.stage = "replay"; save();
      form.requestSubmit(primary);
    } else if (state.stage === "replay") {
      assert(state.operation === "save", "confirmation unexpectedly returned an editor");
      assert(!localStorage.getItem(prefix + state.ref), "acknowledged save left its original unresolved");
      assert(field("idempotency_key").value !== state.key && field("expected_row_version").value === "5", "save did not prepare a fresh confirm");
      state.fresh_key = field("idempotency_key").value;
      state.stage = "confirm"; save();
      form.requestSubmit(primary);
    }
  } catch (error) {
    window.__expenseReviewResult = {...state, error: String(error)};
  }
})();
