/* Real pending queue and drawer: input reload, lost save response, original replay, next and final receipt. */
(async function () {
  "use strict";
  const key = "expense-drawer-probe", prefix = "ticketbox:expensereview-edit-draft:v1:";
  const state = JSON.parse(sessionStorage.getItem(key) || "null") || {stage: "edit", requests: [], positions: []};
  const receiptReadFailure = new URL(location.href).searchParams.get("probe") === "receipt-read-failure";
  const storageFailure = new URL(location.href).searchParams.get("probe") === "storage-failure";
  const save = () => sessionStorage.setItem(key, JSON.stringify(state));
  window.addEventListener("error", event => { state.runtime_error = event.message; save(); });
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async predicate => {
    for (let n = 0; n < 200; n += 1) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("drawer did not reach " + state.stage);
  };
  const form = () => document.querySelector("#drawer [data-drawer-form]");
  const primary = () => form()?.querySelector('[data-expensereview-submit]');
  const fetch = window.fetch;
  window.fetch = async (url, options) => {
    const path = new URL(url, location.href).pathname;
    if (receiptReadFailure && path.includes("/confirmation/") && !state.readFailed) {
      state.readFailed = true; return new Response("unavailable", {status: 503});
    }
    if (options?.method !== "POST" || !/\/expenses\/\d+\/(save|confirm)$/.test(path)) return fetch(url, options);
    state.requests.push({path, fields: [...options.body].filter(([name]) => name !== "csrf_token")}); save();
    const response = await fetch(url, options);
    if (state.stage === "lost") {
      assert(response.ok, "save not accepted"); state.stage = "unknown"; save();
      throw Error("save reply lost");
    }
    return response;
  };
  async function verifyUnretainedInput() {
    const write = Storage.prototype.setItem;
    Storage.prototype.setItem = function (name, value) {
      if (name.startsWith(prefix)) throw Error("storage unavailable");
      return write.call(this, name, value);
    };
    form().elements.merchant.value = "尚未落盘的填写";
    form().elements.merchant.dispatchEvent(new Event("input", {bubbles:true}));
    assert(form().querySelector("[data-expensereview-draft-status]").textContent.includes("未能保留"), "storage failure was hidden");
    const current = form(); TicketboxWeb.drawerApi.close();
    assert(form() === current && form().elements.merchant.value === "尚未落盘的填写", "closing discarded unretained input");
    Storage.prototype.setItem = write;
    form().elements.merchant.dispatchEvent(new Event("input", {bubbles:true}));
    TicketboxWeb.drawerApi.close();
    assert(!TicketboxWeb.drawerApi.isOpen(), "restored persistence did not allow leaving");
    window.__expenseReviewResult = {storage_recovered: true, requests: state.requests}; return;
  }
  try {
    await wait(() => window.TicketboxWeb?.drawerApi);
    const mount = window.TicketboxExpenseReview.mount;
    window.TicketboxExpenseReview.mount = (...args) => {
      try { return mount(...args); }
      catch (error) { state.runtime_error = error.stack; save(); throw error; }
    };
    if (!window.TicketboxWeb.drawerApi.isOpen()) document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    await wait(() => form()?.dataset.expensereviewDraftPhase && primary() && !primary().disabled);
    if (storageFailure) {
      await verifyUnretainedInput(); return;
    }
    if (receiptReadFailure) {
      const ref = form().elements.draft_ref.value;
      form().requestSubmit(primary());
      await wait(() => document.querySelector("#drawer h2")?.textContent === "这次确认已入账");
      const link = document.querySelector("#drawer a");
      const receipt = await (await window.fetch(link.href)).text();
      assert(receipt.includes("128.60") && receipt.includes("首次便利店"), "accepted receipt could not be read independently");
      window.__expenseReviewResult = {...state, original_removed: !localStorage.getItem(prefix + ref)};
      return;
    }
    if (state.stage === "edit") {
      const menu = form().querySelector(".review-more-actions"); menu.open = true;
      menu.querySelector("summary").dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
      assert(!menu.open && TicketboxWeb.drawerApi.isOpen(), "Escape closed drawer before its menu");
      const input = form().elements.merchant;
      input.value = "抽屉原填写"; input.dispatchEvent(new Event("input", {bubbles: true}));
      state.ref = form().elements.draft_ref.value; state.command = form().elements.idempotency_key.value;
      document.querySelector('.exp-row[data-expense-id="43"] .exp-row-detail').click();
      await wait(() => form()?.elements.expense_id.value === "43" && !primary()?.disabled);
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
      await wait(() => form()?.elements.expense_id.value === "42" && !primary()?.disabled);
      assert(form().elements.merchant.value === "抽屉原填写", "switching rows lost original input");
      TicketboxWeb.drawerApi.close();
      const selected = document.querySelector('.exp-row[data-expense-id="42"] .row-check'); selected.click();
      document.querySelector("[data-bulk]").requestSubmit();
      assert(document.querySelector("#bulk-flash").textContent.includes("先保存草稿"), "closed retained task did not block bulk overwrite");
      state.stage = "reload"; save(); location.reload(); return;
    }
    assert(form().elements.merchant.value === "抽屉原填写", "refresh lost the drawer's original input");
    assert(form().elements.idempotency_key.value === state.command, "refresh replaced the original command key");
    if (state.stage === "reload") {
      state.stage = "lost"; save();
      form().requestSubmit([...form().querySelectorAll("button")].find(button => button.textContent === "保存草稿"));
      await wait(() => form().querySelector("[data-expensereview-draft-status]")?.textContent.includes("暂未收到"));
      location.reload(); return;
    }
    assert(state.stage === "unknown" && form().dataset.expensereviewDraftPhase === "submitted", "lost save became a new editable task");
    state.stage = "replay"; save();
    document.querySelector('.exp-row[data-expense-id="42"] .row-check').click();
    form().requestSubmit(form().querySelector("[data-expensereview-submit]"));
    await wait(() => form()?.elements.idempotency_key.value !== state.command && form()?.dataset.expensereviewDraftPhase && !primary()?.disabled);
    assert(!localStorage.getItem(prefix + state.ref), "accepted save left its original unresolved");
    assert(form().elements.expected_row_version.value === "5", "saved drawer has stale OCC");
    assert(document.querySelector('.exp-row[data-expense-id="42"] .row-check').value === "42:5", "queue still has old OCC");
    await wait(() => document.querySelector('.exp-row[data-expense-id="42"] .exp-merch').textContent === "抽屉原填写");
    assert(document.querySelector('.exp-row[data-expense-id="42"] .row-check').checked, "save cleared the selected row");
    assert(document.querySelector('.exp-row[data-expense-id="42"] [name="expense_snapshot"][type="hidden"]').value === "42:5", "quick confirm has stale OCC");
    assert(document.querySelector('#bulk-form [name="expected_row_version"]').value === "5", "bulk has stale OCC");
    state.positions.push(document.querySelector("#drawer [data-review-position]").textContent);
    state.stage = "first-confirm"; save();
    form().requestSubmit(primary());
    await wait(() => document.querySelector("#drawer [data-expense-confirmation]"));
    state.first_receipt = document.querySelector("#drawer [data-expense-confirmation]").textContent.includes("128.60");
    await wait(() => form()?.elements.expense_id.value === "43" && !primary()?.disabled);
    assert(!document.querySelector('.exp-row[data-expense-id="42"]'), "accepted row remained in queue");
    state.positions.push(document.querySelector("#drawer [data-review-position]").textContent);
    state.stage = "last-confirm"; save();
    form().requestSubmit(primary());
    await wait(() => document.querySelector("#drawer [data-expense-confirmation]"));
    const receipt = document.querySelector("#drawer [data-expense-confirmation]");
    assert(receipt.querySelector("[data-confirmation-next]").hidden, "last receipt offers missing next row");
    assert(receipt.querySelector("[data-confirmation-finish]").href.includes("filter=ready"), "receipt lost original filter");
    window.__expenseReviewResult = {...state, last_receipt: receipt.textContent.includes("第二张商家"),
      original_removed: !Object.keys(localStorage).some(item => item.startsWith(prefix))};
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error),
    phase: form()?.dataset.expensereviewDraftPhase, status: form()?.querySelector("[data-expensereview-draft-status]")?.textContent}; }
})();
