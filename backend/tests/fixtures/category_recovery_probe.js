/* Real selected batch: detail return, lost reply, later facts, original receipt, remaining work. */
(async function () {
  "use strict";
  const name = "category-recovery-probe", prefix = "ticketbox:categorybatch-create-draft:v1:";
  const state = JSON.parse(sessionStorage.getItem(name) || "null") || {stage: "select", requests: []};
  const save = () => sessionStorage.setItem(name, JSON.stringify(state));
  const assert = (value, message) => { if (!value) throw Error(message); };
  const form = () => document.querySelector(".uncategorized-form");
  const primary = () => form()?.querySelector("[data-category-apply]");
  const wait = async predicate => {
    for (let n = 0; n < 200; n++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
    throw Error("category recovery stalled at " + state.stage);
  };
  const selected = () => [...form().querySelectorAll('[name="expense_snapshot"]:checked')].map(input => input.value).sort();
  const originalFetch = window.fetch;
  window.fetch = async (url, options) => {
    if (!new URL(url, location.href).pathname.endsWith("/uncategorized/bulk-set")) return originalFetch(url, options);
    state.requests.push([...options.body].filter(([key]) => key !== "csrf_token")); save();
    const response = await originalFetch(url, options);
    if (!state.lost) {
      assert(response.ok && (await response.clone().json()).receipt.result.success_ids.join() === "42", "first batch did not partially apply");
      await response.text(); state.lost = true; save(); throw new TypeError("accepted category reply lost");
    }
    return response;
  };
  try {
    if (state.stage === "detail") {
      assert(location.pathname === "/web/expenses/42/edit", "selected bill did not open its actual detail");
      const back = document.querySelector('a[href*="/web/categories/uncategorized"][href*="draft_ref="]');
      assert(back && back.href.includes(state.ref), "detail lost the original category task");
      state.stage = "returned"; save(); back.click(); return;
    }
    await wait(() => form()?.dataset.categorybatchDraftPhase);
    if (state.stage === "select") {
      await wait(() => !form().querySelector('[name="expense_snapshot"]').disabled);
      for (const token of ["42:4", "44:4"]) {
        const input = form().querySelector('[name="expense_snapshot"][value="' + token + '"]');
        input.checked = true; input.dispatchEvent(new Event("change", {bubbles: true}));
      }
      const category = form().querySelector('[name="category"][value="自选分类"]');
      category.checked = true; category.dispatchEvent(new Event("change", {bubbles: true}));
      state.ref = form().elements.draft_ref.value; state.command = form().elements.idempotency_key.value;
      state.stage = "detail"; save(); form().querySelector('[data-category-row="42"] a').click(); return;
    }
    if (state.stage === "returned") {
      await wait(() => !primary().disabled);
      assert(selected().join() === "42:4,44:4" && form().elements.category.value === "自选分类" &&
        form().elements.idempotency_key.value === state.command, "detail return changed the original selection, category or key");
      state.detail_return = true;
      await originalFetch("/category-later/before", {method: "POST"});
      primary().click();
      await wait(() => state.lost && !primary().disabled);
      assert(JSON.parse(localStorage.getItem(prefix + state.ref)).phase === "submitted", "unknown batch was not retained");
      await originalFetch("/category-later/after", {method: "POST"});
      state.stage = "reloaded"; save(); location.reload(); return;
    }
    if (state.stage === "reloaded") {
      await wait(() => !primary().disabled);
      assert(selected().join() === "42:4,44:4" && form().elements.category.value === "自选分类" &&
        form().elements.idempotency_key.value === state.command, "reload replaced an unknown original with current rows");
      assert(primary().textContent === "核实本次分类结果" && form().querySelector('[name="expense_snapshot"]').disabled &&
        form().querySelector("[data-categorybatch-review]").hidden, "unknown original can be edited before its result is known");
      state.original_restored = true; state.stage = "receipt"; save(); primary().click(); return;
    }
    if (state.stage === "receipt") {
      await wait(() => !primary().disabled);
      assert(document.body.textContent.includes("已更新 1 条") && document.body.textContent.includes("跳过 1 条") &&
        selected().join() === "44:4", "first partial result or remaining original selection was lost");
      const remaining = JSON.parse(localStorage.getItem(prefix + state.ref));
      assert(remaining?.phase === "editing" && remaining.values.origin_receipt === state.command &&
        JSON.parse(remaining.values.selected_rows).map(row => row.snapshot).join() === "44:4" &&
        remaining.values.idempotency_key !== state.command, "partial acceptance lost the unsubmitted remainder or its first receipt");
      state.stage = "resume-remainder"; save(); location.assign("/web/categories/uncategorized?ledger_id=owner"); return;
    }
    if (state.stage === "resume-remainder") {
      await wait(() => !primary().disabled);
      assert(selected().join() === "44:4" && form().elements.origin_receipt.value === state.command,
        "returning from the product entry lost the remaining original task");
      state.stage = "remaining-result"; save(); form().querySelector("[data-category-result]").click(); return;
    }
    if (state.stage === "remaining-result") {
      await wait(() => !primary().disabled);
      assert(document.body.textContent.includes("已更新 1 条") && document.body.textContent.includes("跳过 1 条"),
        "remaining task cannot reopen the first partial receipt");
      state.nextCommand = form().elements.idempotency_key.value; state.stage = "reviewed"; save();
      form().requestSubmit(form().querySelector("[data-categorybatch-review]")); return;
    }
    if (state.stage === "reviewed") {
      await wait(() => !primary().disabled);
      assert(selected().join() === "44:8" && form().elements.category.value === "自选分类" &&
        form().elements.idempotency_key.value !== state.nextCommand, "explicit review did not prepare the remaining current basis");
      state.stage = "finished"; save(); primary().click(); return;
    }
    if (state.stage === "finished") {
      assert(document.body.textContent.includes("已更新 1 条") && !selected().length, "remaining batch did not finish");
      state.partial_continued = true; window.__expenseReviewResult = state;
    }
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error), body: document.body.innerText.slice(-2200)}; }
})();
